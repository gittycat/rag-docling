"""LLM-as-judge for evaluation metrics.

Uses a configurable LLM to evaluate answers for:
- Faithfulness (grounding in context)
- Answer correctness (vs expected answer)
- Answer relevancy (to the question)
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from llama_index.core.llms import LLM

from evals.config import JudgeConfig

logger = logging.getLogger(__name__)


class JudgeError(Exception):
    """The judge could not produce a score.

    Raised instead of returning a 0.0 score: a failed judge call is missing data,
    not evidence of a bad answer. Callers exclude the sample from the average.
    """


class JudgeParseError(JudgeError):
    """The LLM response contained no parseable SCORE line."""


@dataclass
class JudgeResult:
    """Result from an LLM judge evaluation.

    Attributes:
        metric_name: Name of the metric being evaluated
        score: Numeric score (typically 0-1)
        reasoning: LLM's reasoning for the score
        raw_response: Raw LLM response text
        metadata: Additional result metadata
    """

    metric_name: str
    score: float
    reasoning: str = ""
    raw_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMJudge:
    """LLM-as-judge for evaluating RAG responses.

    Uses a separate LLM instance (not the main RAG LLM) to evaluate
    responses for various quality metrics.
    """

    def __init__(self, config: JudgeConfig | None = None):
        """Initialize the judge.

        Args:
            config: Judge configuration. If None, loads from models config.
        """
        self.config = config or self._load_default_config()
        self._llm: LLM | None = None

    def _load_default_config(self) -> JudgeConfig:
        """Load judge config from models.yml."""
        from infrastructure.config.models_config import get_models_config

        models_config = get_models_config()
        eval_config = models_config.eval

        return JudgeConfig(
            enabled=True,
            provider=eval_config.provider,
            model=eval_config.model,
            temperature=0.0,
            max_retries=3,
        )

    @property
    def llm(self) -> LLM:
        """Get or create the judge LLM instance."""
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm

    def _create_llm(self) -> LLM:
        """Create a new LLM client for the judge."""
        from infrastructure.llm.config import LLMConfig, LLMProvider
        from infrastructure.llm.factory import create_llm_client
        from infrastructure.config.models_config import get_models_config

        models_config = get_models_config()
        api_key = models_config.eval.api_key

        try:
            provider = LLMProvider(self.config.provider)
        except ValueError:
            raise ValueError(f"Unsupported judge provider: {self.config.provider}")

        llm_config = LLMConfig(
            provider=provider,
            model=self.config.model,
            api_key=api_key,
            timeout=120.0,
        )

        logger.info(f"[JUDGE] Creating {provider.value} LLM: {self.config.model}")
        return create_llm_client(llm_config)

    async def evaluate_faithfulness(
        self,
        answer: str,
        context: str,
    ) -> JudgeResult:
        """Evaluate whether the answer is faithful to the context."""
        prompt = f"""You are evaluating the faithfulness of an answer to the provided context.
Faithfulness measures whether all claims in the answer are supported by the context.

Context:
{context}

Answer:
{answer}

Evaluate the faithfulness of this answer on a scale of 0 to 1:
- 1.0: All claims are fully supported by the context
- 0.5: Some claims are supported, but others are not or are partially supported
- 0.0: The answer contains claims that contradict or are not supported by the context

Provide your response in the following format:
SCORE: [0.0-1.0]
REASONING: [Your explanation]"""

        return await self._evaluate(prompt, "faithfulness")

    async def evaluate_correctness(
        self,
        answer: str,
        expected_answer: str,
        question: str,
    ) -> JudgeResult:
        """Evaluate whether the answer is correct compared to expected."""
        prompt = f"""You are evaluating the correctness of an answer compared to a reference answer.
Correctness measures whether the answer conveys the same information as the reference.

Question:
{question}

Reference Answer:
{expected_answer}

Generated Answer:
{answer}

Evaluate the correctness on a scale of 0 to 1:
- 1.0: The answer is fully correct and equivalent to the reference
- 0.5: The answer is partially correct or missing some key information
- 0.0: The answer is incorrect or contradicts the reference

Provide your response in the following format:
SCORE: [0.0-1.0]
REASONING: [Your explanation]"""

        return await self._evaluate(prompt, "correctness")

    async def evaluate_relevancy(
        self,
        answer: str,
        question: str,
    ) -> JudgeResult:
        """Evaluate whether the answer is relevant to the question."""
        prompt = f"""You are evaluating the relevancy of an answer to a question.
Relevancy measures whether the answer addresses what the question is asking.

Question:
{question}

Answer:
{answer}

Evaluate the relevancy on a scale of 0 to 1:
- 1.0: The answer directly and completely addresses the question
- 0.5: The answer partially addresses the question or includes irrelevant information
- 0.0: The answer does not address the question at all

Provide your response in the following format:
SCORE: [0.0-1.0]
REASONING: [Your explanation]"""

        return await self._evaluate(prompt, "relevancy")

    async def evaluate_context_relevance(
        self,
        question: str,
        context: str,
    ) -> JudgeResult:
        """Evaluate what fraction of the context is relevant to the question."""
        prompt = f"""You are evaluating how relevant the provided context is to a question.
Context relevance measures what proportion of the context is useful for answering the question.

Question:
{question}

Context:
{context}

Evaluate the context relevance on a scale of 0 to 1:
- 1.0: All of the context is directly useful for answering the question
- 0.5: About half of the context is useful; the rest is unrelated
- 0.0: None of the context is useful for answering the question

Provide your response in the following format:
SCORE: [0.0-1.0]
REASONING: [Your explanation]"""

        return await self._evaluate(prompt, "context_relevance")

    async def _evaluate(self, prompt: str, metric_name: str) -> JudgeResult:
        """Run evaluation with retry logic using async LLM call.

        Raises JudgeError once retries are exhausted. Returning a 0.0 score here
        would be indistinguishable from a genuine "not grounded at all" verdict
        and would drag every batch average down on transient flakiness.
        """
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries):
            try:
                response = await self.llm.acomplete(prompt)
                raw_response = str(response)

                score, reasoning = self._parse_response(raw_response)

                return JudgeResult(
                    metric_name=metric_name,
                    score=score,
                    reasoning=reasoning,
                    raw_response=raw_response,
                    metadata={"attempt": attempt + 1},
                )

            except Exception as e:
                last_error = e
                logger.warning(f"[JUDGE] Attempt {attempt + 1} failed: {e}")

        logger.error(f"[JUDGE] All attempts failed for {metric_name}: {last_error}")
        raise JudgeError(f"{metric_name} evaluation failed after "
                         f"{self.config.max_retries} attempts: {last_error}") from last_error

    def _parse_response(self, response: str) -> tuple[float, str]:
        """Parse the score and reasoning from LLM response.

        Raises JudgeParseError on malformed output so _evaluate's retry loop
        engages — a missing or unparseable SCORE line is a failed call, not a 0.0.
        """
        lines = response.strip().split("\n")
        score: float | None = None
        reasoning = ""

        for line in lines:
            line = line.strip()
            if line.upper().startswith("SCORE:") and score is None:
                score_str = line.split(":", 1)[1].strip()
                # Handle various formats: "0.8", "0.8/1", "80%"
                is_percent = "%" in score_str
                score_str = score_str.replace("/1", "").replace("%", "")
                try:
                    score = float(score_str)
                except ValueError:
                    raise JudgeParseError(f"Unparseable score in judge response: {line!r}")
                if is_percent:
                    score /= 100
                score = max(0.0, min(1.0, score))  # Clamp to 0-1
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        # If reasoning not found in REASONING: line, use remainder of response
        if not reasoning:
            score_line_found = False
            for line in lines:
                if line.upper().startswith("SCORE:"):
                    score_line_found = True
                elif score_line_found:
                    reasoning += line + " "
            reasoning = reasoning.strip()

        if score is None:
            raise JudgeParseError(f"No SCORE line in judge response: {response.strip()[:200]!r}")

        return score, reasoning
