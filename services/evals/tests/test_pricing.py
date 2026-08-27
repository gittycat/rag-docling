"""Pricing resolution, "unpriced" as a state, and judge-inclusive cost.

The question the cost objective exists to answer is whether self-hosted
open-weight inference is actually cheaper than a frontier API. It could not
answer it before: an unmatched model id cost $0, so self-hosting won by label
rather than by measurement. These tests pin the corrected behaviour.
"""

import asyncio
import json

import pytest
from conftest import stub_judge

from evals.metrics.performance import CostPerQuery
from evals.pricing import (
    RATE_OVERRIDE_ENV,
    UsageTotals,
    get_model_cost,
    is_priced,
    resolve_rates,
)
from evals.schemas import EvalQuestion, EvalResponse, QueryMetrics, TokenUsage


@pytest.fixture(autouse=True)
def _no_rate_overrides(monkeypatch):
    monkeypatch.delenv(RATE_OVERRIDE_ENV, raising=False)


def _response(qid: str, prompt: int, completion: int) -> EvalResponse:
    return EvalResponse(
        question_id=qid,
        answer="a",
        metrics=QueryMetrics(
            latency_ms=100,
            token_usage=TokenUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
            ),
        ),
    )


def _question(qid: str) -> EvalQuestion:
    return EvalQuestion(id=qid, question="q?", expected_answer="a")


class TestRateResolution:
    def test_exact_id_resolves_from_the_table(self):
        rates = resolve_rates("gpt-5.2")
        assert rates is not None
        assert (rates.input_per_1m, rates.output_per_1m) == (1.75, 14.00)
        assert rates.source == "table"

    def test_matching_is_case_insensitive(self):
        assert resolve_rates("GPT-4o") == resolve_rates("gpt-4o")

    def test_hf_repo_id_resolves_against_a_bare_name_entry(self, monkeypatch):
        # The override is keyed by bare name; the served id is a repo id.
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV, json.dumps({"Qwen3-32B-AWQ": {"input": 0.4, "output": 0.9}})
        )
        rates = resolve_rates("Qwen/Qwen3-32B-AWQ")
        assert rates is not None
        assert (rates.input_per_1m, rates.output_per_1m) == (0.4, 0.9)

    def test_namespace_wildcard_matches_only_that_namespace(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV, json.dumps({"acme/*": {"input": 1.0, "output": 2.0}})
        )
        assert resolve_rates("acme/some-model") is not None
        # The old implementation matched on `provider in model.lower()`, which
        # would have let this substring match too.
        assert resolve_rates("not-acme-at-all") is None

    def test_unknown_model_is_unpriced_not_free(self):
        assert resolve_rates("Qwen/Qwen3-32B-AWQ") is None
        assert resolve_rates("some-unknown-model") is None
        assert is_priced("some-unknown-model") is False
        assert get_model_cost("some-unknown-model", 10_000, 5_000) is None

    def test_vllm_wildcard_no_longer_prices_open_weights_at_zero(self):
        # The former "vllm/*" entry never matched a real served id anyway.
        assert resolve_rates("Qwen/Qwen2.5-14B-Instruct") is None

    def test_explicitly_configured_zero_is_priced(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV,
            json.dumps({"Qwen/Qwen3-32B-AWQ": {"input": 0.0, "output": 0.0}}),
        )
        rates = resolve_rates("Qwen/Qwen3-32B-AWQ")
        assert rates is not None
        assert rates.source == "environment"
        assert get_model_cost("Qwen/Qwen3-32B-AWQ", 10_000, 5_000) == 0.0

    def test_injected_rates_win_over_the_table(self):
        rates = resolve_rates("gpt-4o", 0.5, 1.5)
        assert rates is not None
        assert (rates.input_per_1m, rates.output_per_1m, rates.source) == (0.5, 1.5, "injected")

    def test_half_a_rate_pair_is_an_error(self):
        with pytest.raises(ValueError):
            resolve_rates("gpt-4o", 0.5, None)

    def test_environment_overrides_beat_the_table(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV, json.dumps({"gpt-4o": {"input": 9.0, "output": 9.0}})
        )
        rates = resolve_rates("gpt-4o")
        assert rates is not None
        assert rates.input_per_1m == 9.0
        assert rates.source == "environment"

    def test_malformed_override_is_dropped_not_treated_as_zero(self, monkeypatch):
        monkeypatch.setenv(RATE_OVERRIDE_ENV, json.dumps({"mystery-model": {"input": 1.0}}))
        assert resolve_rates("mystery-model") is None

    def test_malformed_json_is_ignored(self, monkeypatch):
        monkeypatch.setenv(RATE_OVERRIDE_ENV, "{not json")
        assert resolve_rates("gpt-4o") is not None  # falls through to the table

    def test_cost_arithmetic(self):
        # gpt-4o: $2.50/1M in, $10.00/1M out
        assert get_model_cost("gpt-4o", 2000, 1000) == pytest.approx(0.015)


class TestUnpricedIsExcludedFromCost:
    def test_unpriced_generation_model_yields_no_cost_value(self):
        metric = CostPerQuery(model="Qwen/Qwen3-32B-AWQ")
        result = metric.compute(_question("q1"), _response("q1", 1000, 500))

        assert result.value is None
        assert result.details["rate_source"] == "unpriced"

    def test_unpriced_batch_reports_none_with_an_explanation(self):
        metric = CostPerQuery(model="Qwen/Qwen3-32B-AWQ")
        result = asyncio.run(
            metric.compute_batch([_question("q1")], [_response("q1", 1000, 500)])
        )

        assert result.value is None
        assert result.details["total_cost_usd"] is None
        assert result.details["unpriced_components"] == ["generation"]
        assert result.details["total_prompt_tokens"] == 1000

    def test_no_token_usage_is_unknown_not_zero(self):
        metric = CostPerQuery(model="gpt-4o")
        response = EvalResponse(question_id="q1", answer="a")
        result = asyncio.run(metric.compute_batch([_question("q1")], [response]))

        assert result.value is None

    def test_injected_rates_make_a_self_hosted_model_scoreable(self):
        metric = CostPerQuery(
            model="Qwen/Qwen3-32B-AWQ",
            cost_per_1m_input_tokens=0.30,
            cost_per_1m_output_tokens=0.30,
        )
        result = asyncio.run(
            metric.compute_batch([_question("q1")], [_response("q1", 1_000_000, 0)])
        )

        assert result.value == pytest.approx(0.30)
        assert result.details["rate_source"] == "injected"


class TestJudgeTokensAreCounted:
    def test_judge_cost_is_added_and_attributed_separately(self):
        judge_usage = UsageTotals(model="gpt-5.2")
        # Three judge calls per query, which is where the tokens actually are.
        for _ in range(3):
            judge_usage.record(prompt_tokens=1_000_000, completion_tokens=0)

        metric = CostPerQuery(
            model="gpt-4o",
            judge_usage=judge_usage,
            judge_model="gpt-5.2",
        )
        result = asyncio.run(
            metric.compute_batch([_question("q1")], [_response("q1", 1_000_000, 0)])
        )

        generation = 2.50           # 1M input tokens at gpt-4o rates
        judging = 3 * 1.75          # 3M input tokens at gpt-5.2 rates
        assert result.details["generation_cost_usd"] == pytest.approx(generation)
        assert result.details["judge"]["cost_usd"] == pytest.approx(judging)
        assert result.details["judge"]["calls"] == 3
        assert result.value == pytest.approx(generation + judging)

    def test_generation_only_cost_understates_the_run(self):
        judge_usage = UsageTotals(model="gpt-5.2")
        judge_usage.record(prompt_tokens=1_000_000, completion_tokens=0)

        without = asyncio.run(
            CostPerQuery(model="gpt-4o").compute_batch(
                [_question("q1")], [_response("q1", 1_000_000, 0)]
            )
        )
        with_judge = asyncio.run(
            CostPerQuery(
                model="gpt-4o", judge_usage=judge_usage, judge_model="gpt-5.2"
            ).compute_batch([_question("q1")], [_response("q1", 1_000_000, 0)])
        )

        assert with_judge.value > without.value

    def test_unpriced_judge_makes_the_whole_cost_unpriced(self):
        judge_usage = UsageTotals(model="Qwen/Qwen3-32B-AWQ")
        judge_usage.record(prompt_tokens=1_000_000, completion_tokens=0)

        result = asyncio.run(
            CostPerQuery(
                model="gpt-4o",
                judge_usage=judge_usage,
                judge_model="Qwen/Qwen3-32B-AWQ",
            ).compute_batch([_question("q1")], [_response("q1", 1_000_000, 0)])
        )

        assert result.value is None
        assert result.details["unpriced_components"] == ["judge"]
        # The generation figure is still visible, it is just not the run's cost.
        assert result.details["generation_cost_usd"] == pytest.approx(2.50)

    def test_idle_judge_adds_nothing(self):
        result = asyncio.run(
            CostPerQuery(
                model="gpt-4o", judge_usage=UsageTotals(model="gpt-5.2")
            ).compute_batch([_question("q1")], [_response("q1", 1_000_000, 0)])
        )

        assert result.value == pytest.approx(2.50)


class TestUsageTotals:
    def test_record_accumulates(self):
        totals = UsageTotals(model="m")
        totals.record(10, 5)
        totals.record(1, 2)

        assert (totals.prompt_tokens, totals.completion_tokens, totals.calls) == (11, 7, 2)
        assert totals.has_usage is True

    def test_empty_ledger_has_no_usage(self):
        assert UsageTotals().has_usage is False


class TestCostObjectiveExcludesUnpriced:
    """An unpriced run must not score the cost objective at all."""

    @staticmethod
    def _score(cost_value):
        from evals.config import EvalConfig, EvalTier, ScoringConfig
        from evals.runner import EvaluationRunner
        from evals.schemas import MetricGroup, MetricResult, Scorecard

        scorecard = Scorecard()
        scorecard.add_metric(
            MetricResult(
                name="cost_per_query",
                value=cost_value,
                group=MetricGroup.PERFORMANCE,
                sample_size=10,
            )
        )
        scorecard.add_metric(
            MetricResult(
                name="faithfulness",
                value=0.5,
                group=MetricGroup.GENERATION,
                sample_size=10,
            )
        )
        config = EvalConfig(
            judge=stub_judge(),
            scoring=ScoringConfig(
                weights={"cost": 0.5, "faithfulness": 0.5}, max_cost_per_query_usd=0.10
            ),
            tier=EvalTier.END_TO_END,
            datasets=["ragbench"],
        )
        return EvaluationRunner(config)._compute_weighted_score(scorecard)

    def test_unpriced_cost_is_left_out_of_the_objectives(self):
        result = self._score(None)

        assert "cost" not in result.objectives
        # Weight is redistributed rather than awarded — the old code scored an
        # unpriced (falsy) cost as a perfect 1.0.
        assert result.score == pytest.approx(0.5)

    def test_explicit_zero_cost_still_scores_perfectly(self):
        result = self._score(0.0)

        assert result.objectives["cost"] == 1.0

    def test_priced_cost_is_normalized_against_the_threshold(self):
        result = self._score(0.05)

        assert result.objectives["cost"] == pytest.approx(0.5)
