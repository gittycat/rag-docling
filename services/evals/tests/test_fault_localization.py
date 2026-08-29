"""Phase 4's real acceptance criterion: the two faults must move DIFFERENT metrics.

    Configure a deliberately bad reranker; rerank_demotions must rise while
    candidate_recall_ceiling stays flat. Then degrade the embedder; the ceiling
    must drop while rerank behaviour holds. If both faults move the same
    metrics, the attribution does not work yet.

This could not pass before the qrels fix. The relevant-set used to be derived
from the ranking being scored, so a retrieval miss produced an empty qrels set
and candidate_recall_ceiling returned None — it was structurally incapable of
FALLING when the embedder degraded. It can only be written now because the
relevant-set comes from the chunk catalog.
"""

import pytest

import hashlib
import re

from evals.metrics.retrieval import CandidateRecallCeiling, RecallAtK, RerankDemotions
from evals.schemas import (
    EvalQuestion,
    EvalResponse,
    EvidenceLocator,
    QueryMetrics,
    RetrievedChunk,
    StageItem,
    StageTrace,
)

GOLD = "doc-chunk-3"
DISTRACTORS = ["doc-chunk-0", "doc-chunk-1", "doc-chunk-2", "doc-chunk-4"]
DOCUMENT_HASH = "a" * 64
EVIDENCE_TEXT = "the required evidence"

# Ground truth is a SOURCE COORDINATE, not a chunk id. That is the path whose
# relevant-set used to be derived from the ranking being scored, and therefore
# the path on which candidate_recall_ceiling was structurally incapable of
# falling: a total miss produced an empty qrels set and returned None.
CHUNK_SPANS = {
    "doc-chunk-0": (0, 100),
    "doc-chunk-1": (100, 200),
    "doc-chunk-2": (200, 300),
    GOLD: (300, 400),
    "doc-chunk-4": (400, 500),
}
EVIDENCE_SPAN = (320, 360)


def _normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def _question():
    normalized = _normalize(EVIDENCE_TEXT)
    return EvalQuestion(
        id="q1",
        question="where is the evidence?",
        expected_answer="there",
        evidence=[
            EvidenceLocator(
                document_hash=DOCUMENT_HASH,
                source_format="txt",
                locator={
                    "element_path": "document",
                    "start_char": EVIDENCE_SPAN[0],
                    "end_char": EVIDENCE_SPAN[1],
                },
                normalized_text=normalized,
                normalized_text_hash=hashlib.sha256(normalized.encode()).hexdigest(),
            )
        ],
    )


def _chunk(chunk_id):
    start, end = CHUNK_SPANS[chunk_id]
    body = f"lead {EVIDENCE_TEXT} trail" if chunk_id == GOLD else "filler content"
    normalized = _normalize(body)
    return RetrievedChunk(
        doc_id="doc",
        chunk_id=chunk_id,
        text="",
        metadata={
            "file_hash": DOCUMENT_HASH,
            "source_locator": {
                "document_hash": DOCUMENT_HASH,
                "source_format": "txt",
                "locator": {
                    "element_path": "document",
                    "start_char": start,
                    "end_char": end,
                },
                "normalized_text": normalized,
                "normalized_text_hash": hashlib.sha256(normalized.encode()).hexdigest(),
            },
        },
    )


def _catalog():
    """The corpus as it actually exists. The evidence-bearing chunk is present
    regardless of whether any retrieval leg managed to find it — that is what
    lets a miss score 0.0 instead of vanishing from the average."""
    return [_chunk(cid) for cid in [*DISTRACTORS, GOLD]]


def _stage(name, chunk_ids):
    return StageTrace(
        name=name,
        duration_ms=1,
        item_count=len(chunk_ids),
        items=[
            StageItem(
                chunk_id=cid,
                doc_id="doc",
                rank=i + 1,
                metadata=dict(_chunk(cid).metadata),
            )
            for i, cid in enumerate(chunk_ids)
        ],
    )


def _response(*, candidates, reranked):
    return EvalResponse(
        question_id="q1",
        answer="",
        retrieved_chunks=[_chunk(cid) for cid in reranked],
        metrics=QueryMetrics(
            latency_ms=1,
            stages=[
                _stage("bm25", candidates),
                _stage("vector", candidates),
                _stage("fusion", candidates),
                _stage("rerank", reranked),
            ],
        ),
    )


def _measure(response):
    question, catalog = _question(), _catalog()
    return {
        "ceiling": CandidateRecallCeiling(10).compute(
            question, response, chunk_catalog=catalog
        ).value,
        "demotions": RerankDemotions(3).compute(
            question, response, chunk_catalog=catalog
        ).value,
        "recall": RecallAtK(3).compute(question, response, chunk_catalog=catalog).value,
    }


# A healthy run: the candidate list contains the gold, and the reranker keeps it
# in the final top-3.
HEALTHY_CANDIDATES = [GOLD, *DISTRACTORS]
HEALTHY_RERANKED = [GOLD, DISTRACTORS[0], DISTRACTORS[1]]

# Fault 1 — a deliberately bad reranker: the same candidate list, but the gold
# is demoted out of the final top-3.
BAD_RERANK_RERANKED = [DISTRACTORS[0], DISTRACTORS[1], DISTRACTORS[2], GOLD]

# Fault 2 — a degraded embedder: the gold never makes the candidate list at all.
# The reranker is untouched and behaves exactly as it did when healthy.
DEGRADED_CANDIDATES = DISTRACTORS
DEGRADED_RERANKED = DISTRACTORS[:3]


@pytest.fixture
def baseline():
    return _measure(_response(candidates=HEALTHY_CANDIDATES, reranked=HEALTHY_RERANKED))


def test_the_baseline_is_healthy(baseline):
    assert baseline["ceiling"] == 1.0
    assert baseline["demotions"] == 0.0
    assert baseline["recall"] == 1.0


def test_a_bad_reranker_raises_demotions_and_leaves_the_ceiling_flat(baseline):
    faulted = _measure(
        _response(candidates=HEALTHY_CANDIDATES, reranked=BAD_RERANK_RERANKED)
    )

    assert faulted["demotions"] > baseline["demotions"]
    assert faulted["ceiling"] == baseline["ceiling"] == 1.0
    # The fault is real and visible downstream.
    assert faulted["recall"] < baseline["recall"]


def test_a_degraded_embedder_drops_the_ceiling_and_leaves_rerank_behaviour_flat(baseline):
    faulted = _measure(
        _response(candidates=DEGRADED_CANDIDATES, reranked=DEGRADED_RERANKED)
    )

    # The ceiling FALLS. Before the qrels fix this was None, because the
    # relevant-set was derived from the ranking being scored: a total miss
    # produced an empty denominator and read as unassessable, not as 0.0.
    assert faulted["ceiling"] is not None, "ceiling must be defined on a miss, not None"
    assert faulted["ceiling"] < baseline["ceiling"]
    assert faulted["ceiling"] == 0.0

    # The reranker did nothing wrong: it cannot demote what it never received.
    assert faulted["demotions"] == baseline["demotions"] == 0.0


def test_the_two_faults_move_different_metrics():
    # The criterion itself: if both faults moved the same metrics, the
    # attribution would not localize anything.
    baseline = _measure(_response(candidates=HEALTHY_CANDIDATES, reranked=HEALTHY_RERANKED))
    bad_rerank = _measure(_response(candidates=HEALTHY_CANDIDATES, reranked=BAD_RERANK_RERANKED))
    bad_embed = _measure(_response(candidates=DEGRADED_CANDIDATES, reranked=DEGRADED_RERANKED))

    ceiling_moved_by = {
        "bad_rerank": bad_rerank["ceiling"] != baseline["ceiling"],
        "bad_embedder": bad_embed["ceiling"] != baseline["ceiling"],
    }
    demotions_moved_by = {
        "bad_rerank": bad_rerank["demotions"] != baseline["demotions"],
        "bad_embedder": bad_embed["demotions"] != baseline["demotions"],
    }

    assert ceiling_moved_by == {"bad_rerank": False, "bad_embedder": True}
    assert demotions_moved_by == {"bad_rerank": True, "bad_embedder": False}
