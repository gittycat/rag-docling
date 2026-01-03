"""Recommendation service for optimal configuration selection.

Analyzes historical evaluation runs and recommends the best
configuration based on user-specified weights for accuracy,
speed, and cost.
"""

import logging
from pathlib import Path
from typing import Optional

from schemas.metrics import (
    ConfigSnapshot,
    EvaluationRun,
    Recommendation,
)
from services.metrics import load_evaluation_history

logger = logging.getLogger(__name__)


class RecommendationService:
    """Service for generating configuration recommendations.

    Analyzes historical evaluation runs and recommends the optimal
    configuration based on user preferences for accuracy, speed,
    and cost tradeoffs.
    """

    # Metrics where lower is better
    LOWER_IS_BETTER = {"hallucination"}

    # Key metrics for accuracy calculation
    ACCURACY_METRICS = [
        "faithfulness",
        "answer_relevancy",
        "precision_at_k",
        "recall_at_k",
        "mrr",
        "ndcg",
        "citation_precision",
        "citation_recall",
    ]

    def get_recommendation(
        self,
        accuracy_weight: float = 0.5,
        speed_weight: float = 0.3,
        cost_weight: float = 0.2,
        limit_to_runs: int = 10,
    ) -> Optional[Recommendation]:
        """Generate a configuration recommendation.

        Args:
            accuracy_weight: Weight for accuracy (0-1)
            speed_weight: Weight for speed (0-1)
            cost_weight: Weight for cost efficiency (0-1)
            limit_to_runs: Maximum number of historical runs to consider

        Returns:
            Recommendation with best config, or None if insufficient data
        """
        # Normalize weights
        total = accuracy_weight + speed_weight + cost_weight
        if total == 0:
            total = 1.0
        weights = {
            "accuracy": accuracy_weight / total,
            "speed": speed_weight / total,
            "cost": cost_weight / total,
        }

        # Load historical runs
        history = load_evaluation_history(limit=limit_to_runs)
        runs = [r for r in history.runs if r.config_snapshot is not None]

        if len(runs) < 1:
            logger.warning("Not enough evaluation runs with config snapshots for recommendation")
            return None

        # Calculate normalized scores for each run
        scored_runs = []
        for run in runs:
            scores = self._calculate_scores(run, runs)
            if scores:
                composite = (
                    scores["accuracy"] * weights["accuracy"]
                    + scores["speed"] * weights["speed"]
                    + scores["cost"] * weights["cost"]
                )
                scored_runs.append((run, scores, composite))

        if not scored_runs:
            return None

        # Sort by composite score (highest first)
        scored_runs.sort(key=lambda x: x[2], reverse=True)

        # Best run
        best_run, best_scores, best_composite = scored_runs[0]

        # Build alternatives
        alternatives = []
        for run, scores, composite in scored_runs[1:4]:  # Top 3 alternatives
            model_name = run.config_snapshot.llm_model if run.config_snapshot else "unknown"
            alternatives.append({
                "model": model_name,
                "run_id": run.run_id,
                "composite_score": round(composite, 3),
                "accuracy": round(scores["accuracy"], 3),
                "speed": round(scores["speed"], 3),
                "cost": round(scores["cost"], 3),
                "reason": self._get_alternative_reason(scores, best_scores),
            })

        # Generate reasoning
        reasoning = self._generate_reasoning(best_run, best_scores, weights, alternatives)

        return Recommendation(
            recommended_config=best_run.config_snapshot,
            source_run_id=best_run.run_id,
            reasoning=reasoning,
            accuracy_score=best_scores["accuracy"],
            speed_score=best_scores["speed"],
            cost_score=best_scores["cost"],
            composite_score=round(best_composite, 3),
            weights=weights,
            alternatives=alternatives,
        )

    def _calculate_scores(
        self,
        run: EvaluationRun,
        all_runs: list[EvaluationRun],
    ) -> Optional[dict[str, float]]:
        """Calculate normalized scores for a run.

        Args:
            run: The run to score
            all_runs: All runs for normalization

        Returns:
            Dict with accuracy, speed, cost scores (0-1), or None if insufficient data
        """
        # Calculate accuracy score
        accuracy_values = []
        for metric in self.ACCURACY_METRICS:
            value = run.metric_averages.get(metric)
            if value is not None:
                accuracy_values.append(value)

        if not accuracy_values:
            return None

        # Average of accuracy metrics (already 0-1)
        accuracy_score = sum(accuracy_values) / len(accuracy_values)

        # Penalize for hallucination (lower is better)
        hallucination = run.metric_averages.get("hallucination", 0.5)
        accuracy_score = accuracy_score * (1 - hallucination * 0.5)

        # Calculate speed score (normalized across runs)
        speed_score = 0.5  # Default if no latency data
        if run.latency:
            latencies = [r.latency.p95_query_time_ms for r in all_runs if r.latency]
            if latencies:
                max_latency = max(latencies)
                min_latency = min(latencies)
                if max_latency > min_latency:
                    # Invert: lower latency = higher score
                    speed_score = 1 - (run.latency.p95_query_time_ms - min_latency) / (max_latency - min_latency)
                else:
                    speed_score = 1.0

        # Calculate cost score (normalized across runs)
        cost_score = 0.5  # Default if no cost data
        if run.cost:
            costs = [r.cost.cost_per_query_usd for r in all_runs if r.cost]
            if costs:
                max_cost = max(costs)
                min_cost = min(costs)
                if max_cost > min_cost:
                    # Invert: lower cost = higher score
                    cost_score = 1 - (run.cost.cost_per_query_usd - min_cost) / (max_cost - min_cost)
                elif max_cost == 0:
                    cost_score = 1.0  # Free!
                else:
                    cost_score = 0.5

        return {
            "accuracy": round(accuracy_score, 3),
            "speed": round(speed_score, 3),
            "cost": round(cost_score, 3),
        }

    def _get_alternative_reason(
        self,
        alt_scores: dict[str, float],
        best_scores: dict[str, float],
    ) -> str:
        """Generate a brief reason for an alternative.

        Args:
            alt_scores: Scores for the alternative
            best_scores: Scores for the best option

        Returns:
            Brief explanation of tradeoff
        """
        better_at = []
        worse_at = []

        for dimension in ["accuracy", "speed", "cost"]:
            diff = alt_scores[dimension] - best_scores[dimension]
            if diff > 0.05:
                better_at.append(dimension)
            elif diff < -0.05:
                worse_at.append(dimension)

        if better_at and worse_at:
            return f"Better {'/'.join(better_at)}, worse {'/'.join(worse_at)}"
        elif better_at:
            return f"Better {'/'.join(better_at)}"
        elif worse_at:
            return f"Worse {'/'.join(worse_at)}"
        else:
            return "Similar performance"

    def _generate_reasoning(
        self,
        best_run: EvaluationRun,
        scores: dict[str, float],
        weights: dict[str, float],
        alternatives: list[dict],
    ) -> str:
        """Generate human-readable reasoning for the recommendation.

        Args:
            best_run: The recommended run
            scores: Scores for the best run
            weights: User-specified weights
            alternatives: Alternative options

        Returns:
            Human-readable explanation
        """
        model_name = best_run.config_snapshot.llm_model if best_run.config_snapshot else "Unknown"

        # Describe scores
        score_parts = []
        if scores["accuracy"] >= 0.8:
            score_parts.append(f"high accuracy ({scores['accuracy']:.0%})")
        elif scores["accuracy"] >= 0.6:
            score_parts.append(f"moderate accuracy ({scores['accuracy']:.0%})")
        else:
            score_parts.append(f"lower accuracy ({scores['accuracy']:.0%})")

        if scores["speed"] >= 0.8:
            score_parts.append("fast response times")
        elif scores["speed"] <= 0.3:
            score_parts.append("slower response times")

        if scores["cost"] >= 0.9:
            score_parts.append("very cost-efficient")
        elif scores["cost"] >= 0.7:
            score_parts.append("cost-effective")
        elif scores["cost"] <= 0.3:
            score_parts.append("higher cost")

        # Build reasoning
        reasoning = f"{model_name} offers {', '.join(score_parts)}."

        # Add comparison to alternatives if meaningful
        if alternatives:
            alt_models = [a["model"] for a in alternatives[:2]]
            if alt_models:
                reasoning += f" Compared to {'/'.join(alt_models)}, it provides the best balance"

                # Mention user priority
                max_weight = max(weights.items(), key=lambda x: x[1])
                if max_weight[1] > 0.4:
                    reasoning += f" for your {max_weight[0]} priority"

                reasoning += "."

        return reasoning


# Singleton instance
_recommendation_service: Optional[RecommendationService] = None


def get_recommendation_service() -> RecommendationService:
    """Get the singleton RecommendationService instance."""
    global _recommendation_service
    if _recommendation_service is None:
        _recommendation_service = RecommendationService()
    return _recommendation_service
