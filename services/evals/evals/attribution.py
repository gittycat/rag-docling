"""Deterministic, per-question failure attribution from recorded stage outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evals.evidence import derive_relevant_chunk_ids
from evals.metrics.abstention import is_abstention
from evals.metrics.text_match import match_retrieved_to_gold
from evals.schemas import EvalQuestion, EvalResponse, RetrievedChunk, StageTrace


FAILURE_STAGES = (
    "retrieval_miss",
    "fusion_miss",
    "rerank_drop",
    "context_truncated",
    "generation_drift",
    "citation_error",
    "wrong_abstention",
    "missed_abstention",
    "correct",
)


@dataclass(frozen=True)
class FailureAttribution:
    """Causally ordered verdict and the evidence used to make it."""

    question_id: str
    primary_failure_stage: str | None
    failure_labels: list[str] = field(default_factory=list)
    stage_evidence: dict[str, dict[str, Any]] = field(default_factory=dict)


def _metric_values(scorecard: Any, question_id: str) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for metric in scorecard.metrics:
        per_question = metric.details.get("per_question", {})
        if question_id in per_question:
            values[metric.name] = per_question[question_id]
    return values


def _stage(response: EvalResponse, name: str) -> StageTrace | None:
    if response.metrics is None:
        return None
    return next((trace for trace in response.metrics.stages if trace.name == name), None)


def _chunks(trace: StageTrace | None) -> list[RetrievedChunk] | None:
    # A degraded retrieval leg may have an empty partial list because an external
    # dependency failed. That is operationally useful evidence, but not proof
    # that the corpus lacked the answer, so it cannot support a semantic miss.
    if trace is None or trace.items is None or trace.status != "ok":
        return None
    return [
        RetrievedChunk(
            doc_id=item.doc_id,
            chunk_id=item.chunk_id,
            text="",
            score=item.score,
            rank=item.rank,
            metadata=dict(item.metadata),
        )
        for item in trace.items
    ]


def _relevant_ids(
    question: EvalQuestion, chunks: list[RetrievedChunk]
) -> tuple[set[str] | None, str | None]:
    """Resolve relevant items without judging or inventing text-stage matches."""
    if question.evidence:
        resolution = derive_relevant_chunk_ids(question.evidence, chunks)
        if resolution.lineage_failure:
            return None, resolution.lineage_failure
        return resolution.chunk_ids, None

    chunk_ids = {passage.chunk_id for passage in question.gold_passages if passage.chunk_id}
    if chunk_ids:
        return chunk_ids, None
    return None, "Gold evidence has no stable chunk ids for stage attribution"


def _stage_evidence(
    question: EvalQuestion, response: EvalResponse, stage_name: str
) -> tuple[bool | None, dict[str, Any]]:
    trace = _stage(response, stage_name)
    if trace is None:
        return None, {"assessable": False, "reason": f"{stage_name} trace was not emitted"}
    chunks = _chunks(trace)
    if chunks is None:
        return None, {
            "assessable": False,
            "status": trace.status,
            "error": trace.error,
            "reason": f"{stage_name} did not emit a usable ranking",
        }
    relevant_ids, failure = _relevant_ids(question, chunks)
    if relevant_ids is None:
        return None, {"assessable": False, "reason": failure}
    hits = sorted({chunk.chunk_id for chunk in chunks} & relevant_ids)
    return bool(hits), {
        "assessable": True,
        "status": trace.status,
        "item_count": trace.item_count,
        "relevant_chunk_ids": hits,
        "relevant_count": len(hits),
    }


def _final_evidence(question: EvalQuestion, response: EvalResponse) -> tuple[bool | None, dict[str, Any]]:
    """Whether the context actually supplied to generation still contains evidence."""
    if not response.retrieved_chunks:
        return False, {"assessable": True, "item_count": 0, "relevant_chunk_ids": []}
    if question.evidence:
        resolution = derive_relevant_chunk_ids(question.evidence, response.retrieved_chunks)
        if resolution.lineage_failure:
            return None, {"assessable": False, "reason": resolution.lineage_failure}
        hits = sorted(resolution.chunk_ids)
    else:
        chunk_ids = {passage.chunk_id for passage in question.gold_passages if passage.chunk_id}
        if chunk_ids:
            hits = sorted(response.retrieved_chunk_ids & chunk_ids)
        else:
            matched = match_retrieved_to_gold(response.retrieved_chunks, question.gold_passages)
            hits = sorted(response.retrieved_chunks[index].chunk_id for index in matched)
    return bool(hits), {
        "assessable": True,
        "item_count": len(response.retrieved_chunks),
        "relevant_chunk_ids": hits,
        "relevant_count": len(hits),
    }


def _record(
    evidence: dict[str, dict[str, Any]], label: str, supported: bool, **details: Any
) -> None:
    evidence[label] = {"supported": supported, **details}


def attribute_question(
    question: EvalQuestion, response: EvalResponse, scorecard: Any
) -> FailureAttribution:
    """Attribute one result using only outputs that the evaluation already recorded.

    A label is only considered after every prerequisite stage has supplied the
    evidence it needs. In particular, no generation or citation label is emitted
    after an upstream evidence miss; those outcomes are unassessable, not failures.
    """
    evidence: dict[str, dict[str, Any]] = {}
    metrics = _metric_values(scorecard, question.id)
    did_abstain = is_abstention(response.answer)

    if question.is_unanswerable:
        missed = not did_abstain
        _record(
            evidence,
            "missed_abstention",
            missed,
            assessable=True,
            did_abstain=did_abstain,
        )
        if missed:
            return FailureAttribution(question.id, "missed_abstention", ["missed_abstention"], evidence)
        _record(evidence, "correct", True, assessable=True, reason="Correctly abstained")
        return FailureAttribution(question.id, "correct", ["correct"], evidence)

    bm25, bm25_evidence = _stage_evidence(question, response, "bm25")
    vector, vector_evidence = _stage_evidence(question, response, "vector")
    fusion, fusion_evidence = _stage_evidence(question, response, "fusion")
    rerank, rerank_evidence = _stage_evidence(question, response, "rerank")
    final, final_evidence = _final_evidence(question, response)

    retrieval_assessable = bm25 is not None and vector is not None
    retrieval_miss = retrieval_assessable and not bm25 and not vector
    _record(
        evidence,
        "retrieval_miss",
        retrieval_miss,
        assessable=retrieval_assessable,
        bm25=bm25_evidence,
        vector=vector_evidence,
    )
    if retrieval_miss:
        _record(evidence, "generation_drift", False, assessable=False, reason="retrieval_miss")
        _record(evidence, "citation_error", False, assessable=False, reason="retrieval_miss")
        return FailureAttribution(question.id, "retrieval_miss", ["retrieval_miss"], evidence)

    fusion_assessable = fusion is not None and (bm25 is True or vector is True)
    fusion_miss = fusion_assessable and not fusion
    _record(
        evidence,
        "fusion_miss",
        fusion_miss,
        assessable=fusion_assessable,
        fusion=fusion_evidence,
    )
    if fusion_miss:
        _record(evidence, "generation_drift", False, assessable=False, reason="fusion_miss")
        _record(evidence, "citation_error", False, assessable=False, reason="fusion_miss")
        return FailureAttribution(question.id, "fusion_miss", ["fusion_miss"], evidence)

    rerank_assessable = rerank is not None and fusion is True
    rerank_drop = rerank_assessable and not rerank
    _record(
        evidence,
        "rerank_drop",
        rerank_drop,
        assessable=rerank_assessable,
        rerank=rerank_evidence,
    )
    if rerank_drop:
        _record(evidence, "generation_drift", False, assessable=False, reason="rerank_drop")
        _record(evidence, "citation_error", False, assessable=False, reason="rerank_drop")
        return FailureAttribution(question.id, "rerank_drop", ["rerank_drop"], evidence)

    context_assessable = rerank is True and final is not None
    context_truncated = context_assessable and not final
    _record(
        evidence,
        "context_truncated",
        context_truncated,
        assessable=context_assessable,
        rerank=rerank_evidence,
        final_context=final_evidence,
    )
    if context_truncated:
        _record(evidence, "generation_drift", False, assessable=False, reason="context_truncated")
        _record(evidence, "citation_error", False, assessable=False, reason="context_truncated")
        return FailureAttribution(question.id, "context_truncated", ["context_truncated"], evidence)

    wrong_abstention = final is True and did_abstain
    _record(
        evidence,
        "wrong_abstention",
        wrong_abstention,
        assessable=final is True,
        did_abstain=did_abstain,
        final_context=final_evidence,
    )
    if wrong_abstention:
        return FailureAttribution(question.id, "wrong_abstention", ["wrong_abstention"], evidence)

    correctness = metrics.get("answer_correctness")
    generation_assessable = final is True and correctness is not None
    generation_drift = generation_assessable and correctness < 1.0
    _record(
        evidence,
        "generation_drift",
        generation_drift,
        assessable=generation_assessable,
        answer_correctness=correctness,
        final_context=final_evidence,
    )
    if generation_drift:
        _record(evidence, "citation_error", False, assessable=False, reason="generation_drift")
        return FailureAttribution(question.id, "generation_drift", ["generation_drift"], evidence)

    citation_names = ("citation_precision", "citation_recall", "citation_entailment", "claim_citation_support")
    citation_values = {name: metrics[name] for name in citation_names if metrics.get(name) is not None}
    citation_assessable = generation_assessable and bool(citation_values)
    citation_error = citation_assessable and any(value < 1.0 for value in citation_values.values())
    _record(
        evidence,
        "citation_error",
        citation_error,
        assessable=citation_assessable,
        metrics=citation_values,
    )
    if citation_error:
        return FailureAttribution(question.id, "citation_error", ["citation_error"], evidence)

    correct = generation_assessable and correctness == 1.0
    _record(evidence, "correct", correct, assessable=generation_assessable)
    return FailureAttribution(question.id, "correct" if correct else None, ["correct"] if correct else [], evidence)


def attribute_questions(
    questions: list[EvalQuestion], responses: list[EvalResponse], scorecard: Any
) -> list[FailureAttribution]:
    """Attribute aligned question/response pairs."""
    return [attribute_question(question, response, scorecard) for question, response in zip(questions, responses)]
