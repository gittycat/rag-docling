"""Comparison service for evaluation runs.

Provides side-by-side comparison of two evaluation runs,
calculating deltas for metrics, latency, and cost.
"""

import logging
from typing import Optional

from schemas.metrics import (
    ComparisonResult,
    ConfigSnapshot,
    EvaluationRun,
    LatencyMetrics,
    CostMetrics,
)

logger = logging.getLogger(__name__)


class ComparisonService:
    """Service for comparing evaluation runs.

    Provides detailed comparison between two runs including
    metric deltas, latency comparison, cost comparison,
    and winner determination.
    """

    # Metrics where lower is better
    LOWER_IS_BETTER = {"hallucination"}

    # Weights for winner determination (can be configured)
    DEFAULT_WEIGHTS = {
        "metrics": 0.6,
        "latency": 0.2,
        "cost": 0.2,
    }

    def compare_runs(
        self,
        run_a: EvaluationRun,
        run_b: EvaluationRun,
    ) -> ComparisonResult:
        """Compare two evaluation runs.

        Args:
            run_a: First evaluation run
            run_b: Second evaluation run

        Returns:
            ComparisonResult with detailed comparison
        """
        # Compare metrics
        metric_deltas = self._compare_metrics(
            run_a.metric_averages,
            run_b.metric_averages,
        )

        # Compare latency
        latency_delta, latency_pct = self._compare_latency(
            run_a.latency,
            run_b.latency,
        )

        # Compare cost
        cost_delta, cost_pct = self._compare_cost(
            run_a.cost,
            run_b.cost,
        )

        # Determine winner
        winner, reason = self._determine_winner(
            metric_deltas,
            latency_delta,
            cost_delta,
            run_a,
            run_b,
        )

        return ComparisonResult(
            run_a_id=run_a.run_id,
            run_b_id=run_b.run_id,
            run_a_config=run_a.config_snapshot,
            run_b_config=run_b.config_snapshot,
            metric_deltas=metric_deltas,
            latency_delta_ms=latency_delta,
            latency_improvement_pct=latency_pct,
            cost_delta_usd=cost_delta,
            cost_improvement_pct=cost_pct,
            winner=winner,
            winner_reason=reason,
        )

    def _compare_metrics(
        self,
        metrics_a: dict[str, float],
        metrics_b: dict[str, float],
    ) -> dict[str, float]:
        """Compare metrics between two runs.

        Args:
            metrics_a: Metrics from run A
            metrics_b: Metrics from run B

        Returns:
            Dict of metric deltas (positive = A is better)
        """
        deltas = {}

        all_metrics = set(metrics_a.keys()) | set(metrics_b.keys())

        for metric in all_metrics:
            val_a = metrics_a.get(metric)
            val_b = metrics_b.get(metric)

            if val_a is None or val_b is None:
                continue

            if metric in self.LOWER_IS_BETTER:
                # For hallucination, lower is better, so flip the delta
                delta = val_b - val_a  # Positive = A has lower (better) value
            else:
                delta = val_a - val_b  # Positive = A has higher (better) value

            deltas[metric] = round(delta, 4)

        return deltas

    def _compare_latency(
        self,
        latency_a: Optional[LatencyMetrics],
        latency_b: Optional[LatencyMetrics],
    ) -> tuple[Optional[float], Optional[float]]:
        """Compare latency between two runs.

        Args:
            latency_a: Latency metrics from run A
            latency_b: Latency metrics from run B

        Returns:
            Tuple of (delta_ms, improvement_pct)
            Positive delta = A is faster
        """
        if not latency_a or not latency_b:
            return None, None

        # Use P95 for comparison (more representative of worst case)
        delta = latency_b.p95_query_time_ms - latency_a.p95_query_time_ms

        # Calculate percentage improvement (positive = A is faster)
        if latency_b.p95_query_time_ms > 0:
            pct = (delta / latency_b.p95_query_time_ms) * 100
        else:
            pct = 0.0

        return round(delta, 2), round(pct, 1)

    def _compare_cost(
        self,
        cost_a: Optional[CostMetrics],
        cost_b: Optional[CostMetrics],
    ) -> tuple[Optional[float], Optional[float]]:
        """Compare cost between two runs.

        Args:
            cost_a: Cost metrics from run A
            cost_b: Cost metrics from run B

        Returns:
            Tuple of (delta_usd, improvement_pct)
            Positive delta = A is cheaper
        """
        if not cost_a or not cost_b:
            return None, None

        delta = cost_b.cost_per_query_usd - cost_a.cost_per_query_usd

        # Calculate percentage improvement (positive = A is cheaper)
        if cost_b.cost_per_query_usd > 0:
            pct = (delta / cost_b.cost_per_query_usd) * 100
        else:
            pct = 0.0

        return round(delta, 6), round(pct, 1)

    def _determine_winner(
        self,
        metric_deltas: dict[str, float],
        latency_delta: Optional[float],
        cost_delta: Optional[float],
        run_a: EvaluationRun,
        run_b: EvaluationRun,
    ) -> tuple[str, str]:
        """Determine the overall winner between two runs.

        Args:
            metric_deltas: Metric comparison results
            latency_delta: Latency comparison (positive = A faster)
            cost_delta: Cost comparison (positive = A cheaper)
            run_a: First run
            run_b: Second run

        Returns:
            Tuple of (winner, reason)
        """
        # Calculate aggregate metric score
        if metric_deltas:
            avg_delta = sum(metric_deltas.values()) / len(metric_deltas)
        else:
            avg_delta = 0.0

        # Build reasoning
        reasons = []

        # Check metrics
        a_better_metrics = sum(1 for d in metric_deltas.values() if d > 0.01)
        b_better_metrics = sum(1 for d in metric_deltas.values() if d < -0.01)

        if a_better_metrics > b_better_metrics:
            reasons.append(f"A better on {a_better_metrics} metrics")
        elif b_better_metrics > a_better_metrics:
            reasons.append(f"B better on {b_better_metrics} metrics")

        # Check latency
        if latency_delta is not None:
            if latency_delta > 50:  # A is >50ms faster
                reasons.append("A is faster")
            elif latency_delta < -50:  # B is >50ms faster
                reasons.append("B is faster")

        # Check cost
        if cost_delta is not None:
            if cost_delta > 0.001:  # A is cheaper by >$0.001
                reasons.append("A is cheaper")
            elif cost_delta < -0.001:  # B is cheaper
                reasons.append("B is cheaper")

        # Determine winner based on weighted score
        score_a = 0.0
        score_b = 0.0

        # Metrics score
        if avg_delta > 0.01:
            score_a += self.DEFAULT_WEIGHTS["metrics"]
        elif avg_delta < -0.01:
            score_b += self.DEFAULT_WEIGHTS["metrics"]

        # Latency score
        if latency_delta is not None:
            if latency_delta > 50:
                score_a += self.DEFAULT_WEIGHTS["latency"]
            elif latency_delta < -50:
                score_b += self.DEFAULT_WEIGHTS["latency"]

        # Cost score
        if cost_delta is not None:
            if cost_delta > 0.001:
                score_a += self.DEFAULT_WEIGHTS["cost"]
            elif cost_delta < -0.001:
                score_b += self.DEFAULT_WEIGHTS["cost"]

        # Determine winner
        if score_a > score_b + 0.1:
            winner = "run_a"
            model_name = run_a.config_snapshot.llm_model if run_a.config_snapshot else run_a.run_id
            reason = f"{model_name}: " + ", ".join(reasons) if reasons else "Higher overall score"
        elif score_b > score_a + 0.1:
            winner = "run_b"
            model_name = run_b.config_snapshot.llm_model if run_b.config_snapshot else run_b.run_id
            reason = f"{model_name}: " + ", ".join(reasons) if reasons else "Higher overall score"
        else:
            winner = "tie"
            reason = "Similar performance across metrics, latency, and cost"

        return winner, reason


# Singleton instance
_comparison_service: Optional[ComparisonService] = None


def get_comparison_service() -> ComparisonService:
    """Get the singleton ComparisonService instance."""
    global _comparison_service
    if _comparison_service is None:
        _comparison_service = ComparisonService()
    return _comparison_service
