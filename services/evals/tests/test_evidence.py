"""Source-coordinate evidence must survive a re-chunk and fail closed on gaps."""

import hashlib

from evals.evidence import derive_relevant_chunk_ids
from evals.metrics.retrieval import EvidenceContainment, RecallAtK, _wholly_contained
from evals.schemas import EvalQuestion, EvalResponse, EvidenceLocator, RetrievedChunk


DOCUMENT_HASH = "a" * 64
EVIDENCE_TEXT = "the required evidence"


def _evidence(start: int = 500, end: int = 620, text: str = EVIDENCE_TEXT) -> EvidenceLocator:
    return EvidenceLocator(
        document_hash=DOCUMENT_HASH,
        source_format="txt",
        locator={"element_path": "document", "start_char": start, "end_char": end},
        normalized_text=text,
        normalized_text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _chunk(chunk_id: str, start: int, end: int, *, locator: bool = True, text: str | None = None) -> RetrievedChunk:
    # A real chunk's normalized_text_hash hashes the WHOLE node's content
    # (services/rag_server/pipelines/ingestion.py `_source_locator`), a strict
    # superset of any evidence span it resolves - not the evidence span
    # itself. Default to a realistic superset containing EVIDENCE_TEXT so the
    # secondary check (evidence._normalized_text_disagrees, containment not
    # equality) is exercised live on the happy path, not suppressed. Its hash
    # therefore legitimately differs from the evidence's own hash by
    # construction - that must still resolve as a match.
    if text is None:
        text = f"leading context. {EVIDENCE_TEXT} trailing context."
    metadata = {"file_hash": DOCUMENT_HASH}
    if locator:
        metadata["source_locator"] = {
            "document_hash": DOCUMENT_HASH,
            "source_format": "txt",
            "locator": {"element_path": "document", "start_char": start, "end_char": end},
            "normalized_text": text,
            "normalized_text_hash": hashlib.sha256(text.encode()).hexdigest(),
        }
    return RetrievedChunk(doc_id="doc", chunk_id=chunk_id, text=text, metadata=metadata)


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

    # The catalog is what the relevant-set resolves against, so the chunk
    # missing its lineage has to be in the catalog for the failure to surface.
    catalog = [_chunk("legacy-chunk", 0, 1000, locator=False)]
    result = RecallAtK(5).compute(question, response, chunk_catalog=catalog)

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


def _pdf_evidence(page: int, bbox: list[float], text: str = "evidence text") -> EvidenceLocator:
    return EvidenceLocator(
        document_hash=DOCUMENT_HASH,
        source_format="pdf",
        locator={"page": page, "bbox": bbox},
        normalized_text=text,
        normalized_text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _pdf_chunk(chunk_id: str, page: int, bbox: list[float], *, text: str | None = None) -> RetrievedChunk:
    # See _chunk: default to a realistic superset containing the standard
    # "evidence text" fixture value so the secondary check is exercised live.
    if text is None:
        text = "leading context. evidence text trailing context."
    return RetrievedChunk(
        doc_id="doc",
        chunk_id=chunk_id,
        text=text,
        metadata={
            "file_hash": DOCUMENT_HASH,
            "source_locator": {
                "document_hash": DOCUMENT_HASH,
                "source_format": "pdf",
                "locator": {"page": page, "bbox": bbox},
                "normalized_text": text,
                "normalized_text_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
        },
    )


def test_wholly_contained_requires_positive_pdf_coordinates() -> None:
    # R3: neither locator carries an element_id/block_id, so the old fallback
    # `locator.get("element_id") == evidence.locator.get("element_id")`
    # compared None == None and called it contained. A chunk from page 99
    # must never be reported as containing evidence anchored on page 1.
    evidence = _pdf_evidence(page=1, bbox=[20, 20, 30, 30])
    chunk = _pdf_chunk("far-chunk", page=99, bbox=[900, 900, 910, 910])

    assert _wholly_contained(evidence, chunk) is False


def test_wholly_contained_true_positive_same_page_containing_bbox() -> None:
    # Positive control: real bbox containment on the same page must still work.
    evidence = _pdf_evidence(page=1, bbox=[20, 20, 30, 30])
    chunk = _pdf_chunk("page1-chunk", page=1, bbox=[0, 0, 100, 100])

    assert _wholly_contained(evidence, chunk) is True


def test_evidence_containment_pdf_does_not_count_wrong_page_as_contained() -> None:
    # Two evidence spans: one genuinely on page 1 inside a page-1 chunk, one on
    # page 3 with no containing chunk anywhere. Under the old defect, ANY chunk
    # from the same document "contained" every evidence span (None == None), so
    # this fixture scored 1.0. It must not any more.
    contained_evidence = _pdf_evidence(page=1, bbox=[20, 20, 30, 30], text="contained")
    orphaned_evidence = _pdf_evidence(page=3, bbox=[20, 20, 30, 30], text="orphaned")
    question = EvalQuestion(
        id="q1", question="what?", expected_answer="x",
        evidence=[contained_evidence, orphaned_evidence],
    )
    page1_chunk = _pdf_chunk(
        "page1-chunk", page=1, bbox=[0, 0, 100, 100], text="leading. contained. trailing."
    )
    page7_chunk = _pdf_chunk("page7-chunk", page=7, bbox=[0, 0, 100, 100])
    response = EvalResponse(question_id="q1", answer="", retrieved_chunks=[page1_chunk, page7_chunk])

    result = EvidenceContainment().compute(question, response, chunks=[page1_chunk, page7_chunk])

    assert result.value == 0.5
    assert result.details["contained_evidence"] == 1
    assert result.details["evidence_count"] == 2


def _xlsx_evidence(cell_range: str, text: str = "cell content") -> EvidenceLocator:
    return EvidenceLocator(
        document_hash=DOCUMENT_HASH,
        source_format="xlsx",
        locator={"sheet": "Sheet1", "range": cell_range},
        normalized_text=text,
        normalized_text_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _xlsx_chunk(chunk_id: str, cell_range: str, *, text: str | None = None) -> RetrievedChunk:
    # See _chunk: default to a realistic superset of the standard evidence text
    # so the containment secondary check runs live rather than being suppressed.
    if text is None:
        text = "row header. cell content. row footer."
    return RetrievedChunk(
        doc_id="doc",
        chunk_id=chunk_id,
        text=text,
        metadata={
            "file_hash": DOCUMENT_HASH,
            "source_locator": {
                "document_hash": DOCUMENT_HASH,
                "source_format": "xlsx",
                "locator": {"sheet": "Sheet1", "range": cell_range},
                "normalized_text": text,
                "normalized_text_hash": hashlib.sha256(text.encode()).hexdigest(),
            },
        },
    )


def test_xlsx_range_locators_do_not_cross_match() -> None:
    # Old defect: _locators_overlap compared only row/col, so two range-only
    # locators (neither carrying row/col) satisfied None == None and matched.
    evidence = _xlsx_evidence("B2:D10")
    chunk = _xlsx_chunk("chunk-1", "F20:H30")

    result = derive_relevant_chunk_ids([evidence], [chunk])

    assert result.chunk_ids == set()
    assert result.lineage_failure is None


def test_xlsx_overlapping_ranges_match() -> None:
    # Positive control: genuinely overlapping ranges on the same sheet must
    # still resolve.
    evidence = _xlsx_evidence("B2:D10")
    chunk = _xlsx_chunk("chunk-1", "C5:E12")

    result = derive_relevant_chunk_ids([evidence], [chunk])

    assert result.chunk_ids == {"chunk-1"}


def test_xlsx_malformed_range_is_unusable_not_a_match() -> None:
    evidence = _xlsx_evidence("B2:D10")
    chunk = _xlsx_chunk("chunk-1", "not-a-range")

    result = derive_relevant_chunk_ids([evidence], [chunk])

    assert result.chunk_ids == set()
    assert result.lineage_failure == "chunk chunk-1 has unreconstructable source_locator"


def test_chunk_superset_text_with_different_hash_is_still_a_match() -> None:
    # A real chunk's normalized_text_hash is a hash of the WHOLE node content
    # (services/rag_server/pipelines/ingestion.py:58-73), not of the narrower
    # evidence span. So on any real corpus the chunk hash almost never equals
    # the evidence hash even for a perfectly legitimate match. The chunk's
    # normalized_text genuinely CONTAINS the evidence span here - that must be
    # a match, not a lineage_failure, even though the hashes disagree.
    evidence = _evidence()
    chunk_text = "leading context. " + evidence.normalized_text + " trailing context."
    chunk = RetrievedChunk(
        doc_id="doc", chunk_id="chunk-1", text=chunk_text,
        metadata={
            "file_hash": DOCUMENT_HASH,
            "source_locator": {
                "document_hash": DOCUMENT_HASH,
                "source_format": "txt",
                "locator": {"element_path": "document", "start_char": 0, "end_char": 1000},
                "normalized_text": chunk_text,
                "normalized_text_hash": hashlib.sha256(chunk_text.encode()).hexdigest(),
            },
        },
    )

    assert chunk.metadata["source_locator"]["normalized_text_hash"] != evidence.normalized_text_hash

    result = derive_relevant_chunk_ids([evidence], [chunk])

    assert result.chunk_ids == {"chunk-1"}
    assert result.lineage_failure is None


def test_coordinate_match_whose_text_lacks_the_evidence_is_lineage_failure() -> None:
    # Coordinates still overlap after a re-parse, but the chunk's recorded text
    # no longer carries the evidence span: that is the drift signal.
    evidence = _evidence()
    chunk = _chunk("chunk-1", 0, 1000, text="entirely different content here")

    result = derive_relevant_chunk_ids([evidence], [chunk])

    assert result.chunk_ids == set()
    assert result.lineage_failure is not None
    assert "normalized_text" in result.lineage_failure


def test_containing_chunk_resolves_even_though_its_hash_differs() -> None:
    # The regression this guards: a chunk's normalized_text_hash hashes the
    # whole node, so it differs from the evidence span's hash on every real
    # match. Hash inequality alone must never be treated as drift.
    evidence = _evidence()
    chunk = _chunk("chunk-1", 0, 1000, text=f"leading. {EVIDENCE_TEXT} trailing.")
    chunk_hash = chunk.metadata["source_locator"]["normalized_text_hash"]
    assert chunk_hash != evidence.normalized_text_hash

    result = derive_relevant_chunk_ids([evidence], [chunk])

    assert result.chunk_ids == {"chunk-1"}
    assert result.lineage_failure is None


def test_identical_text_resolves_via_the_hash_fast_path() -> None:
    evidence = _evidence()
    chunk = _chunk("chunk-1", 0, 1000, text=EVIDENCE_TEXT)
    assert chunk.metadata["source_locator"]["normalized_text_hash"] == evidence.normalized_text_hash

    result = derive_relevant_chunk_ids([evidence], [chunk])

    assert result.chunk_ids == {"chunk-1"}
    assert result.lineage_failure is None


def test_wholly_contained_is_false_when_chunk_text_lacks_the_evidence() -> None:
    evidence = _pdf_evidence(page=1, bbox=[20, 20, 30, 30])
    chunk = _pdf_chunk("page1-chunk", page=1, bbox=[0, 0, 100, 100], text="unrelated content")

    assert _wholly_contained(evidence, chunk) is False


def test_wholly_contained_is_true_when_chunk_text_contains_the_evidence() -> None:
    evidence = _pdf_evidence(page=1, bbox=[20, 20, 30, 30])
    chunk = _pdf_chunk("page1-chunk", page=1, bbox=[0, 0, 100, 100])

    assert _wholly_contained(evidence, chunk) is True
