"""Performance metrics for latency and cost tracking."""

import statistics
from typing import Any

from evals.metrics.base import BaseMetric
from evals.pricing import (
    ModelRates,
    UsageTotals,
    get_embedding_cost,
    resolve_embedding_rate,
    resolve_rates,
)
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

    @property
    def requires_judge(self) -> bool:
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

    @property
    def requires_judge(self) -> bool:
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
        ingestion_cost_usd: float | None = 0.0,
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
        self._ingestion_cost_usd = ingestion_cost_usd

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
        if self._ingestion_cost_usd is None:
            unpriced.append("ingestion")

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
            total_cost = (
                (generation_cost or 0.0)
                + (judge_cost or 0.0)
                + (self._ingestion_cost_usd or 0.0)
            )
            avg_cost = total_cost / query_count

        details: dict[str, Any] = {
            "avg_cost_usd": avg_cost,
            "total_cost_usd": total_cost,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "generation_cost_usd": generation_cost,
            "ingestion_cost_usd": self._ingestion_cost_usd,
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


class IngestionCostPerDocument(BaseMetric):
    """Average ingestion cost per document, split into contextual and embedding work."""

    def __init__(
        self,
        stages: list[Any],
        llm_model: str | None,
        embedding_model: str | None,
        llm_input_rate: float | None = None,
        llm_output_rate: float | None = None,
    ):
        self._stages = stages
        self._llm_model = llm_model
        self._embedding_model = embedding_model
        self._llm_rates = resolve_rates(llm_model, llm_input_rate, llm_output_rate)
        self._embedding_rate = resolve_embedding_rate(embedding_model)

    @property
    def name(self) -> str:
        return "ingestion_cost_per_document"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.PERFORMANCE

    @property
    def description(self) -> str:
        return "Average document-ingestion cost in USD (contextual enrichment + embedding)"

    @property
    def requires_gold(self) -> bool:
        return False

    @property
    def requires_judge(self) -> bool:
        return False

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        raise NotImplementedError("Ingestion metrics are computed from document-stage records")

    async def compute_batch(
        self, questions: list[EvalQuestion], responses: list[EvalResponse], **kwargs: Any
    ) -> MetricResult:
        by_document: dict[str, list[Any]] = {}
        for stage in self._stages:
            by_document.setdefault(stage.document_id, []).append(stage)

        if not by_document:
            return MetricResult(
                name=self.name, value=None, group=self.group, sample_size=0,
                details={"note": "No persisted ingestion-stage records available"},
            )

        per_document: dict[str, float] = {}
        stage_totals = {"contextual_enrich": 0.0, "embed": 0.0}
        unpriced: list[str] = []
        for document_id, stages in by_document.items():
            total = 0.0
            unknown = False
            for stage in stages:
                if stage.name == "contextual_enrich" and stage.status != "skipped":
                    if stage.input_tokens is None or stage.output_tokens is None or self._llm_rates is None:
                        unknown = True
                        unpriced.append(f"{document_id}:contextual_enrich")
                        continue
                    cost = self._llm_rates.cost(stage.input_tokens, stage.output_tokens)
                    total += cost
                    stage_totals[stage.name] += cost
                elif stage.name == "embed" and stage.item_count:
                    if stage.input_tokens is None or self._embedding_rate is None:
                        unknown = True
                        unpriced.append(f"{document_id}:embed")
                        continue
                    cost = get_embedding_cost(self._embedding_model or "", stage.input_tokens)
                    if cost is None:
                        unknown = True
                        unpriced.append(f"{document_id}:embed")
                        continue
                    total += cost
                    stage_totals[stage.name] += cost
            if not unknown:
                per_document[document_id] = total

        if len(per_document) != len(by_document):
            return MetricResult(
                name=self.name, value=None, group=self.group, sample_size=len(per_document),
                details={
                    "note": "At least one cost-bearing ingestion stage is unpriced or lacks token usage.",
                    "unpriced_stages": unpriced,
                    "per_document": per_document,
                },
            )

        total = sum(per_document.values())
        count = len(per_document)
        return MetricResult(
            name=self.name,
            value=total / count,
            group=self.group,
            sample_size=count,
            details={
                "total_cost_usd": total,
                "per_document": per_document,
                "by_stage_usd": stage_totals,
                "contextual_rate_source": self._llm_rates.source if self._llm_rates else "unpriced",
                "embedding_rate_source": self._embedding_rate[1] if self._embedding_rate else "unpriced",
            },
        )


class IngestionLatencyPerDocument(BaseMetric):
    """Average wall-clock stage time per document, with a stage breakdown."""

    def __init__(self, stages: list[Any]):
        self._stages = stages

    @property
    def name(self) -> str:
        return "ingestion_latency_per_document_ms"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.PERFORMANCE

    @property
    def description(self) -> str:
        return "Average document-ingestion latency in milliseconds"

    @property
    def requires_gold(self) -> bool:
        return False

    @property
    def requires_judge(self) -> bool:
        return False

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        raise NotImplementedError("Ingestion metrics are computed from document-stage records")

    async def compute_batch(
        self, questions: list[EvalQuestion], responses: list[EvalResponse], **kwargs: Any
    ) -> MetricResult:
        by_document: dict[str, list[Any]] = {}
        for stage in self._stages:
            by_document.setdefault(stage.document_id, []).append(stage)
        if not by_document:
            return MetricResult(
                name=self.name, value=None, group=self.group, sample_size=0,
                details={"note": "No persisted ingestion-stage records available"},
            )

        per_document = {
            document_id: sum(stage.duration_ms for stage in stages)
            for document_id, stages in by_document.items()
        }
        by_stage: dict[str, float] = {}
        for stages in by_document.values():
            for stage in stages:
                by_stage[stage.name] = by_stage.get(stage.name, 0.0) + stage.duration_ms
        count = len(per_document)
        enrichment_rates = [
            stage.enrichment_success_rate
            for stage in self._stages
            if stage.name == "contextual_enrich" and stage.enrichment_success_rate is not None
        ]
        return MetricResult(
            name=self.name,
            value=sum(per_document.values()) / count,
            group=self.group,
            sample_size=count,
            details={
                "per_document": per_document,
                "by_stage_ms": by_stage,
                "enrichment_success_rate": (
                    sum(enrichment_rates) / len(enrichment_rates) if enrichment_rates else None
                ),
            },
        )
