"""Golden baseline management service.

Manages the golden baseline - a reference evaluation run that
new runs are compared against for pass/fail determination.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from schemas.metrics import (
    BaselineCheckResult,
    ConfigSnapshot,
    EvaluationRun,
    GoldenBaseline,
)

logger = logging.getLogger(__name__)

# Default baseline file location
BASELINE_FILE = Path("eval_data/golden_baseline.json")


class BaselineService:
    """Service for managing the golden baseline.

    The golden baseline is a reference evaluation run that defines
    the target metrics to beat. New runs are compared against this
    baseline to determine pass/fail status.
    """

    def __init__(self, baseline_path: Optional[Path] = None):
        """Initialize the baseline service.

        Args:
            baseline_path: Custom path to baseline file. Defaults to
                          eval_data/golden_baseline.json
        """
        self.baseline_path = baseline_path or BASELINE_FILE

    def get_baseline(self) -> Optional[GoldenBaseline]:
        """Load the current golden baseline.

        Returns:
            GoldenBaseline if set, None otherwise
        """
        if not self.baseline_path.exists():
            return None

        try:
            with open(self.baseline_path) as f:
                data = json.load(f)
            return GoldenBaseline(**data)
        except Exception as e:
            logger.error(f"Failed to load baseline: {e}")
            return None

    def set_baseline(
        self,
        run: EvaluationRun,
        set_by: Optional[str] = None,
    ) -> GoldenBaseline:
        """Set an evaluation run as the golden baseline.

        Args:
            run: The evaluation run to set as baseline
            set_by: Optional identifier for who set the baseline

        Returns:
            The created GoldenBaseline
        """
        # Create config snapshot from run
        if run.config_snapshot:
            config_snapshot = run.config_snapshot
        else:
            # Create from legacy retrieval_config if available
            config_snapshot = self._create_config_snapshot_from_legacy(
                run.retrieval_config
            )

        baseline = GoldenBaseline(
            run_id=run.run_id,
            set_at=datetime.utcnow(),
            set_by=set_by,
            target_metrics=run.metric_averages,
            config_snapshot=config_snapshot,
            target_latency_p95_ms=run.latency.p95_query_time_ms if run.latency else None,
            target_cost_per_query_usd=run.cost.cost_per_query_usd if run.cost else None,
        )

        # Ensure directory exists
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)

        # Save to file
        with open(self.baseline_path, "w") as f:
            json.dump(baseline.model_dump(mode="json"), f, indent=2, default=str)

        logger.info(f"Golden baseline set to run {run.run_id}")
        return baseline

    def clear_baseline(self) -> bool:
        """Clear the current golden baseline.

        Returns:
            True if baseline was cleared, False if none existed
        """
        if not self.baseline_path.exists():
            return False

        self.baseline_path.unlink()
        logger.info("Golden baseline cleared")
        return True

    def check_against_baseline(self, run: EvaluationRun) -> Optional[BaselineCheckResult]:
        """Check if a run passes the golden baseline.

        Args:
            run: The evaluation run to check

        Returns:
            BaselineCheckResult with pass/fail details, None if no baseline set
        """
        baseline = self.get_baseline()
        if baseline is None:
            return None

        metrics_pass = []
        metrics_fail = []
        metric_deltas = {}

        for metric_name, target_value in baseline.target_metrics.items():
            actual_value = run.metric_averages.get(metric_name)
            if actual_value is None:
                continue

            # For hallucination, lower is better
            if metric_name == "hallucination":
                passed = actual_value <= target_value
                delta = target_value - actual_value  # Positive = better
            else:
                passed = actual_value >= target_value
                delta = actual_value - target_value  # Positive = better

            if passed:
                metrics_pass.append(metric_name)
            else:
                metrics_fail.append(metric_name)

            metric_deltas[metric_name] = round(delta, 4)

        return BaselineCheckResult(
            baseline_run_id=baseline.run_id,
            checked_run_id=run.run_id,
            metrics_pass=metrics_pass,
            metrics_fail=metrics_fail,
            overall_pass=len(metrics_fail) == 0,
            metric_deltas=metric_deltas,
        )

    def _create_config_snapshot_from_legacy(
        self, retrieval_config: Optional[dict]
    ) -> ConfigSnapshot:
        """Create a ConfigSnapshot from legacy retrieval_config dict.

        Args:
            retrieval_config: Legacy config dict from older runs

        Returns:
            ConfigSnapshot with best-effort mapping
        """
        if not retrieval_config:
            # Return defaults
            return ConfigSnapshot(
                llm_provider="unknown",
                llm_model="unknown",
                embedding_provider="ollama",
                embedding_model="nomic-embed-text:latest",
                retrieval_top_k=10,
                hybrid_search_enabled=True,
                rrf_k=60,
                contextual_retrieval_enabled=False,
                reranker_enabled=True,
                reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
                reranker_top_n=5,
            )

        # Extract from legacy format
        hybrid = retrieval_config.get("hybrid_search", {})
        reranker = retrieval_config.get("reranker", {})
        contextual = retrieval_config.get("contextual_retrieval", {})

        return ConfigSnapshot(
            llm_provider="unknown",
            llm_model="unknown",
            embedding_provider="ollama",
            embedding_model="nomic-embed-text:latest",
            retrieval_top_k=retrieval_config.get("retrieval_top_k", 10),
            hybrid_search_enabled=hybrid.get("enabled", True),
            rrf_k=hybrid.get("rrf_k", 60),
            contextual_retrieval_enabled=contextual.get("enabled", False),
            reranker_enabled=reranker.get("enabled", True),
            reranker_model=reranker.get("model"),
            reranker_top_n=reranker.get("top_n", 5),
        )


# Singleton instance
_baseline_service: Optional[BaselineService] = None


def get_baseline_service() -> BaselineService:
    """Get the singleton BaselineService instance."""
    global _baseline_service
    if _baseline_service is None:
        _baseline_service = BaselineService()
    return _baseline_service
