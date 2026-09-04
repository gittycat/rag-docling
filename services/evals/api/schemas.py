"""Pydantic request/response models for the eval API."""

from datetime import datetime

from pydantic import BaseModel, Field


# ── Requests ──────────────────────────────────────────────────────────────────


class TriggerRunRequest(BaseModel):
    name: str | None = None
    tier: str = "generation"
    datasets: list[str] = Field(default_factory=lambda: ["ragbench"])
    samples: int = 100
    seed: int | None = 42
    judge_enabled: bool = True
    # Claim-level grounding and claim-to-citation entailment run by default.
    groundedness: bool = True


# ── Responses ─────────────────────────────────────────────────────────────────


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str = "queued"
    # 0 = started immediately; N = N jobs ahead of it in the queue
    queue_position: int = 0
    created_at: datetime


class ProgressInfo(BaseModel):
    current_question: int = 0
    total_questions: int = 0
    current_dataset: str = ""
    phase: str = "initializing"
    elapsed_seconds: float = 0.0


class ActiveJobResponse(BaseModel):
    job_id: str
    status: str
    progress: ProgressInfo


class QueuedJob(BaseModel):
    job_id: str
    position: int
    created_at: datetime
    name: str = ""
    tier: str = ""
    datasets: list[str] = Field(default_factory=list)


class DashboardMetrics(BaseModel):
    faithfulness: float | None = None
    claim_groundedness: float | None = None
    answer_correctness: float | None = None
    # Distinct from answer correctness: an answer can be right as far as it goes
    # while omitting required facts.
    answer_completeness: float | None = None
    answer_relevance: float | None = None
    # Retrieval is reported as the funnel's two real numbers rather than a
    # composite. `retrieval_ceiling` is the recall of the candidate list handed
    # to the reranker; `retrieval_final` is what the model actually saw. Their
    # gap is the reranker's cost, and 1 - ceiling is what ingestion never found.
    retrieval_ceiling: float | None = None
    retrieval_final: float | None = None
    retrieval_bottleneck: str | None = None
    latency_p50_seconds: float | None = None
    latency_p95_seconds: float | None = None
    latency_avg_seconds: float | None = None
    avg_cost_usd: float | None = None
    total_cost_usd: float | None = None
    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    cost_model: str | None = None


class FunnelStageOut(BaseModel):
    name: str
    recall: float | None = None
    secondary: dict[str, float] = Field(default_factory=dict)
    questions_scored: int = 0
    delta: float | None = None


class RetrievalFunnelOut(BaseModel):
    """Stage-by-stage retrieval recall, and which half of the system to fix."""

    stages: list[FunnelStageOut] = Field(default_factory=list)
    ceiling: float | None = None
    final: float | None = None
    lost_before_candidates: float | None = None
    lost_in_rerank: float | None = None
    bottleneck: str | None = None
    diagnosis: str | None = None
    leg_recall: dict[str, float] = Field(default_factory=dict)
    fusion_lift: float | None = None
    note: str | None = None


class RunSummary(BaseModel):
    id: str
    name: str
    created_at: datetime
    completed_at: datetime | None = None
    tier: str = ""
    datasets: list[str] = Field(default_factory=list)
    question_count: int = 0
    error_count: int = 0
    duration_seconds: float | None = None
    weighted_score: float | None = None
    llm_model: str | None = None
    dashboard_metrics: DashboardMetrics | None = None
    retrieval_funnel: RetrievalFunnelOut | None = None
    # None = the metric was undefined for this run's data (e.g. citation metrics
    # with no gold passages). Distinct from the key being absent.
    metrics: dict[str, float | None] = Field(default_factory=dict)
    groups: dict[str, list[str]] = Field(default_factory=dict)


class RunListResponse(BaseModel):
    runs: list[RunSummary]
    total: int


class RunDetailResponse(BaseModel):
    """Full run detail — includes raw scorecard data."""

    id: str
    name: str
    created_at: datetime
    completed_at: datetime | None = None
    tier: str = ""
    datasets: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    scorecard: dict | None = None
    weighted_score: dict | None = None
    question_count: int = 0
    error_count: int = 0
    duration_seconds: float | None = None
    metadata: dict = Field(default_factory=dict)
    dashboard_metrics: DashboardMetrics | None = None
    retrieval_funnel: RetrievalFunnelOut | None = None


class MetricSignificance(BaseModel):
    """Paired significance result for one metric between two runs."""

    metric: str
    n_paired: int
    mean_a: float
    mean_b: float
    delta: float
    ci_low: float
    ci_high: float
    p_value: float
    test: str
    significant: bool
    significant_corrected: bool | None = None
    underpowered: bool = False
    discordant_b_better: int | None = None
    discordant_a_better: int | None = None


class SignificanceReport(BaseModel):
    """Significance of run B against run A, plus the family-level context.

    Without this a caller sees only arithmetic deltas and cannot tell a real
    improvement from noise — a difference across 10 questions and one across 1000
    otherwise render identically.
    """

    run_a: str
    run_b: str
    alpha: float
    family_size: int
    expected_false_positives: float
    any_spurious_probability: float
    underpowered_threshold: int
    metrics: list[MetricSignificance] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class CompareRunsResponse(BaseModel):
    runs: list[RunDetailResponse]
    deltas: dict[str, float | None] = Field(default_factory=dict)
    # One report per non-baseline run, each compared against runs[0]
    significance: list[SignificanceReport] = Field(default_factory=list)


class DatasetInfo(BaseModel):
    name: str
    description: str = ""
    source_url: str = ""
    supported_tiers: list[str] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    latest_run: RunSummary | None = None
    total_runs: int = 0
    active_job: ActiveJobResponse | None = None
