"""Per-question sample persistence for evaluation runs.

The run JSON holds aggregates only. Anything that needs the individual
question/answer pairs after the fact — the human-review exports, spot-checking a
regression, re-judging without re-querying — needs the samples too, so the runner
writes them to a sidecar file next to the run.

Sidecar rather than inline: run files are read on every dashboard request and
indexed wholesale at startup, and a few hundred answers with their retrieved
chunks dwarf the metrics they accompany.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from evals.schemas import (
    Citation,
    Difficulty,
    EvalQuestion,
    EvalResponse,
    GoldPassage,
    QueryMetrics,
    QueryType,
    RetrievedChunk,
    TokenUsage,
)

logger = logging.getLogger(__name__)

SAMPLES_SUFFIX = "_samples.json"

# Retrieved chunk text is stored truncated: full text multiplies file size by the
# retrieval depth and reviewers work from the head of a passage anyway.
MAX_CHUNK_TEXT = 2000


def samples_path_for(run_path: Path) -> Path:
    """Sidecar path for a given run file."""
    return run_path.with_name(run_path.stem + SAMPLES_SUFFIX)


def _question_to_dict(q: EvalQuestion) -> dict[str, Any]:
    return {
        "id": q.id,
        "question": q.question,
        "expected_answer": q.expected_answer,
        "query_type": q.query_type.value,
        "difficulty": q.difficulty.value,
        "domain": q.domain,
        "is_unanswerable": q.is_unanswerable,
        "metadata": q.metadata,
        "gold_passages": [
            {
                "doc_id": p.doc_id,
                "chunk_id": p.chunk_id,
                "text": p.text[:MAX_CHUNK_TEXT],
                "relevance_score": p.relevance_score,
            }
            for p in q.gold_passages
        ],
    }


def _response_to_dict(r: EvalResponse) -> dict[str, Any]:
    return {
        "question_id": r.question_id,
        "answer": r.answer,
        "session_id": r.session_id,
        "latency_ms": r.metrics.latency_ms if r.metrics else None,
        "token_usage": (
            {
                "prompt_tokens": r.metrics.token_usage.prompt_tokens,
                "completion_tokens": r.metrics.token_usage.completion_tokens,
                "total_tokens": r.metrics.token_usage.total_tokens,
            }
            if r.metrics and r.metrics.token_usage
            else None
        ),
        "citations": [
            {
                "source_index": c.source_index,
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "text_span": c.text_span,
            }
            for c in r.citations
        ],
        "retrieved_chunks": [
            {
                "doc_id": c.doc_id,
                "chunk_id": c.chunk_id,
                "text": c.text[:MAX_CHUNK_TEXT],
                "score": c.score,
                "rank": c.rank,
            }
            for c in r.retrieved_chunks
        ],
    }


def save_samples(
    run_path: Path,
    run_id: str,
    questions: list[EvalQuestion],
    responses: list[EvalResponse],
) -> Path:
    """Write the per-question sidecar for a run. Returns the path written."""
    path = samples_path_for(run_path)
    payload = {
        "run_id": run_id,
        "count": len(questions),
        "samples": [
            {"question": _question_to_dict(q), "response": _response_to_dict(r)}
            for q, r in zip(questions, responses)
        ],
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    logger.info(f"[EVAL] Saved {len(questions)} samples to {path}")
    return path


def _question_from_dict(d: dict[str, Any]) -> EvalQuestion:
    return EvalQuestion(
        id=d["id"],
        question=d["question"],
        expected_answer=d.get("expected_answer"),
        gold_passages=[
            GoldPassage(
                doc_id=p["doc_id"],
                chunk_id=p["chunk_id"],
                text=p.get("text", ""),
                relevance_score=p.get("relevance_score", 1.0),
            )
            for p in d.get("gold_passages", [])
        ],
        query_type=QueryType(d.get("query_type", "factoid")),
        difficulty=Difficulty(d.get("difficulty", "medium")),
        domain=d.get("domain", "unknown"),
        is_unanswerable=d.get("is_unanswerable", False),
        metadata=d.get("metadata", {}),
    )


def _response_from_dict(d: dict[str, Any]) -> EvalResponse:
    usage = d.get("token_usage")
    metrics = QueryMetrics(
        latency_ms=d.get("latency_ms") or 0.0,
        token_usage=(
            TokenUsage(
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )
            if usage
            else None
        ),
    )
    return EvalResponse(
        question_id=d["question_id"],
        answer=d.get("answer", ""),
        retrieved_chunks=[
            RetrievedChunk(
                doc_id=c.get("doc_id", ""),
                chunk_id=c.get("chunk_id", ""),
                text=c.get("text", ""),
                score=c.get("score"),
                rank=c.get("rank"),
            )
            for c in d.get("retrieved_chunks", [])
        ],
        citations=[
            Citation(
                source_index=c.get("source_index", 0),
                doc_id=c.get("doc_id"),
                chunk_id=c.get("chunk_id"),
                chunk_index=c.get("chunk_index"),
                text_span=c.get("text_span"),
            )
            for c in d.get("citations", [])
        ],
        session_id=d.get("session_id"),
        metrics=metrics,
    )


def load_samples(run_path: Path) -> tuple[list[EvalQuestion], list[EvalResponse]]:
    """Load a run's samples sidecar. Returns ([], []) when there isn't one."""
    path = samples_path_for(run_path)
    if not path.exists():
        return ([], [])

    data = json.loads(path.read_text())
    questions: list[EvalQuestion] = []
    responses: list[EvalResponse] = []
    for sample in data.get("samples", []):
        questions.append(_question_from_dict(sample["question"]))
        responses.append(_response_from_dict(sample["response"]))
    return (questions, responses)
