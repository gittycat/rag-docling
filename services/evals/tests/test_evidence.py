"""Source-coordinate evidence must survive a re-chunk and fail closed on gaps."""

import hashlib

from evals.evidence import derive_relevant_chunk_ids
from evals.metrics.retrieval import RecallAtK
from evals.schemas import EvalQuestion, EvalResponse, EvidenceLocator, RetrievedChunk


DOCUMENT_HASH = "a" * 64


def _evidence(start: int = 500, end: int = 620) -> EvidenceLocator:
    text = "the required evidence"
    return EvidenceLocator(
        document_hash=DOCUMENT_HASH,
        source_format="txt",
        locator={"element_path": "document", "start_char": start, "end_char": end},
        normalized_text=text,
        normalized_text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _chunk(chunk_id: str, start: int, end: int, *, locator: bool = True) -> RetrievedChunk:
    metadata = {"file_hash": DOCUMENT_HASH}
    if locator:
        metadata["source_locator"] = {
            "document_hash": DOCUMENT_HASH,
            "source_format": "txt",
            "locator": {"element_path": "document", "start_char": start, "end_char": end},
            "normalized_text": "chunk text",
            "normalized_text_hash": hashlib.sha256(b"chunk text").hexdigest(),
        }
    return RetrievedChunk(doc_id="doc", chunk_id=chunk_id, text="chunk text", metadata=metadata)


def test_evidence_locator_resolves_after_rechunking() -> None:
    evidence = [_evidence()]
    small_chunks = [_chunk("small-1", 0, 550), _chunk("small-2", 500, 1000)]
    large_chunks = [_chunk("large-1", 0, 1000)]

    assert derive_relevant_chunk_ids(evidence, small_chunks).chunk_ids == {"small-1", "small-2"}
    assert derive_relevant_chunk_ids(evidence, large_chunks).chunk_ids == {"large-1"}


def test_missing_chunk_lineage_returns_none_instead_of_fuzzy_match() -> None:
    question = EvalQuestion(
        id="q1",
        question="What is required?",
        expected_answer="evidence",
        evidence=[_evidence()],
    )
    response = EvalResponse(
        question_id="q1",
        answer="",
        retrieved_chunks=[_chunk("legacy-chunk", 0, 1000, locator=False)],
    )

    result = RecallAtK(5).compute(question, response)

    assert result.value is None
    assert result.details["lineage_failure"] == "chunk legacy-chunk has no source_locator"


def test_docling_pdf_regions_resolve_by_page_and_bbox() -> None:
    text = "table cell"
    evidence = EvidenceLocator(
        document_hash=DOCUMENT_HASH,
        source_format="pdf",
        locator={"page": 1, "bbox": [20, 20, 30, 30]},
        normalized_text=text,
        normalized_text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    chunk = _chunk("pdf-1", 0, 1)
    chunk.metadata["source_locator"] = {
        "document_hash": DOCUMENT_HASH,
        "source_format": "pdf",
        "locator": {"regions": [{"element_id": "#/texts/4", "page": 1, "bbox": [0, 0, 25, 25]}]},
        "normalized_text": text,
        "normalized_text_hash": hashlib.sha256(text.encode()).hexdigest(),
    }

    assert derive_relevant_chunk_ids([evidence], [chunk]).chunk_ids == {"pdf-1"}
