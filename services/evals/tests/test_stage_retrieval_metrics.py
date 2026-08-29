"""Judge-free regression tests for retrieval-stage attribution."""

import hashlib

import pytest

from evals.metrics.retrieval import (
    CandidateRecallCeiling,
    EvidenceContainment,
    EvidenceFragmentation,
    EvidenceSetRecall,
    FusionLift,
    NDCG,
    OrphanedEvidenceRate,
    RecallAtK,
    RerankDemotions,
    RerankPromotions,
)
from evals.schemas import (
    EvalQuestion,
    EvalResponse,
    EvidenceLocator,
    GoldPassage,
    QueryMetrics,
    RetrievedChunk,
    StageItem,
    StageTrace,
)
from evals.config import EvalConfig, EvalTier, JudgeConfig


def _question() -> EvalQuestion:
    return EvalQuestion(
        id="q1",
        question="Where is the evidence?",
        expected_answer="answer",
        gold_passages=[GoldPassage(doc_id="doc", chunk_id="gold", text="gold evidence")],
    )


def _stage_catalog() -> list[RetrievedChunk]:
    """The current chunk catalog the stage fixtures resolve their gold against.

    Both ids must be present even when a leg retrieves neither: the relevant-set
    comes from the catalog, so a leg that missed scores 0.0 instead of dropping
    out of the average as unassessable.
    """
    return [
        RetrievedChunk(doc_id="doc", chunk_id="gold", text="gold evidence"),
        RetrievedChunk(doc_id="doc", chunk_id="miss", text="miss"),
    ]


def _stage(name: str, *chunk_ids: str) -> StageTrace:
    return StageTrace(
        name=name,
        duration_ms=1,
        item_count=len(chunk_ids),
        items=[StageItem(chunk_id=chunk_id, doc_id="doc", rank=index + 1) for index, chunk_id in enumerate(chunk_ids)],
    )


@pytest.mark.asyncio
async def test_per_leg_scores_stay_in_one_headline_metric_row() -> None:
    response = EvalResponse(
        question_id="q1",
        answer="",
        retrieved_chunks=[RetrievedChunk(doc_id="doc", chunk_id="gold", text="gold evidence")],
        metrics=QueryMetrics(
            latency_ms=1,
            stages=[
                _stage("bm25", "miss", "gold"),
                _stage("vector", "gold"),
                _stage("fusion", "gold"),
                _stage("rerank", "gold"),
            ],
        ),
    )

    result = await RecallAtK(1).compute_batch(
        [_question()], [response], chunk_catalog=_stage_catalog()
    )

    assert result.name == "recall_at_1"
    assert result.details["stage_scores"] == {
        "recall_at_1{leg=bm25}": 0.0,
        "recall_at_1{leg=vector}": 1.0,
        "recall_at_1{leg=fusion}": 1.0,
        "recall_at_1{leg=rerank}": 1.0,
    }


def test_bad_reranker_has_demotions_without_lowering_candidate_ceiling() -> None:
    response = EvalResponse(
        question_id="q1",
        answer="",
        retrieved_chunks=[RetrievedChunk(doc_id="doc", chunk_id="miss", text="miss")],
        metrics=QueryMetrics(
            latency_ms=1,
            stages=[
                _stage("bm25", "gold", "miss"),
                _stage("vector", "gold", "miss"),
                _stage("fusion", "gold", "miss"),
                _stage("rerank", "miss", "gold"),
            ],
        ),
    )

    assert CandidateRecallCeiling(1).compute(_question(), response, chunk_catalog=_stage_catalog()).value == 1.0
    assert RerankPromotions(1).compute(_question(), response, chunk_catalog=_stage_catalog()).value == 0.0
    assert RerankDemotions(1).compute(_question(), response, chunk_catalog=_stage_catalog()).value == 1.0


def test_fusion_lift_compares_fusion_to_better_leg() -> None:
    response = EvalResponse(
        question_id="q1",
        answer="",
        metrics=QueryMetrics(
            latency_ms=1,
            stages=[
                _stage("bm25", "miss", "gold"),
                _stage("vector", "gold", "miss"),
                _stage("fusion", "miss", "gold"),
            ],
        ),
    )

    assert FusionLift().compute(_question(), response, chunk_catalog=_stage_catalog()).value < 0.0


def _evidence() -> EvidenceLocator:
    text = "required evidence"
    return EvidenceLocator(
        document_hash="a" * 64,
        source_format="txt",
        locator={"element_path": "document", "start_char": 10, "end_char": 20},
        normalized_text=text,
        normalized_text_hash=hashlib.sha256(text.encode()).hexdigest(),
        evidence_set_id="both",
    )


def _chunk(chunk_id: str, start: int, end: int) -> RetrievedChunk:
    return RetrievedChunk(
        doc_id="doc",
        chunk_id=chunk_id,
        text="",
        metadata={
            "file_hash": "a" * 64,
            "source_locator": {
                "document_hash": "a" * 64,
                "source_format": "txt",
                "locator": {"element_path": "document", "start_char": start, "end_char": end},
            },
        },
    )


def test_chunking_metrics_measure_containment_fragmentation_and_orphans() -> None:
    question = EvalQuestion(id="q1", question="q", expected_answer="a", evidence=[_evidence()])
    response = EvalResponse(question_id="q1", answer="")

    contained = [_chunk("whole", 0, 30)]
    split = [_chunk("left", 0, 15), _chunk("right", 15, 30)]
    orphaned = [_chunk("elsewhere", 30, 40)]

    assert EvidenceContainment().compute(question, response, chunks=contained).value == 1.0
    assert EvidenceFragmentation().compute(question, response, chunks=split).value == 2.0
    assert OrphanedEvidenceRate().compute(question, response, chunks=orphaned).value == 1.0


def test_evidence_set_recall_requires_every_locator_in_the_set() -> None:
    second = _evidence()
    second.locator["start_char"] = 30
    second.locator["end_char"] = 40
    question = EvalQuestion(id="q1", question="q", expected_answer="a", evidence=[_evidence(), second])
    response = EvalResponse(question_id="q1", answer="", retrieved_chunks=[_chunk("first", 0, 25)])

    assert EvidenceSetRecall().compute(question, response).value == 0.0


def test_ir_measures_parity_fixture_for_binary_ndcg() -> None:
    question = _question()
    response = EvalResponse(
        question_id="q1",
        answer="",
        retrieved_chunks=[
            RetrievedChunk(doc_id="doc", chunk_id="miss", text="miss"),
            RetrievedChunk(doc_id="doc", chunk_id="gold", text="gold evidence"),
        ],
    )
    # The retired implementation's binary DCG formula: 1 / log2(rank + 1).
    old_value = 1 / 1.584962500721156
    assert NDCG(2).compute(question, response, chunk_catalog=_stage_catalog()).value == pytest.approx(old_value)


def test_retrieval_only_mode_validates_its_stage_and_tier() -> None:
    config = EvalConfig(
        datasets=[],
        tier=EvalTier.END_TO_END,
        retrieval_only=True,
        retrieval_source="fusion",
        judge=JudgeConfig(provider="test", model="test", enabled=False),
    )
    assert config.retrieval_only is True
    with pytest.raises(ValueError, match="end_to_end"):
        EvalConfig(
            datasets=[], tier=EvalTier.GENERATION, retrieval_only=True,
            judge=JudgeConfig(provider="test", model="test", enabled=False),
        )
