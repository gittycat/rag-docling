"""Evaluation configuration management."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from evals.cache import CacheConfig

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
    "retrieval": 0.15,  # Retrieval quality
    "cost": 0.10,  # Cost per query
    "latency": 0.05,  # Response time
}

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


# Cost lookup table (USD per 1M tokens)
# Lookup is exact-match on the full model id (then "provider/*" wildcards), and
# an unmatched model silently costs $0 — every model reachable from config.yml
# must have an entry here or the cost objective scores it as free.
MODEL_COSTS = {
    # Anthropic
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    # Retired 2026-06-15 (returns 404) but still referenced by config.yml's
    # eval tier — priced so a run against it is not scored as free.
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.00},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
    "gpt-5.6-sol": {"input": 5.00, "output": 30.00},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # Google, DeepSeek, and Moonshot providers are not currently supported
    # (no Docker secret declared) — see rag_server/infrastructure/llm/config.py.
    # Local/Ollama - free
    "ollama/*": {"input": 0.0, "output": 0.0},
}

EMBEDDING_COSTS = {
    # Per 1M tokens
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "nomic-embed-text": 0.0,  # Ollama - free
    "ollama/*": 0.0,
}


@dataclass
class MetricConfig:
    """Configuration for which metrics to compute."""

    retrieval: bool = True
    generation: bool = True
    citation: bool = True
    abstention: bool = True
    performance: bool = True

    # Retrieval metric parameters
    recall_k_values: list[int] = field(default_factory=lambda: [1, 3, 5, 10])
    precision_k_values: list[int] = field(default_factory=lambda: [1, 3, 5])


@dataclass
class JudgeConfig:
    """Configuration for LLM-as-judge evaluation."""

    enabled: bool = True
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    temperature: float = 0.0
    max_retries: int = 3


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
    judge: JudgeConfig = field(default_factory=JudgeConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig.from_models_config)
    rag_server_url: str = "http://localhost:8001"
    runs_dir: Path = field(default_factory=lambda: Path("data/eval_runs"))
    seed: int | None = 42
    tier: EvalTier = field(default_factory=lambda: EvalTier.END_TO_END)
    cache: CacheConfig = field(default_factory=CacheConfig)
    cleanup_on_failure: bool = True
    query_concurrency: int = 10
    judge_concurrency: int = 10

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
        # Validate tier/dataset combinations
        for ds in self.datasets:
            supported = DATASET_TIER_SUPPORT.get(ds, list(EvalTier))
            if self.tier not in supported:
                supported_names = [t.value for t in supported]
                raise ValueError(
                    f"Dataset '{ds.value}' does not support tier '{self.tier.value}'. "
                    f"Supported tiers: {supported_names}"
                )

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
                "recall_k_values": self.metrics.recall_k_values,
                "precision_k_values": self.metrics.precision_k_values,
            },
            "judge": {
                "enabled": self.judge.enabled,
                "provider": self.judge.provider,
                "model": self.judge.model,
                "temperature": self.judge.temperature,
                "max_retries": self.judge.max_retries,
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


def get_model_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Calculate cost for a query based on model and token counts.

    Args:
        model: Model identifier
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens

    Returns:
        Cost in USD
    """
    # Check for exact match first
    costs = MODEL_COSTS.get(model)

    # Check for provider wildcard (e.g., "ollama/*")
    if costs is None:
        for pattern, pattern_costs in MODEL_COSTS.items():
            if pattern.endswith("/*"):
                provider = pattern[:-2]
                if model.startswith(provider) or provider in model.lower():
                    costs = pattern_costs
                    break

    # Default to free if unknown
    if costs is None:
        costs = {"input": 0.0, "output": 0.0}

    return (
        prompt_tokens * costs["input"] + completion_tokens * costs["output"]
    ) / 1_000_000
