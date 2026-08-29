"""Track G: the paired contextual-retrieval delta protocol.

Phase 4 required A/B delta protocols as runner modes. Only the per-source half
shipped (--retrieval-only with --retrieval-source). This covers the other half:
contextual retrieval on vs off, with the ingestion price attached.
"""

import pytest

from evals.config import EvalConfig, EvalTier, JudgeConfig
from evals.contextual_ab import build_report, run_contextual_ab


def _run(run_id, *, recall, ndcg, ingest_cost=None, ingest_latency=None, per_question=None):
    metrics = [
        {"name": "recall_at_5", "value": recall, "group": "retrieval",
         "details": {"per_question": per_question or {}}},
        {"name": "ndcg_at_10", "value": ndcg, "group": "retrieval", "details": {}},
    ]
    if ingest_cost is not None:
        metrics.append({
            "name": "ingestion_cost_per_document", "value": ingest_cost,
            "group": "performance", "details": {},
        })
    if ingest_latency is not None:
        metrics.append({
            "name": "ingestion_latency_per_document", "value": ingest_latency,
            "group": "performance", "details": {},
        })
    return {"id": run_id, "name": run_id, "scorecard": {"metrics": metrics}}


def test_retrieval_and_ingestion_deltas_are_both_reported():
    # The comparison only means something with both halves: contextual
    # retrieval buys retrieval quality and costs ingestion time and money.
    on = _run("on", recall=0.80, ndcg=0.75, ingest_cost=0.05, ingest_latency=9000.0)
    off = _run("off", recall=0.65, ndcg=0.60, ingest_cost=0.01, ingest_latency=1200.0)

    report = build_report(on, off, n_resamples=50)

    deltas = {d.name: d.delta for d in report.retrieval_deltas}
    assert deltas["recall_at_5"] == pytest.approx(0.15)
    assert deltas["ndcg_at_10"] == pytest.approx(0.15)

    ingestion = {d.name: d.delta for d in report.ingestion_deltas}
    assert ingestion["ingestion_cost_per_document"] == pytest.approx(0.04)
    assert ingestion["ingestion_latency_per_document"] == pytest.approx(7800.0)


def test_a_missing_ingestion_measurement_is_called_out_not_silently_dropped():
    on = _run("on", recall=0.80, ndcg=0.75)
    off = _run("off", recall=0.65, ndcg=0.60)

    report = build_report(on, off, n_resamples=50)

    assert report.ingestion_deltas == []
    assert any("cannot be weighed" in note for note in report.notes)


def test_an_undefined_metric_yields_no_delta_and_says_so():
    # None is not 0.0: a metric undefined in one arm has no delta, and the
    # report must not manufacture one.
    on = _run("on", recall=0.80, ndcg=None, ingest_cost=0.05)
    off = _run("off", recall=0.65, ndcg=0.60, ingest_cost=0.01)

    report = build_report(on, off, n_resamples=50)

    ndcg = next(d for d in report.retrieval_deltas if d.name == "ndcg_at_10")
    assert ndcg.delta is None
    assert any("ndcg_at_10" in note for note in report.notes)


def test_significance_reuses_the_existing_compare_path():
    # Not a second statistics implementation: the same paired bootstrap that
    # `evals compare` uses, so the two never disagree.
    on = _run("on", recall=0.80, ndcg=0.75, ingest_cost=0.05,
              per_question={"q1": 1.0, "q2": 1.0, "q3": 0.0, "q4": 1.0})
    off = _run("off", recall=0.50, ndcg=0.60, ingest_cost=0.01,
               per_question={"q1": 0.0, "q2": 1.0, "q3": 0.0, "q4": 0.0})

    report = build_report(on, off, n_resamples=200)

    assert report.significance is not None
    assert report.significance.run_a == "off"
    assert report.significance.run_b == "on"


@pytest.mark.asyncio
async def test_the_ab_refuses_a_tier_that_never_ingests():
    # Contextual retrieval is an ingestion-time behaviour; comparing it in a
    # tier that reuses a corpus would measure nothing.
    config = EvalConfig(
        datasets=[],
        tier=EvalTier.GENERATION,
        judge=JudgeConfig(provider="test", model="test", enabled=False),
    )
    with pytest.raises(ValueError, match="end_to_end"):
        await run_contextual_ab(config)
