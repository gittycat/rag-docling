"""Phase-6 deterministic failure attribution tests."""

import asyncio

from evals.attribution import attribute_question
from evals.metrics.generation import Faithfulness
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


def _scorecard(**scores: float | None) -> Scorecard:
    scorecard = Scorecard()
    for name, value in scores.items():
        scorecard.add_metric(
            MetricResult(
                name=name,
                value=value,
                group=MetricGroup.GENERATION if name == "answer_correctness" else MetricGroup.CITATION,
                details={"per_question": {"q1": value}} if value is not None else {},
            )
        )
    return scorecard


def test_retrieval_miss_makes_generation_unassessable_not_unfaithful():
    question = _question()
    response = EvalResponse(
        question_id="q1",
        answer="An unsupported answer.",
        metrics=QueryMetrics(
            latency_ms=1.0,
            stages=[
                _trace("bm25", "other-bm25"),
                _trace("vector", "other-vector"),
                _trace("fusion", "other-fusion"),
                _trace("rerank", "other-rerank"),
            ],
        ),
    )

    verdict = attribute_question(question, response, _scorecard(answer_correctness=0.0))

    assert verdict.primary_failure_stage == "retrieval_miss"
    assert verdict.failure_labels == ["retrieval_miss"]
    assert verdict.stage_evidence["generation_drift"]["assessable"] is False

    class Judge:
        async def evaluate_faithfulness(self, answer, context):  # pragma: no cover - must not run
            raise AssertionError("A judge must not be called without context")

    faithfulness = asyncio.run(Faithfulness(Judge()).compute(question, response))
    assert faithfulness.value is None


def test_reranker_demotion_is_queryable_as_the_primary_failure():
    question = _question()
    response = EvalResponse(
        question_id="q1",
        answer="",
        metrics=QueryMetrics(
            latency_ms=1.0,
            stages=[
                _trace("bm25", "gold"),
                _trace("vector", "other-vector"),
                _trace("fusion", "gold", "other-fusion"),
                _trace("rerank", "other-rerank"),
            ],
        ),
    )

    verdict = attribute_question(question, response, _scorecard(answer_correctness=0.0))

    assert verdict.primary_failure_stage == "rerank_drop"
    assert verdict.failure_labels == ["rerank_drop"]
    assert verdict.stage_evidence["rerank_drop"]["rerank"]["relevant_chunk_ids"] == []


def test_degraded_leg_is_unassessable_not_a_retrieval_miss():
    question = _question()
    response = EvalResponse(
        question_id="q1",
        answer="",
        metrics=QueryMetrics(
            latency_ms=1.0,
            stages=[
                StageTrace("bm25", 1.0, 0, items=[], status="ok"),
                StageTrace("vector", 1.0, 0, items=[], status="degraded", error="embedder down"),
            ],
        ),
    )

    verdict = attribute_question(question, response, _scorecard(answer_correctness=0.0))

    assert verdict.primary_failure_stage is None
    assert verdict.stage_evidence["retrieval_miss"]["assessable"] is False


def test_generation_drift_is_only_labeled_after_gold_reaches_context():
    question = _question()
    response = EvalResponse(
        question_id="q1",
        answer="Wrong despite the evidence.",
        retrieved_chunks=[],
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
    # Sources are the actual context assembled for generation; keep it separate
    # from a reranker ranking so this test cannot accidentally skip the gate.
    response.retrieved_chunks = [
        RetrievedChunk(doc_id="doc-1", chunk_id="gold", text="The evidence is here.", rank=1)
    ]

    verdict = attribute_question(question, response, _scorecard(answer_correctness=0.0))

    assert verdict.primary_failure_stage == "generation_drift"
    assert verdict.stage_evidence["generation_drift"]["answer_correctness"] == 0.0
