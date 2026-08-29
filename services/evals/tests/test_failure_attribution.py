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


_METRIC_GROUP_BY_NAME = {
    "answer_correctness": MetricGroup.GENERATION,
    "faithfulness": MetricGroup.GENERATION,
    "answer_completeness": MetricGroup.GENERATION,
    "answer_relevancy": MetricGroup.GENERATION,
    "claim_groundedness": MetricGroup.GROUNDEDNESS,
}


def _scorecard(**scores: float | None) -> Scorecard:
    scorecard = Scorecard()
    for name, value in scores.items():
        scorecard.add_metric(
            MetricResult(
                name=name,
                value=value,
                group=_METRIC_GROUP_BY_NAME.get(name, MetricGroup.CITATION),
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


def _full_success_chain_response(answer: str = "Wrong despite the evidence.") -> EvalResponse:
    """A response whose bm25/vector/fusion/rerank traces and final sources all hit gold."""
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
    # Sources are the actual context assembled for generation; keep it separate
    # from a reranker ranking so tests cannot accidentally skip the gate.
    response.retrieved_chunks = [
        RetrievedChunk(doc_id="doc-1", chunk_id="gold", text="The evidence is here.", rank=1)
    ]
    return response


def test_two_assessable_failures_both_appear_with_earliest_as_primary():
    question = _question()
    response = _full_success_chain_response()

    verdict = attribute_question(
        question,
        response,
        _scorecard(answer_correctness=0.0, citation_precision=0.0),
    )

    assert verdict.primary_failure_stage == "generation_drift"
    assert verdict.failure_labels == ["generation_drift", "citation_error"]
    assert verdict.stage_evidence["generation_drift"]["assessable"] is True
    assert verdict.stage_evidence["citation_error"]["assessable"] is True
    assert verdict.stage_evidence["citation_error"]["supported"] is True


def test_vector_only_deployment_can_report_retrieval_miss():
    question = _question()
    response = EvalResponse(
        question_id="q1",
        answer="",
        metrics=QueryMetrics(
            latency_ms=1.0,
            # No bm25 trace at all — a vector-only deployment never runs it.
            stages=[_trace("vector", "other-vector")],
        ),
    )

    verdict = attribute_question(question, response, _scorecard(answer_correctness=0.0))

    assert verdict.primary_failure_stage == "retrieval_miss"
    assert verdict.failure_labels == ["retrieval_miss"]
    retrieval_evidence = verdict.stage_evidence["retrieval_miss"]
    assert retrieval_evidence["assessable"] is True
    assert retrieval_evidence["legs_used"] == ["vector"]
    assert retrieval_evidence["legs_degraded"] == []


def test_correctness_one_with_zero_faithfulness_is_not_correct():
    question = _question()
    response = _full_success_chain_response(answer="Right answer, wrong basis.")

    verdict = attribute_question(
        question,
        response,
        _scorecard(answer_correctness=1.0, faithfulness=0.0),
    )

    assert verdict.primary_failure_stage != "correct"
    assert "correct" not in verdict.failure_labels
    assert verdict.primary_failure_stage == "generation_drift"
    drift_evidence = verdict.stage_evidence["generation_drift"]
    assert drift_evidence["supported"] is True
    assert drift_evidence["failing_supporting_metrics"] == {"faithfulness": 0.0}


def test_a_strong_but_imperfect_answer_is_correct_not_drift():
    # The exactness regression: demanding an exact 1.0 on continuous judge scores
    # made "correct" nearly unreachable and fired generation_drift on almost
    # everything. A 0.9 across the board is a good answer, not a failure.
    question = _question()
    response = _full_success_chain_response(answer="The evidence is here.")

    verdict = attribute_question(
        question,
        response,
        _scorecard(
            answer_correctness=0.9,
            faithfulness=0.9,
            answer_completeness=0.9,
            answer_relevancy=0.9,
        ),
    )

    assert verdict.primary_failure_stage == "correct"
    assert "generation_drift" not in verdict.failure_labels


def test_scores_exactly_at_the_threshold_pass():
    # Guards the comparison direction: >= threshold passes, matching
    # calibration.py's `judged >= 0.5` convention. Flipping this to `>` would
    # silently reclassify every borderline answer as a generation failure.
    question = _question()
    response = _full_success_chain_response(answer="The evidence is here.")

    verdict = attribute_question(
        question, response, _scorecard(answer_correctness=0.5, faithfulness=0.5)
    )

    assert verdict.primary_failure_stage == "correct"
    assert "generation_drift" not in verdict.failure_labels


def test_context_truncated_is_unassessable_without_context_assembly_trace():
    question = _question()
    response = _full_success_chain_response(answer="The evidence is here.")

    verdict = attribute_question(question, response, _scorecard(answer_correctness=1.0))

    context_evidence = verdict.stage_evidence["context_truncated"]
    assert context_evidence["assessable"] is False
    assert context_evidence["supported"] is False
    assert "context_assembly" in context_evidence["reason"]
    assert "not measured" in context_evidence["reason"]
    # The gate must not silently block generation from being judged "correct" —
    # the whole point is that it stays a visible unassessable gap, not a proxy
    # for pass/fail.
    assert verdict.primary_failure_stage == "correct"


def test_context_truncated_fires_only_from_a_distinct_context_assembly_trace():
    question = _question()
    response = EvalResponse(
        question_id="q1",
        answer="",
        metrics=QueryMetrics(
            latency_ms=1.0,
            stages=[
                _trace("bm25", "gold"),
                _trace("vector", "gold"),
                _trace("fusion", "gold"),
                _trace("rerank", "gold"),
                _trace("context_assembly", "other-truncated"),
            ],
        ),
    )

    verdict = attribute_question(question, response, _scorecard(answer_correctness=0.0))

    assert verdict.primary_failure_stage == "context_truncated"
    assert verdict.failure_labels == ["context_truncated"]
    assert verdict.stage_evidence["context_truncated"]["assessable"] is True


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


def test_context_truncated_is_unassessable_when_the_trace_mirrors_rerank():
    # The engine returns _aget_nodes()'s output straight out of _run_c3, so a
    # context_assembly trace identical to rerank is not a measurement of the
    # packed context. The label must say so rather than read as assessable.
    question = _question()
    response = _full_success_chain_response(answer="The evidence is here.")
    rerank = next(stage for stage in response.metrics.stages if stage.name == "rerank")
    response.metrics.stages.append(
        StageTrace(
            name="context_assembly",
            duration_ms=1,
            item_count=rerank.item_count,
            items=list(rerank.items),
        )
    )

    verdict = attribute_question(question, response, _scorecard(answer_correctness=1.0))

    context_evidence = verdict.stage_evidence["context_truncated"]
    assert context_evidence["assessable"] is False
    assert "no distinct context_assembly measurement" in context_evidence["reason"]
    assert "context_truncated" not in verdict.failure_labels
