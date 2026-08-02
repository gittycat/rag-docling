"""Significance testing: paired bootstrap, McNemar, BH correction."""

import math

import pytest

from evals.stats import (
    UNDERPOWERED_N,
    benjamini_hochberg,
    compare_runs,
    extract_per_question,
    mcnemar_exact,
    paired_bootstrap,
)


def _run(run_id: str, metrics: dict[str, dict[str, float]]) -> dict:
    """Build a minimal saved-run dict carrying per-question scores."""
    return {
        "id": run_id,
        "name": run_id,
        "scorecard": {
            "metrics": [
                {
                    "name": name,
                    "value": sum(per_q.values()) / len(per_q),
                    "group": "generation",
                    "sample_size": len(per_q),
                    "details": {"per_question": per_q},
                }
                for name, per_q in metrics.items()
            ]
        },
    }


class TestPairedBootstrap:
    def test_no_difference_interval_covers_zero(self):
        lo, hi, p = paired_bootstrap([0.0] * 50, n_resamples=2000)
        assert lo == 0.0 and hi == 0.0
        assert p == 1.0

    def test_consistent_improvement_excludes_zero(self):
        lo, hi, p = paired_bootstrap([0.2] * 100, n_resamples=2000)
        assert lo > 0
        assert p <= 0.001

    def test_noisy_zero_mean_does_not_exclude_zero(self):
        deltas = [0.5 if i % 2 else -0.5 for i in range(100)]
        lo, hi, p = paired_bootstrap(deltas, n_resamples=4000)
        assert lo < 0 < hi
        assert p > 0.05

    def test_deterministic_across_calls(self):
        deltas = [0.1, -0.3, 0.4, 0.0, 0.2, -0.1, 0.35]
        assert paired_bootstrap(deltas, n_resamples=1000) == paired_bootstrap(
            deltas, n_resamples=1000
        )

    def test_empty_and_single_sample(self):
        assert paired_bootstrap([]) == (0.0, 0.0, 1.0)
        assert paired_bootstrap([0.7]) == (0.7, 0.7, 1.0)

    def test_p_value_never_zero(self):
        # The bootstrap cannot establish p = 0; it floors at 1 / n_resamples.
        _, _, p = paired_bootstrap([1.0] * 200, n_resamples=1000)
        assert p == pytest.approx(1 / 1000)


class TestMcNemar:
    def test_no_discordant_pairs_is_not_significant(self):
        assert mcnemar_exact(0, 0) == 1.0

    def test_symmetric_split_is_not_significant(self):
        assert mcnemar_exact(10, 10) == 1.0

    def test_lopsided_split_is_significant(self):
        assert mcnemar_exact(12, 1) < 0.05

    def test_matches_closed_form(self):
        # b=3, c=0 → 2 * P(X <= 0 | n=3) = 2 * 1/8
        assert mcnemar_exact(3, 0) == pytest.approx(0.25)


class TestBenjaminiHochberg:
    def test_empty(self):
        assert benjamini_hochberg([]) == []

    def test_all_null_rejects_nothing(self):
        assert benjamini_hochberg([0.6, 0.7, 0.9, 0.5]) == [False] * 4

    def test_step_up_rejects_below_the_largest_passing_rank(self):
        # p=0.03 alone fails 0.05*1/4=0.0125, but passes at rank 3 (0.0375)
        rejected = benjamini_hochberg([0.001, 0.008, 0.03, 0.9])
        assert rejected == [True, True, True, False]

        # One rank higher and it no longer passes, so nothing rides along with it
        assert benjamini_hochberg([0.001, 0.008, 0.04, 0.9]) == [True, True, False, False]

    def test_is_stricter_than_uncorrected(self):
        p_values = [0.04] + [0.9] * 19
        assert benjamini_hochberg(p_values)[0] is False


class TestCompareRuns:
    def test_pairs_only_shared_questions(self):
        a = _run("a", {"faithfulness": {"q1": 0.5, "q2": 0.5, "q3": 0.5}})
        b = _run("b", {"faithfulness": {"q1": 0.9, "q2": 0.9}})
        report = compare_runs(a, b, n_resamples=500)

        assert len(report.metrics) == 1
        assert report.metrics[0].n_paired == 2
        assert report.metrics[0].delta == pytest.approx(0.4)

    def test_binary_metric_uses_mcnemar_and_reports_flips(self):
        a = _run("a", {"recall_at_5": {f"q{i}": 0.0 for i in range(20)}})
        b = _run("b", {"recall_at_5": {f"q{i}": 1.0 if i < 15 else 0.0 for i in range(20)}})
        report = compare_runs(a, b, n_resamples=500)

        metric = report.metrics[0]
        assert metric.test == "mcnemar_exact"
        assert metric.discordant_b_better == 15
        assert metric.discordant_a_better == 0
        assert metric.p_value < 0.001

    def test_continuous_metric_uses_bootstrap(self):
        a = _run("a", {"faithfulness": {f"q{i}": 0.4 for i in range(30)}})
        b = _run("b", {"faithfulness": {f"q{i}": 0.55 for i in range(30)}})
        assert compare_runs(a, b, n_resamples=500).metrics[0].test == "paired_bootstrap"

    def test_small_comparison_is_flagged_underpowered(self):
        a = _run("a", {"faithfulness": {f"q{i}": 0.4 for i in range(10)}})
        b = _run("b", {"faithfulness": {f"q{i}": 0.6 for i in range(10)}})
        assert compare_runs(a, b, n_resamples=500).metrics[0].underpowered

    def test_large_comparison_is_not_flagged_underpowered(self):
        n = UNDERPOWERED_N + 5
        a = _run("a", {"faithfulness": {f"q{i}": 0.4 for i in range(n)}})
        b = _run("b", {"faithfulness": {f"q{i}": 0.6 for i in range(n)}})
        assert not compare_runs(a, b, n_resamples=500).metrics[0].underpowered

    def test_metric_without_per_question_data_is_skipped_not_guessed(self):
        a = {
            "id": "a",
            "scorecard": {
                "metrics": [
                    {"name": "latency_p50_ms", "value": 100.0, "group": "performance",
                     "sample_size": 5, "details": {}}
                ]
            },
        }
        b = {
            "id": "b",
            "scorecard": {
                "metrics": [
                    {"name": "latency_p50_ms", "value": 200.0, "group": "performance",
                     "sample_size": 5, "details": {}}
                ]
            },
        }
        report = compare_runs(a, b, n_resamples=200)
        assert report.metrics == []
        assert "latency_p50_ms" in report.skipped

    def test_family_arithmetic_is_surfaced(self):
        metrics = {f"m{i}": {f"q{j}": 0.5 for j in range(5)} for i in range(20)}
        report = compare_runs(_run("a", metrics), _run("b", metrics), n_resamples=200)

        assert report.family_size == 20
        assert report.expected_false_positives == pytest.approx(1.0)
        assert report.any_spurious_probability == pytest.approx(
            1 - 0.95 ** 20, abs=1e-6
        )

    def test_extract_per_question_ignores_null_scores(self):
        run = {
            "scorecard": {
                "metrics": [
                    {"name": "citation_recall", "value": None, "group": "citation",
                     "details": {"per_question": {"q1": None, "q2": 0.5}}}
                ]
            }
        }
        assert extract_per_question(run) == {"citation_recall": {"q2": 0.5}}
