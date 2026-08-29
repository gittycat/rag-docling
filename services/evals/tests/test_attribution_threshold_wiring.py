"""Proves EvalConfig's attribution thresholds actually reach attribute_questions.

runner.py used to call attribute_questions() positionally, so
EvalConfig.correctness_threshold / supporting_metric_threshold were declared
fields that no run ever consulted — the module defaults (0.5) were the only
thresholds that mattered. This exercises the runner's own wiring, not
attribute_question() directly, since that already honours an explicit
threshold argument regardless of whether the runner forwards config.
"""

from conftest import stub_judge

from evals.config import EvalConfig
from evals.schemas import (
    EvalQuestion,
    EvalResponse,
    GoldPassage,
    MetricGroup,
    MetricResult,
    QueryMetrics,
    RetrievedChunk,
    Scorecard,
    StageItem,
    StageTrace,
)


def _trace(name: str, *chunk_ids: str) -> StageTrace:
    return StageTrace(
        name=name,
        duration_ms=1.0,
        item_count=len(chunk_ids),
        items=[
            StageItem(chunk_id=chunk_id, doc_id="doc-1", rank=index + 1)
            for index, chunk_id in enumerate(chunk_ids)
        ],
    )


def _question() -> EvalQuestion:
    return EvalQuestion(
        id="q1",
        question="Where is the evidence?",
        expected_answer="The evidence is here.",
        gold_passages=[GoldPassage(doc_id="doc-1", chunk_id="gold", text="The evidence is here.")],
    )


def _full_success_chain_response(answer: str = "The evidence is here.") -> EvalResponse:
    response = EvalResponse(
        question_id="q1",
        answer=answer,
        metrics=QueryMetrics(
            latency_ms=1.0,
            stages=[
                _trace("bm25", "gold"),
                _trace("vector", "gold"),
                _trace("fusion", "gold"),
                _trace("rerank", "gold"),
            ],
        ),
    )
    response.retrieved_chunks = [
        RetrievedChunk(doc_id="doc-1", chunk_id="gold", text="The evidence is here.", rank=1)
    ]
    return response


def _scorecard(answer_correctness: float) -> Scorecard:
    scorecard = Scorecard()
    scorecard.add_metric(
        MetricResult(
            name="answer_correctness",
            value=answer_correctness,
            group=MetricGroup.GENERATION,
            details={"per_question": {"q1": answer_correctness}},
        )
    )
    return scorecard


def _runner(**threshold_overrides):
    from evals.runner import EvaluationRunner

    return EvaluationRunner(EvalConfig(judge=stub_judge(), **threshold_overrides))


def test_default_threshold_lets_a_0_8_score_pass_through_the_runner():
    runner = _runner()
    question = _question()
    response = _full_success_chain_response()

    verdicts = runner._attribute_questions([question], [response], _scorecard(0.8))

    assert verdicts[0].primary_failure_stage == "correct"


def test_runner_forwards_a_stricter_correctness_threshold_from_config():
    # Same 0.8 score as above, but the run was configured with a 0.9 bar.
    # Before the fix, runner.run() called attribute_questions() without
    # forwarding this field, so this override was silently ignored.
    runner = _runner(correctness_threshold=0.9)
    question = _question()
    response = _full_success_chain_response()

    verdicts = runner._attribute_questions([question], [response], _scorecard(0.8))

    assert verdicts[0].primary_failure_stage == "generation_drift"
