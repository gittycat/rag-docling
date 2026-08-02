"""Weighted-score weights and normalization thresholds are configuration, not constants."""

import pytest

from evals.config import (
    DEFAULT_MAX_COST_PER_QUERY_USD,
    EvalConfig,
    EvalTier,
    ScoringConfig,
)
from evals.runner import EvaluationRunner
from evals.schemas import MetricGroup, MetricResult, Scorecard


def _scorecard(**metrics) -> Scorecard:
    sc = Scorecard()
    groups = {
        "latency_p50_ms": MetricGroup.PERFORMANCE,
        "cost_per_query": MetricGroup.PERFORMANCE,
        "faithfulness": MetricGroup.GENERATION,
        "citation_recall": MetricGroup.CITATION,
    }
    for name, value in metrics.items():
        sc.add_metric(
            MetricResult(name=name, value=value, group=groups[name], sample_size=10)
        )
    return sc


def _runner(scoring: ScoringConfig, tier=EvalTier.END_TO_END) -> EvaluationRunner:
    return EvaluationRunner(EvalConfig(scoring=scoring, tier=tier, datasets=["ragbench"]))


class TestLatencyThreshold:
    def test_threshold_is_read_from_config(self):
        scoring = ScoringConfig(
            weights={"latency": 1.0}, latency_threshold_ms_end_to_end=10_000
        )
        result = _runner(scoring)._compute_weighted_score(
            _scorecard(latency_p50_ms=5_000)
        )
        assert result.objectives["latency"] == pytest.approx(0.5)

    def test_tighter_threshold_scores_the_same_latency_worse(self):
        lenient = ScoringConfig(weights={"latency": 1.0}, latency_threshold_ms_end_to_end=20_000)
        strict = ScoringConfig(weights={"latency": 1.0}, latency_threshold_ms_end_to_end=4_000)
        card = _scorecard(latency_p50_ms=4_000)

        assert _runner(lenient)._compute_weighted_score(card).objectives["latency"] == pytest.approx(0.8)
        assert _runner(strict)._compute_weighted_score(card).objectives["latency"] == 0.0

    def test_tier_selects_the_threshold(self):
        scoring = ScoringConfig(
            weights={"latency": 1.0},
            latency_threshold_ms_generation=1_000,
            latency_threshold_ms_end_to_end=10_000,
        )
        assert scoring.latency_threshold_ms(EvalTier.GENERATION) == 1_000
        assert scoring.latency_threshold_ms(EvalTier.END_TO_END) == 10_000


class TestCostThreshold:
    def test_threshold_is_read_from_config(self):
        scoring = ScoringConfig(weights={"cost": 1.0}, max_cost_per_query_usd=0.02)
        result = _runner(scoring)._compute_weighted_score(_scorecard(cost_per_query=0.01))
        assert result.objectives["cost"] == pytest.approx(0.5)

    def test_free_models_score_one(self):
        scoring = ScoringConfig(weights={"cost": 1.0})
        result = _runner(scoring)._compute_weighted_score(_scorecard(cost_per_query=0.0))
        assert result.objectives["cost"] == 1.0

    def test_default_matches_the_documented_constant(self):
        assert ScoringConfig().max_cost_per_query_usd == DEFAULT_MAX_COST_PER_QUERY_USD


class TestUndefinedMetricsAreExcluded:
    def test_undefined_metric_does_not_contribute_to_its_objective(self):
        scoring = ScoringConfig(weights={"citation": 1.0, "faithfulness": 1.0})
        card = _scorecard(faithfulness=0.8, citation_recall=None)

        result = _runner(scoring)._compute_weighted_score(card)

        # citation has no data, so its weight is redistributed rather than the
        # objective being scored 0 (or, worse, a fabricated 1.0)
        assert "citation" not in result.objectives
        assert result.score == pytest.approx(0.8)

    def test_undefined_latency_does_not_produce_an_objective(self):
        scoring = ScoringConfig(weights={"latency": 1.0, "faithfulness": 1.0})
        card = _scorecard(faithfulness=0.5, latency_p50_ms=None)

        result = _runner(scoring)._compute_weighted_score(card)
        assert "latency" not in result.objectives


class TestConfigPlumbing:
    def test_weights_property_delegates_to_scoring(self):
        config = EvalConfig(scoring=ScoringConfig(weights={"accuracy": 1.0}))
        assert config.weights == {"accuracy": 1.0}

    def test_scoring_accepts_a_plain_dict(self):
        config = EvalConfig(scoring={"weights": {"accuracy": 1.0}, "max_cost_per_query_usd": 0.5})
        assert isinstance(config.scoring, ScoringConfig)
        assert config.scoring.max_cost_per_query_usd == 0.5

    def test_yaml_round_trip_preserves_scoring(self, tmp_path):
        path = tmp_path / "eval.yml"
        original = EvalConfig(
            datasets=["ragbench"],
            scoring=ScoringConfig(
                weights={"accuracy": 0.7, "latency": 0.3},
                latency_threshold_ms_end_to_end=12_345,
                max_cost_per_query_usd=0.42,
            ),
        )
        original.to_yaml(path)
        loaded = EvalConfig.from_yaml(path)

        assert loaded.scoring.weights == {"accuracy": 0.7, "latency": 0.3}
        assert loaded.scoring.latency_threshold_ms_end_to_end == 12_345
        assert loaded.scoring.max_cost_per_query_usd == 0.42

    def test_legacy_top_level_weights_key_still_loads(self, tmp_path):
        path = tmp_path / "legacy.yml"
        path.write_text("datasets: [ragbench]\nweights: {accuracy: 1.0}\n")

        loaded = EvalConfig.from_yaml(path)
        assert loaded.weights == {"accuracy": 1.0}


class TestScoringSettingsValidation:
    def test_negative_weights_are_rejected(self):
        from infrastructure.config.models_config import ScoringSettings

        with pytest.raises(ValueError, match="negative"):
            ScoringSettings(weights={"accuracy": -0.1})

    def test_all_zero_weights_are_rejected(self):
        from infrastructure.config.models_config import ScoringSettings

        with pytest.raises(ValueError, match="greater than zero"):
            ScoringSettings(weights={"accuracy": 0.0, "latency": 0.0})
