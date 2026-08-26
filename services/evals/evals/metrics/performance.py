"""Performance metrics for latency and cost tracking."""

import statistics
from typing import Any

from evals.metrics.base import BaseMetric
from evals.pricing import ModelRates, UsageTotals, resolve_rates
from evals.schemas import (
    EvalQuestion,
    EvalResponse,
    MetricResult,
    MetricGroup,
)


class LatencyP50(BaseMetric):
    """P50 (median) latency in milliseconds.

    Lower is better.
    """

    @property
    def name(self) -> str:
        return "latency_p50"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.PERFORMANCE

    @property
    def description(self) -> str:
        return "Median query latency in milliseconds"

    @property
    def requires_gold(self) -> bool:
        return False

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        if response.metrics and response.metrics.latency_ms:
            latency = response.metrics.latency_ms
        else:
            latency = 0.0

        return MetricResult(
            name=self.name,
            value=latency,
            group=self.group,
            sample_size=1,
            details={"latency_ms": latency},
        )

    async def compute_batch(
        self,
        questions: list[EvalQuestion],
        responses: list[EvalResponse],
        progress_callback: Any | None = None,
        concurrency: int = 10,
        **kwargs: Any,
    ) -> MetricResult:
        """Compute P50 latency across batch."""
        latencies = []
        for r in responses:
            if r.metrics and r.metrics.latency_ms:
                latencies.append(r.metrics.latency_ms)

        if not latencies:
            return MetricResult(
                name=self.name,
                value=0.0,
                group=self.group,
                sample_size=0,
                details={"note": "No latency data available"},
            )

        p50 = statistics.median(latencies)

        return MetricResult(
            name=self.name,
            value=p50,
            group=self.group,
            sample_size=len(latencies),
            details={
                "p50_ms": p50,
                "min_ms": min(latencies),
                "max_ms": max(latencies),
                "mean_ms": statistics.mean(latencies),
            },
        )


class LatencyP95(BaseMetric):
    """P95 latency in milliseconds.

    Lower is better. Captures tail latency.
    """

    @property
    def name(self) -> str:
        return "latency_p95"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.PERFORMANCE

    @property
    def description(self) -> str:
        return "95th percentile query latency in milliseconds"

    @property
    def requires_gold(self) -> bool:
        return False

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        # Single sample - return the latency value
        if response.metrics and response.metrics.latency_ms:
            latency = response.metrics.latency_ms
        else:
            latency = 0.0

        return MetricResult(
            name=self.name,
            value=latency,
            group=self.group,
            sample_size=1,
            details={"latency_ms": latency},
        )

    async def compute_batch(
        self,
        questions: list[EvalQuestion],
        responses: list[EvalResponse],
        progress_callback: Any | None = None,
        concurrency: int = 10,
        **kwargs: Any,
    ) -> MetricResult:
        """Compute P95 latency across batch."""
        latencies = []
        for r in responses:
            if r.metrics and r.metrics.latency_ms:
                latencies.append(r.metrics.latency_ms)

        if not latencies:
            return MetricResult(
                name=self.name,
                value=0.0,
                group=self.group,
                sample_size=0,
                details={"note": "No latency data available"},
            )

        # Calculate P95
        sorted_latencies = sorted(latencies)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p95 = sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)]

        return MetricResult(
            name=self.name,
            value=p95,
            group=self.group,
            sample_size=len(latencies),
            details={
                "p95_ms": p95,
                "p50_ms": statistics.median(latencies),
                "min_ms": min(latencies),
                "max_ms": max(latencies),
            },
        )


class CostPerQuery(BaseMetric):
    """Average cost per query in USD — answer generation plus judging.

    Lower is better.

    Two things this deliberately refuses to do. It will not price a model it has
    no rates for: the value is None ("unpriced") and the runner leaves the cost
    objective out of the weighted score, because an unpriced model is unmeasured,
    not free. And it will not report generation cost as if it were the run's
    cost: judging is three LLM calls per query and is where an eval run's token
    volume actually sits, so judge usage is added in — attributed separately in
    the details so the two remain distinguishable.
    """

    def __init__(
        self,
        model: str,
        cost_per_1m_input_tokens: float | None = None,
        cost_per_1m_output_tokens: float | None = None,
        judge_usage: UsageTotals | None = None,
        judge_model: str | None = None,
        judge_cost_per_1m_input_tokens: float | None = None,
        judge_cost_per_1m_output_tokens: float | None = None,
    ):
        """Initialize with the generation model and, optionally, judge usage.

        Explicit rates are injected rather than looked up — that is the hook an
        amortized self-hosted rate (instance price / measured throughput) arrives
        through, and it is why they default to None instead of 0.0.
        """
        self._model = model
        self._rates = resolve_rates(
            model, cost_per_1m_input_tokens, cost_per_1m_output_tokens
        )
        self._judge_usage = judge_usage
        self._judge_model = judge_model or (judge_usage.model if judge_usage else None)
        self._judge_rates = resolve_rates(
            self._judge_model,
            judge_cost_per_1m_input_tokens,
            judge_cost_per_1m_output_tokens,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def rates(self) -> ModelRates | None:
        return self._rates

    @property
    def name(self) -> str:
        return "cost_per_query"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.PERFORMANCE

    @property
    def description(self) -> str:
        return "Average cost per query in USD (generation + judging)"

    @property
    def requires_gold(self) -> bool:
        return False

    def _rate_details(self) -> dict[str, Any]:
        return {
            "model": self._model,
            "rate_source": self._rates.source if self._rates else "unpriced",
            "cost_per_1m_input_tokens": self._rates.input_per_1m if self._rates else None,
            "cost_per_1m_output_tokens": self._rates.output_per_1m if self._rates else None,
        }

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        """Per-question generation cost. Judge usage is a batch-level quantity."""
        usage = response.metrics.token_usage if response.metrics else None
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        cost = (
            self._rates.cost(prompt_tokens, completion_tokens)
            if self._rates is not None
            else None
        )

        details: dict[str, Any] = {
            "cost_usd": cost,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            **self._rate_details(),
        }
        if cost is None:
            details["note"] = (
                f"Model '{self._model}' is unpriced — no rates in the pricing table, "
                "MODEL_PRICE_OVERRIDES or /models/info. Excluded from cost scoring."
            )

        return MetricResult(
            name=self.name,
            value=cost,
            group=self.group,
            sample_size=1,
            details=details,
        )

    async def compute_batch(
        self,
        questions: list[EvalQuestion],
        responses: list[EvalResponse],
        progress_callback: Any | None = None,
        concurrency: int = 10,
        **kwargs: Any,
    ) -> MetricResult:
        """Average cost per query across the batch, judging included."""
        total_prompt_tokens = 0
        total_completion_tokens = 0
        per_question: dict[str, float] = {}
        counted = 0

        for q, r in zip(questions, responses):
            usage = r.metrics.token_usage if r.metrics else None
            if not usage:
                continue
            counted += 1
            total_prompt_tokens += usage.prompt_tokens
            total_completion_tokens += usage.completion_tokens
            if self._rates is not None:
                per_question[q.id] = self._rates.cost(
                    usage.prompt_tokens, usage.completion_tokens
                )

        judge = self._judge_usage
        judge_has_usage = judge is not None and judge.has_usage

        if counted == 0 and not judge_has_usage:
            return MetricResult(
                name=self.name,
                value=None,
                group=self.group,
                sample_size=0,
                details={
                    "note": (
                        "No token usage data available — cost is unknown, not zero."
                    ),
                    **self._rate_details(),
                },
            )

        # An unpriced component makes the total unknowable, so the whole metric
        # goes unpriced rather than silently under-reporting the workload.
        unpriced = []
        if counted > 0 and self._rates is None:
            unpriced.append("generation")
        if judge_has_usage and self._judge_rates is None:
            unpriced.append("judge")

        generation_cost = (
            self._rates.cost(total_prompt_tokens, total_completion_tokens)
            if self._rates is not None
            else None
        )
        if not judge_has_usage:
            judge_cost = 0.0
        elif self._judge_rates is not None:
            judge_cost = self._judge_rates.cost(
                judge.prompt_tokens, judge.completion_tokens
            )
        else:
            judge_cost = None

        # Queries are the denominator for both components: judging is a per-query
        # cost of running this eval, it is just billed in a different place.
        query_count = counted or len(questions) or 1

        if unpriced:
            total_cost = None
            avg_cost = None
        else:
            total_cost = (generation_cost or 0.0) + (judge_cost or 0.0)
            avg_cost = total_cost / query_count

        details: dict[str, Any] = {
            "avg_cost_usd": avg_cost,
            "total_cost_usd": total_cost,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "generation_cost_usd": generation_cost,
            "per_question": per_question,
            "query_count": query_count,
            **self._rate_details(),
        }

        if judge is not None:
            details["judge"] = {
                **judge.as_dict(),
                "model": self._judge_model,
                "cost_usd": judge_cost,
                "rate_source": (
                    self._judge_rates.source if self._judge_rates else "unpriced"
                ),
            }

        if unpriced:
            details["unpriced_components"] = unpriced
            details["note"] = (
                f"Unpriced: {', '.join(unpriced)}. Cost is unmeasured, not zero, "
                "so this run is excluded from the cost objective. Supply rates via "
                "MODEL_PRICE_OVERRIDES or /models/info."
            )

        return MetricResult(
            name=self.name,
            value=avg_cost,
            group=self.group,
            sample_size=counted,
            details=details,
        )
