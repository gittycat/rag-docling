"""cost_per_query's per-question series must describe the reported value.

`compare` bootstraps details["per_question"]. When that series held generation
cost only while `value` also carried judge and ingestion cost, a paired
significance result did not describe the point estimate printed beside it.
"""

import pytest

from evals.metrics.performance import CostPerQuery
from evals.pricing import UsageTotals
from evals.schemas import EvalQuestion, EvalResponse, QueryMetrics, TokenUsage


def _question(qid):
    return EvalQuestion(id=qid, question="q?", expected_answer="a")


def _response(qid, prompt_tokens, completion_tokens):
    return EvalResponse(
        question_id=qid,
        answer="a",
        metrics=QueryMetrics(
            latency_ms=1,
            token_usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        ),
    )


def _metric(**kwargs):
    defaults = dict(
        model="test-model",
        cost_per_1m_input_tokens=1.0,
        cost_per_1m_output_tokens=2.0,
    )
    defaults.update(kwargs)
    return CostPerQuery(**defaults)


@pytest.mark.asyncio
async def test_per_question_mean_reproduces_the_reported_value():
    questions = [_question("q1"), _question("q2")]
    responses = [_response("q1", 1000, 500), _response("q2", 3000, 1500)]
    judge = UsageTotals(model="judge-model", prompt_tokens=8000, completion_tokens=2000, calls=6)

    metric = _metric(
        judge_usage=judge,
        judge_model="judge-model",
        judge_cost_per_1m_input_tokens=1.0,
        judge_cost_per_1m_output_tokens=2.0,
        ingestion_cost_usd=0.02,
    )
    result = await metric.compute_batch(questions, responses)

    series = list(result.details["per_question"].values())
    assert len(series) == 2
    assert sum(series) / len(series) == pytest.approx(result.value)


@pytest.mark.asyncio
async def test_series_carries_judge_and_ingestion_not_generation_alone():
    questions = [_question("q1")]
    responses = [_response("q1", 1000, 500)]
    judge = UsageTotals(model="judge-model", prompt_tokens=8000, completion_tokens=2000, calls=3)

    with_extras = await _metric(
        judge_usage=judge,
        judge_model="judge-model",
        judge_cost_per_1m_input_tokens=1.0,
        judge_cost_per_1m_output_tokens=2.0,
        ingestion_cost_usd=0.02,
    ).compute_batch(questions, responses)
    generation_only = await _metric(ingestion_cost_usd=0.0).compute_batch(questions, responses)

    assert with_extras.details["per_question"]["q1"] > generation_only.details["per_question"]["q1"]
    assert with_extras.details["judge_cost_per_question"] > 0
    assert with_extras.details["ingestion_cost_per_question"] > 0


@pytest.mark.asyncio
async def test_ingestion_amortisation_is_flagged_as_sample_size_dependent():
    # The same corpus at two sample counts produces different cost_per_query for
    # reasons unrelated to the system under test. Say so rather than let two
    # runs be compared silently.
    small = await _metric(ingestion_cost_usd=0.10).compute_batch(
        [_question("q1")], [_response("q1", 1000, 500)]
    )
    large = await _metric(ingestion_cost_usd=0.10).compute_batch(
        [_question(f"q{i}") for i in range(10)],
        [_response(f"q{i}", 1000, 500) for i in range(10)],
    )

    assert small.details["sample_size_dependent"] is True
    assert "not directly comparable" in small.details["comparability_note"]
    assert small.value > large.value
    # Renormalisation is possible from the recorded components.
    assert small.details["ingestion_cost_usd"] == large.details["ingestion_cost_usd"]
    assert small.details["query_count"] == 1
    assert large.details["query_count"] == 10


@pytest.mark.asyncio
async def test_an_unpriced_component_leaves_no_bootstrappable_series():
    # value is None when anything is unpriced; a series that bootstraps cleanly
    # against a None point estimate would be worse than no series at all.
    metric = CostPerQuery(model="model-with-no-rates", ingestion_cost_usd=0.0)
    result = await metric.compute_batch([_question("q1")], [_response("q1", 1000, 500)])

    assert result.value is None
    assert result.details["per_question"] == {}
    assert "generation" in result.details["unpriced_components"]
