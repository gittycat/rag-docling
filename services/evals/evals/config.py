"""Evaluation configuration management."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from evals.cache import CacheConfig

# Pricing lives in evals.pricing — one table, one set of matching rules, and
# "unpriced" as a real state instead of a silent $0. These names are re-exported
# because callers have always imported them from evals.config.
from evals.pricing import (  # noqa: F401
    EMBEDDING_COSTS,
    MODEL_COSTS,
    ModelRates,
    get_model_cost,
    resolve_rates,
)

if TYPE_CHECKING:
    from infrastructure.config.models_config import ContentPrivacy, DataPolicyConfig

logger = logging.getLogger(__name__)


class DatasetName(str, Enum):
    """Available evaluation datasets."""

    RAGBENCH = "ragbench"
    QASPER = "qasper"
    SQUAD_V2 = "squad_v2"
    HOTPOTQA = "hotpotqa"
    MSMARCO = "msmarco"
    GOLDEN = "golden"


class EvalTier(str, Enum):
    """Evaluation tier controlling how queries are executed."""

    GENERATION = "generation"   # Tier 1: inject context directly, no ingestion
    END_TO_END = "end_to_end"   # Tier 2: ingest docs, full pipeline


# Which tiers each dataset supports
DATASET_TIER_SUPPORT: dict[str, list[EvalTier]] = {
    DatasetName.RAGBENCH:  [EvalTier.GENERATION, EvalTier.END_TO_END],
    DatasetName.SQUAD_V2:  [EvalTier.GENERATION],
    DatasetName.GOLDEN:    [EvalTier.GENERATION],
    DatasetName.QASPER:    [EvalTier.END_TO_END],
    DatasetName.HOTPOTQA:  [EvalTier.END_TO_END],
    DatasetName.MSMARCO:   [EvalTier.END_TO_END],
}


def classify_eval_content(
    datasets: "Sequence[DatasetName] | None",
    tier: EvalTier | None,
    policy: "DataPolicyConfig",
) -> "ContentPrivacy":
    """Whether this run's content is public enough for an out-of-boundary judge.

    Fails closed: an unknown dataset or tier is not public. Every dataset must be
    public — a mixed run is as confidential as its most confidential member — and
    in the end_to_end tier a public dataset is still not enough, because there the
    runner queries the live index and the judge sees whatever it returns.

    Returns the condition that failed, not just a boolean, so the gate error names
    the one thing the operator has to change. Only the *first* failing condition is
    reported: fixing it re-runs this check, and reporting a downstream condition the
    operator cannot yet evaluate is noise.
    """
    from infrastructure.config.models_config import (
        IN_BOUNDARY_JUDGE_REMEDY,
        NON_CONFIDENTIAL_CORPUS_REMEDY,
        ContentPrivacy,
    )

    if not datasets or tier is None:
        # Not an operator mistake — a caller resolved a judge without saying what
        # the run evaluates, and the gate refuses to guess.
        return ContentPrivacy(
            is_public=False,
            reason=(
                "the run's datasets and tier were not passed to the judge gate, and an "
                "unidentified run fails closed"
            ),
            remedies=(
                "pass datasets= and tier= to evals.config.resolve_judge_config() "
                "(a code path, not a config setting)",
            ),
        )

    non_public = sorted({d.value for d in datasets if d.value not in policy.public_datasets})
    if non_public:
        return ContentPrivacy(
            is_public=False,
            reason=(
                f"dataset(s) {', '.join(non_public)} are not in "
                f"data_policy.public_datasets, so their questions and gold passages "
                f"may carry your own content"
            ),
            remedies=(
                IN_BOUNDARY_JUDGE_REMEDY,
                f"add {', '.join(non_public)} to data_policy.public_datasets, but only "
                f"if their questions and gold passages genuinely carry nothing of yours "
                f"(`golden` is authored from your documents, so it never qualifies)",
                NON_CONFIDENTIAL_CORPUS_REMEDY,
            ),
        )

    if tier is EvalTier.END_TO_END and not policy.eval_index_is_isolated:
        return ContentPrivacy(
            is_public=False,
            reason=(
                "the end_to_end tier queries the live rag-server index, which returns "
                "whatever is in it regardless of which dataset asked, and "
                "data_policy.eval_index_is_isolated is false — the dataset being public "
                "is not enough here"
            ),
            remedies=(
                IN_BOUNDARY_JUDGE_REMEDY,
                "set data_policy.eval_index_is_isolated: true, if the index this run "
                "queries really holds only the eval's own documents — or set "
                "EVAL_INDEX_IS_ISOLATED=true to assert it for a single run "
                "(`docker compose exec -e EVAL_INDEX_IS_ISOLATED=true evals ...`)",
                NON_CONFIDENTIAL_CORPUS_REMEDY,
            ),
        )

    return ContentPrivacy(is_public=True)


def eval_content_is_public(
    datasets: "Sequence[DatasetName] | None",
    tier: EvalTier | None,
    policy: "DataPolicyConfig",
) -> bool:
    """Boolean view of classify_eval_content, for callers that only record the verdict."""
    return classify_eval_content(datasets, tier, policy).is_public


# Dataset -> Primary evaluation aspect mapping
DATASET_ASPECTS = {
    DatasetName.RAGBENCH: ["generation", "retrieval"],  # Cross-domain baseline
    DatasetName.QASPER: ["citation", "generation"],  # Long-doc evidence grounding
    DatasetName.SQUAD_V2: ["abstention"],  # Unanswerable questions
    DatasetName.HOTPOTQA: ["retrieval", "generation"],  # Multi-hop reasoning
    DatasetName.MSMARCO: ["retrieval"],  # Retrieval ranking
    DatasetName.GOLDEN: ["generation", "retrieval"],  # Local curated Q&A pairs
}


# Fallback objective weights, used only when config.yml cannot be read. The
# operator-facing source of truth is `eval.scoring` in config.yml.
DEFAULT_WEIGHTS = {
    "accuracy": 0.30,  # Answer correctness
    "faithfulness": 0.20,  # Grounding in context
    "citation": 0.20,  # Citation precision/recall
    "groundedness": 0.0,  # Claim-level grounding — reported, not scored, by default
    "retrieval": 0.15,  # Retrieval quality
    "cost": 0.10,  # Cost per query
    "latency": 0.05,  # Response time
}

# A verdict of "correct" requires answer_correctness to clear this bar, and every
# consulted supporting generation metric to clear the one below it. Deliberately
# NOT 1.0: these are continuous 0-1 LLM-judge scores, and demanding an exact 1.0
# was the original defect. 0.5 is this repo's own calibrated convention for
# booleanizing a judge score (calibration.py:175, `judged >= 0.5`).
DEFAULT_CORRECTNESS_THRESHOLD = 0.5
DEFAULT_SUPPORTING_METRIC_THRESHOLD = 0.5

# Same role for the normalization thresholds latency and cost are scored against.
DEFAULT_LATENCY_THRESHOLD_MS = {
    "generation": 5_000.0,
    "end_to_end": 30_000.0,
}
DEFAULT_MAX_COST_PER_QUERY_USD = 0.10


@dataclass
class ScoringConfig:
    """Weights and normalization thresholds for the weighted score."""

    weights: dict[str, float] = field(default_factory=lambda: DEFAULT_WEIGHTS.copy())
    latency_threshold_ms_generation: float = DEFAULT_LATENCY_THRESHOLD_MS["generation"]
    latency_threshold_ms_end_to_end: float = DEFAULT_LATENCY_THRESHOLD_MS["end_to_end"]
    max_cost_per_query_usd: float = DEFAULT_MAX_COST_PER_QUERY_USD

    def latency_threshold_ms(self, tier: "EvalTier") -> float:
        if tier == EvalTier.END_TO_END:
            return self.latency_threshold_ms_end_to_end
        return self.latency_threshold_ms_generation

    @classmethod
    def from_models_config(cls) -> "ScoringConfig":
        """Read `eval.scoring` from config.yml, falling back to the constants above."""
        try:
            from infrastructure.config.models_config import get_models_config

            scoring = get_models_config().eval.scoring
        except Exception as e:  # config unavailable in unit tests / bare CLI use
            logger.debug(f"[EVAL] Using default scoring config: {e}")
            return cls()

        return cls(
            weights=dict(scoring.weights),
            latency_threshold_ms_generation=scoring.latency_threshold_ms_generation,
            latency_threshold_ms_end_to_end=scoring.latency_threshold_ms_end_to_end,
            max_cost_per_query_usd=scoring.max_cost_per_query_usd,
        )


@dataclass
class MetricConfig:
    """Configuration for which metrics to compute."""

    retrieval: bool = True
    generation: bool = True
    citation: bool = True
    abstention: bool = True
    performance: bool = True
    # Claim-level grounding is surfaced by default. Its 0.0 scoring weight keeps
    # historic headline scores comparable while still exposing hallucinations.
    # It is the only metric group whose cost scales with
    # the *shape* of the answer rather than the number of questions: one judge
    # call per claim, plus one per claim-citation link, against three per question
    # for the whole generation group. The work is enabled by default so
    # hallucination data is visible; see metrics/groundedness.py.
    groundedness: bool = True

    # Retrieval metric parameters
    recall_k_values: list[int] = field(default_factory=lambda: [1, 3, 5, 10])
    precision_k_values: list[int] = field(default_factory=lambda: [1, 3, 5])

    # Groundedness cost brakes. Both truncate rather than sample, and truncation
    # is reported per question so a capped answer is visibly capped.
    max_claims_per_answer: int = 5
    max_citations_per_claim: int = 2


@dataclass
class JudgeConfig:
    """The fully resolved identity of the judge a run will actually call.

    provider and model have no defaults on purpose. They used to default to
    Anthropic, and because every entry point constructed JudgeConfig(enabled=...)
    the defaults always won — `active.eval` in config.yml was dead configuration
    and every run called Anthropic regardless of what it said. Build this with
    resolve_judge_config(), never by hand outside tests.

    execution_boundary carries the ExecutionBoundary *value* (a plain string such
    as "third_party") rather than the enum, so this dataclass stays free of any
    dependency on the infrastructure package and serializes into run metadata
    unchanged.
    """

    provider: str
    model: str
    enabled: bool = True
    base_url: str | None = None
    temperature: float = 0.0
    timeout: float = 120.0
    max_retries: int = 3
    execution_boundary: str | None = None


def resolve_judge_config(
    enabled: bool = True,
    datasets: Sequence[DatasetName] | None = None,
    tier: EvalTier | None = None,
) -> JudgeConfig:
    """Resolve the judge from `active.eval` in config.yml.

    The single source of judge identity. Raises rather than falling back: a judge
    that cannot be resolved must stop the run, not quietly become someone else's
    API. Re-validates the resolved object against the data policy so the thing
    the runtime calls is the thing that was checked.

    `datasets` and `tier` decide whether this run's content is public; omitting
    them fails closed, which is why every caller that knows them passes them.
    """
    from infrastructure.config.models_config import (
        enforce_judge_boundary,
        get_models_config,
    )

    models_config = get_models_config()
    eval_config = models_config.eval

    enforce_judge_boundary(
        eval_config.execution_boundary,
        models_config.data_policy,
        f"{eval_config.provider}/{eval_config.model}",
        content_privacy=classify_eval_content(
            datasets, tier, models_config.data_policy
        ),
    )

    return JudgeConfig(
        provider=eval_config.provider,
        model=eval_config.model,
        enabled=enabled,
        base_url=eval_config.base_url,
        temperature=0.0,
        timeout=float(eval_config.timeout),
        max_retries=3,
        execution_boundary=(
            eval_config.execution_boundary.value
            if eval_config.execution_boundary is not None
            else None
        ),
    )


@dataclass
class EvalConfig:
    """Complete evaluation configuration.

    Attributes:
        datasets: Which datasets to use
        samples_per_dataset: Number of samples per dataset (None = all)
        metrics: Which metric groups to compute
        judge: LLM-as-judge configuration
        scoring: Objective weights and normalization thresholds
        rag_server_url: URL of the RAG server to evaluate
        runs_dir: Directory to store evaluation runs
        seed: Random seed for reproducibility
    """

    datasets: list[DatasetName] = field(
        default_factory=lambda: [DatasetName.RAGBENCH]
    )
    samples_per_dataset: int | None = 100
    metrics: MetricConfig = field(default_factory=MetricConfig)
    # Resolved in __post_init__, once datasets and tier are normalized — the gate
    # needs both, and a default_factory runs before either exists.
    judge: JudgeConfig | None = None
    scoring: ScoringConfig = field(default_factory=ScoringConfig.from_models_config)
    rag_server_url: str = "http://localhost:8001"
    runs_dir: Path = field(default_factory=lambda: Path("data/eval_runs"))
    seed: int | None = 42
    tier: EvalTier = field(default_factory=lambda: EvalTier.END_TO_END)
    cache: CacheConfig = field(default_factory=CacheConfig)
    cleanup_on_failure: bool = True
    query_concurrency: int = 10
    judge_concurrency: int = 10
    # Uses POST /search and records a selected retrieval stage as the response.
    # This is an evaluation mode only; it never changes server retrieval settings.
    retrieval_only: bool = False
    retrieval_source: str = "rerank"
    search_top_k: int = 10
    # Failure-attribution verdict thresholds. Continuous 0-1 judge scores are
    # booleanized at 0.5, matching calibration.py's `judged >= 0.5` convention;
    # an exact-1.0 bar made "correct" nearly unreachable and fired
    # generation_drift on almost every question. Raise for a stricter study.
    correctness_threshold: float = DEFAULT_CORRECTNESS_THRESHOLD
    supporting_metric_threshold: float = DEFAULT_SUPPORTING_METRIC_THRESHOLD

    @property
    def weights(self) -> dict[str, float]:
        return self.scoring.weights

    def __post_init__(self):
        if isinstance(self.runs_dir, str):
            self.runs_dir = Path(self.runs_dir)
        if isinstance(self.scoring, dict):
            self.scoring = ScoringConfig(**self.scoring)
        if isinstance(self.cache, dict):
            self.cache = CacheConfig(**self.cache)
        # Normalize dataset names
        normalized = []
        for ds in self.datasets:
            if isinstance(ds, str):
                normalized.append(DatasetName(ds))
            else:
                normalized.append(ds)
        self.datasets = normalized
        # Normalize tier
        if isinstance(self.tier, str):
            self.tier = EvalTier(self.tier)
        if self.retrieval_only and self.tier != EvalTier.END_TO_END:
            raise ValueError("retrieval_only requires the end_to_end tier")
        if self.retrieval_source not in {"bm25", "vector", "fusion", "rerank"}:
            raise ValueError("retrieval_source must be bm25, vector, fusion, or rerank")
        if self.search_top_k < 1:
            raise ValueError("search_top_k must be at least 1")
        # Validate tier/dataset combinations
        for ds in self.datasets:
            supported = DATASET_TIER_SUPPORT.get(ds, list(EvalTier))
            if self.tier not in supported:
                supported_names = [t.value for t in supported]
                raise ValueError(
                    f"Dataset '{ds.value}' does not support tier '{self.tier.value}'. "
                    f"Supported tiers: {supported_names}"
                )
        # Resolve the judge last: the boundary gate needs the normalized datasets
        # and tier, so the default path is dataset-aware rather than fail-closed
        # by accident.
        if self.judge is None:
            self.judge = resolve_judge_config(datasets=self.datasets, tier=self.tier)

    @property
    def judge_gate_basis(self) -> dict[str, Any]:
        """What the judge gate concluded for this run, for the run record."""
        from infrastructure.config.models_config import get_models_config

        return {
            "datasets": [d.value for d in self.datasets],
            "tier": self.tier.value,
            "eval_content_is_public": eval_content_is_public(
                self.datasets, self.tier, get_models_config().data_policy
            ),
        }

    @classmethod
    def from_yaml(cls, path: Path | str) -> "EvalConfig":
        """Load configuration from a YAML file."""
        path = Path(path)
        with open(path) as f:
            data = yaml.safe_load(f)

        # Handle nested configs
        if "metrics" in data and isinstance(data["metrics"], dict):
            data["metrics"] = MetricConfig(**data["metrics"])
        if "judge" in data and isinstance(data["judge"], dict):
            data["judge"] = JudgeConfig(**data["judge"])
        if "scoring" in data and isinstance(data["scoring"], dict):
            data["scoring"] = ScoringConfig(**data["scoring"])
        # Legacy top-level `weights:` key folds into scoring
        if "weights" in data:
            weights = data.pop("weights")
            scoring = data.get("scoring") or ScoringConfig.from_models_config()
            scoring.weights = weights
            data["scoring"] = scoring

        # Normalize tier from string
        if "tier" in data and isinstance(data["tier"], str):
            data["tier"] = EvalTier(data["tier"])

        return cls(**data)

    def to_yaml(self, path: Path | str) -> None:
        """Save configuration to a YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "datasets": [ds.value for ds in self.datasets],
            "samples_per_dataset": self.samples_per_dataset,
            "metrics": {
                "retrieval": self.metrics.retrieval,
                "generation": self.metrics.generation,
                "citation": self.metrics.citation,
                "abstention": self.metrics.abstention,
                "performance": self.metrics.performance,
                "groundedness": self.metrics.groundedness,
                "recall_k_values": self.metrics.recall_k_values,
                "precision_k_values": self.metrics.precision_k_values,
                "max_claims_per_answer": self.metrics.max_claims_per_answer,
                "max_citations_per_claim": self.metrics.max_citations_per_claim,
            },
            "judge": {
                "enabled": self.judge.enabled,
                "provider": self.judge.provider,
                "model": self.judge.model,
                "base_url": self.judge.base_url,
                "temperature": self.judge.temperature,
                "timeout": self.judge.timeout,
                "max_retries": self.judge.max_retries,
                "execution_boundary": self.judge.execution_boundary,
            },
            "scoring": {
                "weights": self.scoring.weights,
                "latency_threshold_ms_generation": self.scoring.latency_threshold_ms_generation,
                "latency_threshold_ms_end_to_end": self.scoring.latency_threshold_ms_end_to_end,
                "max_cost_per_query_usd": self.scoring.max_cost_per_query_usd,
            },
            "rag_server_url": self.rag_server_url,
            "runs_dir": str(self.runs_dir),
            "seed": self.seed,
            "tier": self.tier.value,
            "cache": {
                "judge": self.cache.judge,
                "query": self.cache.query,
                "dir": str(self.cache.dir),
            },
            "cleanup_on_failure": self.cleanup_on_failure,
            "query_concurrency": self.query_concurrency,
            "judge_concurrency": self.judge_concurrency,
            "retrieval_only": self.retrieval_only,
            "retrieval_source": self.retrieval_source,
            "search_top_k": self.search_top_k,
            "correctness_threshold": self.correctness_threshold,
            "supporting_metric_threshold": self.supporting_metric_threshold,
        }

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get_datasets_for_aspect(self, aspect: str) -> list[DatasetName]:
        """Get datasets that are relevant for a specific evaluation aspect."""
        return [
            ds
            for ds in self.datasets
            if aspect in DATASET_ASPECTS.get(ds, [])
        ]
