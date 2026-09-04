"""The funnel's job is to point at one half of the system. These pin which."""

import pytest

from evals.funnel import build_funnel


def _scorecard(stage_recall: dict[str, float], *, extra_metrics: list[dict] | None = None) -> dict:
    """A scorecard carrying per-leg recall in the shape the metrics emit."""
    return {
        "metrics": [
            {
                "name": "recall_at_5",
                "value": stage_recall.get("rerank"),
                "details": {
                    "stage_scores": {
                        f"recall_at_5{{leg={stage}}}": value for stage, value in stage_recall.items()
                    },
                    "stage_per_question": {
                        stage: {f"q{i}": 1.0 for i in range(10)} for stage in stage_recall
                    },
                },
            },
            *(extra_metrics or []),
        ]
    }


def test_reranker_bottleneck_when_it_drops_what_it_was_handed():
    funnel = build_funnel(_scorecard({"bm25": 0.7, "vector": 0.8, "fusion": 0.9, "rerank": 0.5}))

    assert funnel.ceiling == pytest.approx(0.9)
    assert funnel.final == pytest.approx(0.5)
    assert funnel.lost_before_candidates == pytest.approx(0.1)
    assert funnel.lost_in_rerank == pytest.approx(0.4)
    assert funnel.bottleneck == "rerank"
    assert "reranker is the bottleneck" in funnel.diagnosis


def test_ingestion_bottleneck_when_evidence_never_reaches_candidates():
    funnel = build_funnel(_scorecard({"bm25": 0.3, "vector": 0.35, "fusion": 0.4, "rerank": 0.38}))

    assert funnel.lost_before_candidates == pytest.approx(0.6)
    assert funnel.lost_in_rerank == pytest.approx(0.02)
    assert funnel.bottleneck == "ingestion"
    assert "never get their evidence into the candidate list" in funnel.diagnosis


def test_no_bottleneck_when_retrieval_is_already_good():
    funnel = build_funnel(_scorecard({"bm25": 0.9, "vector": 0.95, "fusion": 0.98, "rerank": 0.97}))

    assert funnel.bottleneck is None
    assert "No stage is losing enough" in funnel.diagnosis


def test_rerank_cannot_recover_evidence_so_negative_loss_is_clamped():
    # A stage population difference can make rerank score above its own ceiling.
    # That is noise, not a gain: reranking reorders candidates, it cannot add any.
    funnel = build_funnel(_scorecard({"vector": 0.6, "fusion": 0.6, "rerank": 0.65}))

    assert funnel.lost_in_rerank == 0.0


def test_pipeline_without_a_reranker_reports_no_rerank_loss():
    funnel = build_funnel(_scorecard({"bm25": 0.5, "vector": 0.7, "fusion": 0.8}))

    assert funnel.ceiling == pytest.approx(0.8)
    assert funnel.final == pytest.approx(0.8)
    assert funnel.lost_in_rerank == 0.0
    assert funnel.bottleneck == "ingestion"


def test_deltas_compare_each_stage_to_its_real_predecessor():
    funnel = build_funnel(_scorecard({"bm25": 0.4, "vector": 0.7, "fusion": 0.8, "rerank": 0.6}))
    deltas = {stage.name: stage.delta for stage in funnel.stages}

    # The legs run in parallel, so neither is the other's predecessor.
    assert deltas["bm25"] is None
    assert deltas["vector"] is None
    # Fusion is judged against the better leg, not against bm25's 0.4.
    assert deltas["fusion"] == pytest.approx(0.1)
    assert deltas["rerank"] == pytest.approx(-0.2)


def test_single_leg_pipeline_uses_that_leg_as_the_ceiling():
    funnel = build_funnel(_scorecard({"vector": 0.75, "rerank": 0.6}))

    assert funnel.ceiling == pytest.approx(0.75)
    assert funnel.lost_in_rerank == pytest.approx(0.15)


def test_generation_tier_run_has_no_funnel_rather_than_a_zero():
    # No stage scores at all: a generation-tier run, or questions with no gold.
    # Reporting 0.0 recall here would read as a total retrieval failure.
    funnel = build_funnel({"metrics": [{"name": "faithfulness", "value": 0.9, "details": {}}]})

    assert not funnel.measured
    assert funnel.final is None
    assert funnel.bottleneck is None
    assert "No per-stage retrieval scores" in funnel.note


def test_empty_scorecard_is_unmeasured_not_empty_funnel():
    funnel = build_funnel(None)

    assert not funnel.measured
    assert funnel.note == "No metrics in this run"


def test_fusion_lift_is_carried_through_from_its_own_metric():
    scorecard = _scorecard(
        {"bm25": 0.6, "vector": 0.7, "fusion": 0.85, "rerank": 0.8},
        extra_metrics=[{"name": "fusion_lift", "value": 0.12, "details": {}}],
    )
    funnel = build_funnel(scorecard)

    assert funnel.fusion_lift == pytest.approx(0.12)
    assert funnel.leg_recall == {"bm25": 0.6, "vector": 0.7}


def test_accepts_the_scorecard_dataclass_as_well_as_its_saved_dict_form():
    from evals.schemas.results import MetricGroup, MetricResult, Scorecard

    scorecard = Scorecard()
    scorecard.add_metric(
        MetricResult(
            name="recall_at_5",
            value=0.5,
            group=MetricGroup.RETRIEVAL,
            details={
                "stage_scores": {
                    "recall_at_5{leg=fusion}": 0.9,
                    "recall_at_5{leg=rerank}": 0.5,
                }
            },
        )
    )
    funnel = build_funnel(scorecard)

    assert funnel.ceiling == pytest.approx(0.9)
    assert funnel.bottleneck == "rerank"


def test_stage_question_counts_are_reported_so_thin_stages_are_visible():
    funnel = build_funnel(_scorecard({"fusion": 0.9, "rerank": 0.8}))
    counts = {stage.name: stage.questions_scored for stage in funnel.stages}

    assert counts == {"fusion": 10, "rerank": 10}
