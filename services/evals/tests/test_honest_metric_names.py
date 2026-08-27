"""A reported number must mean what its name says.

Two defects, one class. `answer_completeness` on the dashboard was
`lookup.get("answer_correctness")` — a different failure mode under a name
nothing measured. And `uncited_claim_rate` returned a constant 1.0 under the
shipped `citation_scope: retrieved`, because the server never asks the model for
inline markers in that mode, so no claim can ever be cited.

Both looked measured. Neither was.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from api.dashboard import compute_dashboard_metrics
from api.schemas import DashboardMetrics
from evals.metrics.groundedness import UncitedClaimRate
from evals.schemas import EvalQuestion, EvalResponse, MetricGroup, MetricResult, Scorecard


def _scorecard(**metric_values) -> dict:
    return {"metrics": [{"name": k, "value": v} for k, v in metric_values.items()]}


# ── F5: completeness is not correctness ───────────────────────────────────────


def test_completeness_is_not_aliased_to_correctness():
    """The defect: a dashboard showing 0.82 "completeness" that was only ever the
    correctness score wearing another name."""
    metrics = compute_dashboard_metrics(_scorecard(answer_correctness=0.82), tier="generation")

    assert metrics.answer_correctness == 0.82
    assert metrics.answer_completeness is None


def test_completeness_reads_its_own_metric_when_one_exists():
    """Wiring check for the day a real completeness metric lands."""
    metrics = compute_dashboard_metrics(
        _scorecard(answer_correctness=0.82, answer_completeness=0.41), tier="generation"
    )

    assert metrics.answer_correctness == 0.82
    assert metrics.answer_completeness == 0.41


def test_correctness_has_a_home_under_its_own_name():
    assert "answer_correctness" in DashboardMetrics.model_fields


def test_an_absent_scorecard_reports_nothing_rather_than_zero():
    """No scorecard is no data — the dashboard shows nothing, not zeroes."""
    assert compute_dashboard_metrics(None, tier="generation") is None
    assert compute_dashboard_metrics({"metrics": []}, tier="generation") is None


# ── F6: an unmeasurable rate is undefined, not 1.0 ────────────────────────────


def _response(answer: str) -> EvalResponse:
    return EvalResponse(question_id="q1", answer=answer)


QUESTION = EvalQuestion(id="q1", question="What is it?", expected_answer="It is a thing.")

# Claim extraction skips very short fragments, so these are full sentences.
UNCITED_ANSWER = (
    "The sky above the city is a deep blue colour today. "
    "Water from the tap is wet and cold. "
    "Fire in the hearth is extremely hot."
)
PARTIALLY_CITED_ANSWER = (
    "The sky above the city is a deep blue colour today [1]. "
    "Water from the tap is wet and cold. "
    "Fire in the hearth is extremely hot."
)
FULLY_CITED_ANSWER = (
    "The sky above the city is a deep blue colour today [1]. "
    "Water from the tap is wet and cold [2]."
)


def test_an_answer_with_no_markers_anywhere_is_undefined_not_one():
    """This is exactly the shape every answer has under citation_scope:
    'retrieved' — the model is never asked for markers, so 1.0 would be a
    property of the config, not of the answer."""
    result = UncitedClaimRate().compute(QUESTION, _response(UNCITED_ANSWER))

    assert result.value is None
    assert "citation_scope" in result.details["note"]


def test_a_partially_cited_answer_still_reports_a_rate():
    """The metric must keep working where it can actually be computed."""
    result = UncitedClaimRate().compute(QUESTION, _response(PARTIALLY_CITED_ANSWER))

    assert result.value == pytest.approx(2 / 3)
    assert result.details["uncited_claims"] == 2


def test_a_fully_cited_answer_scores_zero():
    result = UncitedClaimRate().compute(QUESTION, _response(FULLY_CITED_ANSWER))

    assert result.value == 0.0


# ── A skipped group explains itself ───────────────────────────────────────────


def test_scorecard_carries_notes():
    scorecard = Scorecard()
    scorecard.notes.append("groundedness group disabled (opt-in)")

    assert scorecard.notes == ["groundedness group disabled (opt-in)"]


def test_notes_survive_the_save_and_reload_round_trip(tmp_path):
    """A note that vanishes on reload leaves the exported report claiming the
    metrics simply were not there."""
    import json

    from evals.cli import _run_from_dict

    payload = {
        "id": "run-1",
        "name": "test",
        "created_at": "2026-08-27T00:00:00",
        "config": {},
        "scorecard": {
            "metrics": [
                {"name": "faithfulness", "value": 0.9, "group": MetricGroup.GENERATION.value}
            ],
            "notes": ["groundedness group disabled (opt-in)"],
        },
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(payload))

    run = _run_from_dict(json.loads(path.read_text()))

    assert run.scorecard.notes == ["groundedness group disabled (opt-in)"]


def test_the_run_report_prints_the_notes(tmp_path):
    from datetime import datetime

    from evals.export import export_run_report
    from evals.schemas import ConfigSnapshot, EvalRun

    scorecard = Scorecard()
    scorecard.add_metric(
        MetricResult(name="faithfulness", value=0.9, group=MetricGroup.GENERATION, sample_size=1)
    )
    scorecard.notes.append("groundedness group disabled (opt-in)")

    run = EvalRun(
        id="run-1",
        name="test",
        created_at=datetime.now(),
        config=ConfigSnapshot(
            llm_model="gpt-5.2", llm_provider="openai", embedding_model="qwen3"
        ),
        datasets=["ragbench"],
        scorecard=scorecard,
        question_count=1,
    )

    out = export_run_report(run, tmp_path / "report.md")

    assert "groundedness group disabled" in out.read_text()
