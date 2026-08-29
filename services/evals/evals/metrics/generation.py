"""Generation quality metrics.

Measures answer quality using LLM-as-judge evaluation.
"""

import asyncio
from typing import Any

from evals.config import resolve_judge_config
from evals.metrics.base import BaseMetric
from evals.judges import LLMJudge
from evals.schemas import (
    EvalQuestion,
    EvalResponse,
    MetricResult,
    MetricGroup,
)


def _lazy_judge() -> LLMJudge:
    """Resolve a judge for a metric constructed without one.

    This path knows no dataset and no tier, so the boundary gate fails closed by
    design. The runner always injects a judge (runner.py), so reaching here means
    the metric was built outside a run — say the fix in the error, not a
    permissive default.
    """
    try:
        return LLMJudge(resolve_judge_config())
    except ValueError as e:
        raise ValueError(
            f"{e}\n\nThis metric was constructed without a judge, so the gate could "
            f"not see which datasets or tier are in play and refused by default. "
            f"Pass a judge explicitly — Faithfulness(judge=...) — or build the metric "
            f"through EvalRunner, which injects one resolved against the run's "
            f"datasets and tier."
        ) from e



class Faithfulness(BaseMetric):
    """Faithfulness measures whether the answer is grounded in the retrieved context.

    A faithful answer only makes claims that are supported by the context.
    Uses LLM-as-judge to evaluate.

    Higher is better. 1.0 means fully grounded in context.
    """

    def __init__(self, judge: LLMJudge | None = None):
        self._judge = judge

    @property
    def judge(self) -> LLMJudge:
        if self._judge is None:
            # Resolved from active.eval, explicitly — LLMJudge has no default.
            self._judge = _lazy_judge()
        return self._judge

    @property
    def name(self) -> str:
        return "faithfulness"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.GENERATION

    @property
    def description(self) -> str:
        return "Whether the answer is grounded in the retrieved context"

    @property
    def requires_judge(self) -> bool:
        return True

    async def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        context = "\n\n".join(
            chunk.text for chunk in response.retrieved_chunks
        )

        if not context:
            return MetricResult(
                name=self.name,
                # A retrieval miss makes grounding unassessable: calling it an
                # unfaithful answer would attribute an upstream absence of
                # evidence to generation. Keep it distinct from a judged 0.0.
                value=None,
                group=self.group,
                sample_size=0,
                details={"note": "No context retrieved; faithfulness is unassessable"},
            )

        result = await self.judge.evaluate_faithfulness(
            answer=response.answer,
            context=context,
        )

        return MetricResult(
            name=self.name,
            value=result.score,
            group=self.group,
            sample_size=1,
            details={
                "reasoning": result.reasoning,
                "context_length": len(context),
            },
        )


class AnswerCorrectness(BaseMetric):
    """Answer correctness measures whether the answer matches the expected answer.

    Uses LLM-as-judge to evaluate semantic equivalence.

    Higher is better. 1.0 means fully correct.
    """

    def __init__(self, judge: LLMJudge | None = None):
        self._judge = judge

    @property
    def judge(self) -> LLMJudge:
        if self._judge is None:
            # Resolved from active.eval, explicitly — LLMJudge has no default.
            self._judge = _lazy_judge()
        return self._judge

    @property
    def name(self) -> str:
        return "answer_correctness"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.GENERATION

    @property
    def description(self) -> str:
        return "Whether the answer matches the expected reference answer"

    @property
    def requires_gold(self) -> bool:
        return True

    @property
    def requires_judge(self) -> bool:
        return True

    async def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        if not question.expected_answer:
            return MetricResult(
                name=self.name,
                value=0.0,
                group=self.group,
                sample_size=1,
                details={"note": "No expected answer defined"},
            )

        result = await self.judge.evaluate_correctness(
            answer=response.answer,
            expected_answer=question.expected_answer,
            question=question.question,
        )

        return MetricResult(
            name=self.name,
            value=result.score,
            group=self.group,
            sample_size=1,
            details={
                "reasoning": result.reasoning,
                "expected_answer": question.expected_answer[:200],
            },
        )


class AnswerCompleteness(BaseMetric):
    """Fraction of pre-derived reference facts entailed by the answer."""

    def __init__(self, judge: LLMJudge | None = None):
        self._judge = judge

    @property
    def judge(self) -> LLMJudge:
        if self._judge is None:
            self._judge = _lazy_judge()
        return self._judge

    @property
    def name(self) -> str:
        return "answer_completeness"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.GENERATION

    @property
    def description(self) -> str:
        return "Fraction of required answer nuggets covered by the answer"

    @property
    def requires_gold(self) -> bool:
        return True

    @property
    def requires_judge(self) -> bool:
        return True

    async def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        if not question.answer_nuggets:
            return MetricResult(
                name=self.name,
                value=None,
                group=self.group,
                sample_size=0,
                details={"note": "No answer nuggets defined for this question"},
            )

        verdicts = await asyncio.gather(
            *(
                self.judge.evaluate_entailment(claim=nugget, passage=response.answer)
                for nugget in question.answer_nuggets
            ),
            return_exceptions=True,
        )
        scored = [
            (nugget, verdict)
            for nugget, verdict in zip(question.answer_nuggets, verdicts)
            if not isinstance(verdict, BaseException)
        ]
        if not scored:
            return MetricResult(
                name=self.name,
                value=None,
                group=self.group,
                sample_size=0,
                details={"note": "Every nugget entailment call failed"},
            )

        scores = [verdict.score for _, verdict in scored]
        return MetricResult(
            name=self.name,
            value=sum(scores) / len(scores),
            group=self.group,
            sample_size=1,
            details={
                "nugget_count": len(question.answer_nuggets),
                "judged_nuggets": len(scored),
                "nuggets": [
                    {"text": nugget, "score": verdict.score, "reasoning": verdict.reasoning}
                    for nugget, verdict in scored
                ],
                "missing_nuggets": [
                    nugget for nugget, verdict in scored if verdict.score < 0.5
                ],
                "failed_nuggets": len(question.answer_nuggets) - len(scored),
            },
        )


class ContextualPrefixFactuality(BaseMetric):
    """Fraction of persisted contextual prefixes supported by their source text."""

    def __init__(self, judge: LLMJudge, stages: list[Any], chunk_text: dict[str, str] | None = None):
        self.judge = judge
        self.stages = stages
        # chunk_id -> text, supplied by the runner. Ingestion stage rows record
        # only the chunk index, so the source text is joined at metric time.
        self._chunk_text = chunk_text

    @property
    def name(self) -> str:
        return "contextual_prefix_factuality"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.GROUNDEDNESS

    @property
    def description(self) -> str:
        return "Fraction of contextual prefixes supported by their source chunk"

    @property
    def requires_gold(self) -> bool:
        return False

    @property
    def requires_judge(self) -> bool:
        return True

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        raise NotImplementedError("Contextual prefix factuality is computed from ingestion stages")

    async def compute_batch(
        self,
        questions: list[EvalQuestion],
        responses: list[EvalResponse],
        progress_callback: Any | None = None,
        concurrency: int = 10,
        **kwargs: Any,
    ) -> MetricResult:
        # Stage rows carry the prefix and the chunk it was written from by
        # index, not a second copy of the chunk text; join it back here.
        chunk_text = self._chunk_text or {}
        pending = [
            (stage, record)
            for stage in self.stages
            if stage.name == "contextual_enrich"
            for record in stage.contextual_prefixes
            if record.get("prefix")
        ]
        records = []
        unjoined = 0
        for stage, record in pending:
            index = record.get("chunk_index")
            source = (
                chunk_text.get(f"{stage.document_id}-chunk-{index}")
                if index is not None
                else None
            ) or record.get("source_text")
            if not source:
                unjoined += 1
                continue
            records.append({"prefix": record["prefix"], "source_text": source})
        if not records:
            note = (
                "Contextual prefixes were recorded but their source chunks could "
                "not be joined; the metric needs chunk text, which the runner "
                "fetches only when the groundedness judge is enabled."
                if unjoined
                else "No contextual prefix/source pairs were recorded"
            )
            return MetricResult(
                name=self.name,
                value=None,
                group=self.group,
                sample_size=0,
                details={"note": note, "unjoined_prefixes": unjoined},
            )

        sem = asyncio.Semaphore(max(1, concurrency))
        completed = 0

        async def score(record: dict[str, str]):
            nonlocal completed
            async with sem:
                try:
                    return await self.judge.evaluate_entailment(
                        claim=record["prefix"], passage=record["source_text"]
                    )
                finally:
                    completed += 1
                    if progress_callback:
                        progress_callback(completed)

        verdicts = await asyncio.gather(*(score(record) for record in records), return_exceptions=True)
        scored = [
            (record, verdict)
            for record, verdict in zip(records, verdicts)
            if not isinstance(verdict, BaseException)
        ]
        if not scored:
            return MetricResult(
                name=self.name,
                value=None,
                group=self.group,
                sample_size=0,
                details={"note": "Every contextual-prefix entailment call failed"},
            )
        scores = [verdict.score for _, verdict in scored]
        return MetricResult(
            name=self.name,
            value=sum(scores) / len(scores),
            group=self.group,
            sample_size=len(scored),
            details={
                "individual_scores": scores,
                "prefixes": [
                    {
                        "prefix": record["prefix"],
                        "score": verdict.score,
                        "reasoning": verdict.reasoning,
                    }
                    for record, verdict in scored
                ],
                "failed_prefixes": len(records) - len(scored),
            },
        )


class AnswerRelevancy(BaseMetric):
    """Answer relevancy measures whether the answer addresses the question.

    Uses LLM-as-judge to evaluate relevance.

    Higher is better. 1.0 means fully relevant.
    """

    def __init__(self, judge: LLMJudge | None = None):
        self._judge = judge

    @property
    def judge(self) -> LLMJudge:
        if self._judge is None:
            # Resolved from active.eval, explicitly — LLMJudge has no default.
            self._judge = _lazy_judge()
        return self._judge

    @property
    def name(self) -> str:
        return "answer_relevancy"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.GENERATION

    @property
    def description(self) -> str:
        return "Whether the answer addresses the question asked"

    @property
    def requires_gold(self) -> bool:
        return False

    @property
    def requires_judge(self) -> bool:
        return True

    async def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        result = await self.judge.evaluate_relevancy(
            answer=response.answer,
            question=question.question,
        )

        return MetricResult(
            name=self.name,
            value=result.score,
            group=self.group,
            sample_size=1,
            details={"reasoning": result.reasoning},
        )
