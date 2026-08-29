"""Phase 3's ingestion half: source coordinates survive a re-chunk.

Runs the real parse+chunk path at two chunk sizes and asserts that the lineage
each chunk records still locates the same evidence span. The prior "rechunk
test" lived in the evals suite and fed the resolver synthetic locators, so it
never touched an ingestion — this does.
"""

import hashlib
from pathlib import Path

import pytest

from pipelines.ingestion import (
    SOURCE_LOCATOR_METADATA_KEY,
    chunk_document,
    compute_file_hash,
)

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "evals" / "data" / "documents"
TXT_FIXTURE = CORPUS / "freedonia_facts.txt"
PDF_FIXTURE = CORPUS / "sylvania_report.pdf"

# Authored from the source document, matching evals/data/golden_qa.json.
TXT_EVIDENCE = {"start_char": 264, "end_char": 371}
PDF_EVIDENCE = {"page": 1, "bbox": [40.0, 725.0, 550.0, 748.0]}

CHUNK_SIZES = (500, 1000)


def _locators(nodes):
    found = []
    for node in nodes:
        locator = node.metadata.get(SOURCE_LOCATOR_METADATA_KEY)
        if isinstance(locator, dict):
            found.append(locator)
    return found


def _ranges_overlap(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def _normalized(bbox):
    x0, x1 = sorted((float(bbox[0]), float(bbox[2])))
    y0, y1 = sorted((float(bbox[1]), float(bbox[3])))
    return x0, y0, x1, y1


@pytest.mark.skipif(not TXT_FIXTURE.exists(), reason="txt fixture missing")
def test_text_evidence_resolves_at_every_chunk_size():
    document_hash = compute_file_hash(str(TXT_FIXTURE))
    resolved_per_size = {}

    for chunk_size in CHUNK_SIZES:
        nodes = chunk_document(
            str(TXT_FIXTURE),
            chunk_size=chunk_size,
            chunk_overlap=50,
            document_hash=document_hash,
        )
        locators = _locators(nodes)
        assert locators, f"no source lineage recorded at chunk_size={chunk_size}"

        matching = [
            entry for entry in locators
            if entry["source_format"] in ("txt", "text")
            and _ranges_overlap(
                TXT_EVIDENCE["start_char"], TXT_EVIDENCE["end_char"],
                entry["locator"]["start_char"], entry["locator"]["end_char"],
            )
        ]
        assert matching, (
            f"evidence at {TXT_EVIDENCE} resolved to no chunk at chunk_size={chunk_size}"
        )
        resolved_per_size[chunk_size] = matching

        # Every chunk that claims the span must actually contain the text, or
        # the coordinate has drifted away from the content it points at.
        raw = TXT_FIXTURE.read_text()
        expected = raw[TXT_EVIDENCE["start_char"]:TXT_EVIDENCE["end_char"]]
        joined = " ".join(entry["normalized_text"] for entry in matching)
        assert " ".join(expected.split()) in " ".join(joined.split())

    assert set(resolved_per_size) == set(CHUNK_SIZES)


@pytest.mark.skipif(not TXT_FIXTURE.exists(), reason="txt fixture missing")
def test_recorded_document_hash_is_the_files_own_hash():
    # The locator's document_hash must equal documents.file_hash, or a gold
    # locator authored against the source file can never match an ingested chunk.
    document_hash = compute_file_hash(str(TXT_FIXTURE))
    assert document_hash == hashlib.sha256(TXT_FIXTURE.read_bytes()).hexdigest()

    nodes = chunk_document(
        str(TXT_FIXTURE), chunk_size=500, chunk_overlap=50, document_hash=document_hash
    )
    for entry in _locators(nodes):
        assert entry["document_hash"] == document_hash


@pytest.mark.slow
@pytest.mark.skipif(not PDF_FIXTURE.exists(), reason="pdf fixture missing")
def test_pdf_evidence_resolves_through_the_real_docling_path():
    # The PDF path had never been exercised end to end. Docling reports
    # BOTTOMLEFT-origin bboxes (top edge y > bottom edge y), which is why the
    # resolver normalises both axes before comparing.
    document_hash = compute_file_hash(str(PDF_FIXTURE))
    nodes = chunk_document(str(PDF_FIXTURE), document_hash=document_hash)
    locators = _locators(nodes)
    assert locators, "docling recorded no source lineage for the pdf"

    evidence_box = _normalized(PDF_EVIDENCE["bbox"])
    matches = []
    for entry in locators:
        regions = entry["locator"].get("regions") or [entry["locator"]]
        for region in regions:
            if region.get("page") != PDF_EVIDENCE["page"]:
                continue
            bbox = region.get("bbox")
            if not bbox:
                continue
            box = _normalized(bbox)
            if _ranges_overlap(box[0], box[2], evidence_box[0], evidence_box[2]) and \
               _ranges_overlap(box[1], box[3], evidence_box[1], evidence_box[3]):
                matches.append(entry)
                break

    assert matches, "pdf evidence bbox resolved to no chunk on its page"
    assert any("water authority" in entry["normalized_text"] for entry in matches)
