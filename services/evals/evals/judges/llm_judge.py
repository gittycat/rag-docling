"""LLM-as-judge for evaluation metrics.

Uses a configurable LLM to evaluate answers for:
- Faithfulness (grounding in context)
- Answer correctness (vs expected answer)
- Answer relevancy (to the question)
"""

import logging
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from llama_index.core.llms import LLM

from evals.config import JudgeConfig
from evals.judges.outputs import (
    JUDGE_CONTRACT_VERSION,
    JudgeError,
    JudgeParseError,
    judge_response_format,
    output_format_instructions,
    parse_judge_response,
    response_format_rejected,
    supports_structured_output,
)

logger = logging.getLogger(__name__)

# JudgeError and JudgeParseError live in evals.judges.outputs so the parser can
# raise them without importing the judge. They are re-exported here because that
# is where every caller already imports them from.
__all__ = ["JudgeError", "JudgeParseError", "JudgeResult", "LLMJudge"]


def check_judge_independence(
    inference_provider: str, judge_provider: str
) -> str | None:
    """Return a warning if the judge shares a provider with the generation model.

    Self-preference bias in LLM judges is documented to extend across a model
    family, not only to an identical model. A same-provider pairing is therefore
    not a neutral referee for the comparison users most want to run — local versus
    cloud generation — and the bias points the wrong way for exactly that test.
    """
    if not inference_provider or not judge_provider:
        return None
    if inference_provider.lower() != judge_provider.lower():
        return None
    return (
        f"Judge and generation model share provider '{judge_provider}'. "
        f"LLM judges show self-preference bias across a model family, so scores "
        f"for this provider's own generations are likely inflated. Point "
        f"active.eval at a different provider for a neutral comparison."
    )


def warn_if_judge_not_independent() -> str | None:
    """Emit the same-provider warning for the active config. Never raises."""
    try:
        from infrastructure.config.models_config import get_models_config

        config = get_models_config()
        warning = check_judge_independence(config.llm.provider, config.eval.provider)
    except Exception as e:
        logger.debug(f"[JUDGE] Could not check judge independence: {e}")
        return None

    if warning:
        logger.warning(f"[JUDGE] {warning}")
    return warning


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

    def __init__(
        self,
        config: JudgeConfig,
        cache: Any | None = None,
        usage_sink: Callable[[int, int], None] | None = None,
    ):
        """Initialize the judge with an already-resolved config.

        There is deliberately no fallback. A hidden `config or _load_default()`
        used to exist here and never ran, because both entry points passed a
        JudgeConfig whose provider/model defaults pointed at Anthropic. Callers
        resolve the judge explicitly with evals.config.resolve_judge_config().

        Args:
            config: Resolved judge configuration.
            cache: Optional ResponseCache. Judge calls are deterministic at
                temperature 0, so an identical prompt need not be paid for twice.
            usage_sink: Called `(prompt_tokens, completion_tokens)` after every
                call that reached the endpoint. Cache hits cost nothing and do
                not report. `UsageTotals.record` is what the runner passes; the
                attribute is public so it can also be assigned after construction.
        """
        if config is None:
            raise ValueError(
                "LLMJudge requires a resolved JudgeConfig. Call "
                "evals.config.resolve_judge_config() — the judge identity comes "
                "from active.eval in config.yml and is never defaulted."
            )
        self.config = config
        self._llm: LLM | None = None
        self._cache = cache
        self.usage_sink = usage_sink
        # Whether to constrain the reply with a JSON schema. Starts from what the
        # provider's transport is known to support and is turned off for the rest
        # of this judge's life the first time an endpoint rejects the field.
        self._structured_output = supports_structured_output(config.provider)

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
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            temperature=self.config.temperature,
        )

        logger.info(
            f"[JUDGE] Creating {provider.value} LLM: {self.config.model} "
            f"(boundary={self.config.execution_boundary or 'unknown'}, "
            f"temperature={self.config.temperature})"
        )
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
- 0.0: The answer contains claims that contradict or are not supported by the context"""

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
- 0.0: The answer is incorrect or contradicts the reference"""

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
- 0.0: The answer does not address the question at all"""

        return await self._evaluate(prompt, "relevancy")

    async def evaluate_entailment(
        self,
        claim: str,
        passage: str,
    ) -> JudgeResult:
        """Evaluate whether a single passage entails a single claim.

        Deliberately narrower than `evaluate_faithfulness`, which judges a whole
        answer against a whole context in one call and so cannot tell which
        sentence the ungrounded part was in — or which of the cited passages was
        supposed to support it.

        The rubric forbids outside knowledge: a claim that is true in the world
        but absent from this passage is not supported *by this passage*, and that
        is the whole question a citation makes.
        """
        prompt = f"""You are checking whether a single passage supports a single claim.
Judge only against the passage. A claim that is true in general but not stated or
implied by this passage is NOT supported.

Passage:
{passage}

Claim:
{claim}

Score the support on a scale of 0 to 1:
- 1.0: The passage states or directly implies the claim
- 0.5: The passage supports part of the claim; the rest is not stated in it
- 0.0: The passage does not support the claim, or contradicts it"""

        return await self._evaluate(prompt, "entailment")

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
- 0.0: None of the context is useful for answering the question"""

        return await self._evaluate(prompt, "context_relevance")

    def _cache_parts(self, prompt_body: str, structured: bool) -> list[Any]:
        """Everything that can change a judge verdict for the same question.

        The key used to be (provider, model, temperature, prompt). That silently
        reused scores across a changed endpoint and a changed output contract:
        repointing base_url at a different vLLM container, or switching between
        schema-constrained and free-text answers, both produce different verdicts
        under an identical key.

        Still missing, because JudgeConfig cannot see them: model revision /
        commit hash, quantization, the serving stack's version and the chat
        template. Two vLLM containers serving "Qwen/Qwen3-32B-AWQ" at different
        revisions remain indistinguishable here. Closing that needs a fingerprint
        carried in config.yml or read back from the endpoint - recorded as a
        follow-up, not solved here.
        """
        return [
            self.config.provider,
            self.config.model,
            self.config.base_url,
            self.config.temperature,
            self.config.execution_boundary,
            JUDGE_CONTRACT_VERSION,
            "structured" if structured else "text",
            prompt_body,
        ]

    async def _acomplete(self, prompt: str) -> Any:
        """One judge call, downgrading to free text if the endpoint refuses the schema."""
        if self._structured_output:
            try:
                return await self.llm.acomplete(
                    prompt, response_format=judge_response_format()
                )
            except Exception as e:
                if not response_format_rejected(e):
                    raise
                logger.warning(
                    f"[JUDGE] Endpoint rejected schema-constrained output "
                    f"({self.config.provider}/{self.config.model}): {e}. "
                    f"Falling back to SCORE:/REASONING: text parsing for this judge."
                )
                self._structured_output = False
        return await self.llm.acomplete(prompt)

    def _record_usage(self, response: Any) -> None:
        """Report one endpoint call's token usage to the sink. Never raises.

        The sink is what makes judge tokens visible to `CostPerQuery`. Without it
        an eval run reported the generation model's cost as the run's cost, while
        judging — three or more calls per question against the generation model's
        one — was billed at exactly zero.

        A provider that reports no usage block still counts as a call: the sink
        records it with zero tokens so `calls` and `calls_without_usage` together
        explain a zero judge cost, instead of leaving it indistinguishable from a
        sink that never fired.
        """
        if self.usage_sink is None:
            return
        try:
            tokens = _usage_tokens(_token_usage(response))
            if tokens is None:
                logger.debug(
                    f"[JUDGE] {self.config.provider}/{self.config.model} reported no "
                    f"token usage; the call is counted, its tokens are not."
                )
                self.usage_sink(0, 0)
                return
            self.usage_sink(*tokens)
        except Exception as e:
            # Accounting must never fail a judgement that already succeeded.
            logger.warning(f"[JUDGE] Could not record token usage: {e}")

    async def _evaluate(self, prompt_body: str, metric_name: str) -> JudgeResult:
        """Run evaluation with retry logic using async LLM call.

        Raises JudgeError once retries are exhausted. Returning a 0.0 score here
        would be indistinguishable from a genuine "not grounded at all" verdict
        and would drag every batch average down on transient flakiness.

        `prompt_body` carries the rubric only; the output-format instructions are
        appended per attempt so a mid-run downgrade from schema-constrained to
        free text also changes what the model is asked for.
        """
        cache_parts = self._cache_parts(prompt_body, self._structured_output)
        if self._cache is not None:
            cached = self._cache.get("judge", cache_parts)
            if cached is not None:
                return JudgeResult(
                    metric_name=metric_name,
                    score=cached["score"],
                    reasoning=cached.get("reasoning", ""),
                    raw_response=cached.get("raw_response", ""),
                    metadata={"cached": True},
                )

        last_error: Exception | None = None

        for attempt in range(self.config.max_retries):
            prompt = f"{prompt_body}\n\n{output_format_instructions(self._structured_output)}"
            try:
                response = await self._acomplete(prompt)
                # Before parsing, not after: an unparseable reply still consumed
                # the tokens that produced it, and a retry loop that only counted
                # parseable answers would under-report exactly the runs that cost
                # the most.
                self._record_usage(response)
                # Read after the call: _acomplete clears the flag if the endpoint
                # refused the schema, and the cache key must record the contract
                # the answer was actually produced under.
                structured = self._structured_output
                raw_response = str(response)

                parsed = parse_judge_response(raw_response)

                if self._cache is not None:
                    self._cache.set(
                        "judge",
                        self._cache_parts(prompt_body, structured),
                        {
                            "score": parsed.score,
                            "reasoning": parsed.reasoning,
                            "raw_response": raw_response,
                        },
                    )

                return JudgeResult(
                    metric_name=metric_name,
                    score=parsed.score,
                    reasoning=parsed.reasoning,
                    raw_response=raw_response,
                    metadata={
                        "attempt": attempt + 1,
                        "structured_output": parsed.structured,
                        # The raw usage block as the transport reported it, kept
                        # per result for debugging. The run-level total that
                        # CostPerQuery prices comes from usage_sink, not from
                        # re-aggregating these.
                        "token_usage": _token_usage(response),
                    },
                )

            except Exception as e:
                last_error = e
                logger.warning(f"[JUDGE] Attempt {attempt + 1} failed: {e}")

        logger.error(f"[JUDGE] All attempts failed for {metric_name}: {last_error}")
        raise JudgeError(f"{metric_name} evaluation failed after "
                         f"{self.config.max_retries} attempts: {last_error}") from last_error

    def _parse_response(self, response: str) -> tuple[float, str]:
        """Parse the score and reasoning from an LLM response.

        Accepts either output form. Raises JudgeParseError on malformed output so
        _evaluate's retry loop engages — an unreadable response is a failed call,
        not a 0.0.
        """
        parsed = parse_judge_response(response)
        return parsed.score, parsed.reasoning


# Provider naming for the same two numbers. OpenAI-compatible transports say
# prompt/completion, Anthropic says input/output; both shapes reach here unchanged
# because _token_usage reports what the transport gave rather than normalizing it.
_PROMPT_KEYS = ("prompt_tokens", "input_tokens")
_COMPLETION_KEYS = ("completion_tokens", "output_tokens")


def _usage_tokens(usage: dict[str, Any] | None) -> tuple[int, int] | None:
    """(prompt, completion) token counts from a provider usage block, or None."""
    if not usage:
        return None

    def _first(keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        return None

    prompt = _first(_PROMPT_KEYS)
    completion = _first(_COMPLETION_KEYS)
    if prompt is None and completion is None:
        return None
    return prompt or 0, completion or 0


def _token_usage(response: Any) -> dict[str, Any] | None:
    # LlamaIndex hangs the provider payload off `raw`; shapes differ per provider,
    # so this reports what is there rather than normalizing it.
    raw = getattr(response, "raw", None)
    usage = getattr(raw, "usage", None)
    if usage is None and isinstance(raw, dict):
        usage = raw.get("usage")
    if usage is None:
        return None
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage) if isinstance(usage, dict) else None
