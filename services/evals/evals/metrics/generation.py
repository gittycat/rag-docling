"""Generation quality metrics.

Measures answer quality using LLM-as-judge evaluation.
"""

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
                value=0.0,
                group=self.group,
                sample_size=1,
                details={"note": "No context retrieved"},
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
