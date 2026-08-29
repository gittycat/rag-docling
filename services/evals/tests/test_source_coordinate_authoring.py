"""Track F: source-coordinate ground truth is actually authored and reachable.

Before this, `grep -rn "EvidenceLocator("` across evals/ found only the cache
round-trip and sample deserialization — two sites that rehydrate what something
else wrote, and nothing wrote. The whole source-coordinate path was dead code.
"""

import hashlib
import json
from pathlib import Path

import pytest

from evals.datasets.golden import GoldenDatasetLoader
from evals.evidence import (
    _bbox_contains,
    _bbox_overlap,
    _locator_is_usable,
    _normalized_bbox,
    _valid_bbox,
)


class TestDoclingBboxOrigin:
    # Docling emits PDF provenance with coord_origin BOTTOMLEFT, where the top
    # edge has a LARGER y than the bottom edge. Assuming a top-left origin
    # rejected every real PDF bbox, so every PDF locator was unusable and the
    # entire PDF path was a lineage failure. This is the shape Docling actually
    # produced for the sylvania_report.pdf fixture.
    DOCLING_BBOX = [31.18, 751.528, 564.094, 721.513]

    def test_a_real_docling_bbox_is_valid(self):
        assert _valid_bbox(self.DOCLING_BBOX) is True

    def test_normalisation_orders_both_axes(self):
        assert _normalized_bbox(self.DOCLING_BBOX) == (31.18, 721.513, 564.094, 751.528)

    def test_top_left_origin_boxes_still_work(self):
        assert _normalized_bbox([10.0, 20.0, 30.0, 40.0]) == (10.0, 20.0, 30.0, 40.0)

    def test_overlap_is_origin_agnostic(self):
        bottom_left = [31.18, 751.528, 564.094, 721.513]
        top_left = [40.0, 725.0, 550.0, 748.0]
        assert _bbox_overlap(bottom_left, top_left) is True
        assert _bbox_contains(bottom_left, top_left) is True

    def test_a_degenerate_box_is_still_not_a_box(self):
        assert _normalized_bbox([10.0, 20.0, 10.0, 40.0]) is None
        assert _valid_bbox([1, 2, 3]) is False
        assert _valid_bbox("nope") is False

    def test_pdf_locator_with_element_id_is_usable(self):
        # Docling carries element_id (self_ref), never block_id. Accepting only
        # block_id or a bbox made every real Docling locator unusable.
        assert _locator_is_usable("pdf", {"page": 1, "element_id": "#/texts/2"}) is True

    def test_pdf_locator_with_neither_is_not_usable(self):
        assert _locator_is_usable("pdf", {"page": 1}) is False


class TestGoldenLoaderAuthorsLocators:
    def test_the_loader_constructs_evidence_locators(self):
        questions = GoldenDatasetLoader().load().questions
        with_evidence = [q for q in questions if q.evidence]
        assert with_evidence, "golden dataset must author at least one locator"

    def test_document_hash_is_the_sha256_of_the_real_source_bytes(self):
        # This is the whole point: the hash must equal what documents.file_hash
        # records after ingesting those same bytes, or the locator resolves to
        # nothing.
        for question in GoldenDatasetLoader().load().questions:
            if not question.evidence:
                continue
            source = Path(question.metadata["source_path"])
            expected = hashlib.sha256(source.read_bytes()).hexdigest()
            for locator in question.evidence:
                assert locator.document_hash == expected

    def test_every_authored_locator_is_usable(self):
        for question in GoldenDatasetLoader().load().questions:
            for locator in question.evidence:
                assert _locator_is_usable(locator.source_format, locator.locator), locator

    def test_both_a_text_and_a_pdf_fixture_are_covered(self):
        formats = {
            locator.source_format
            for question in GoldenDatasetLoader().load().questions
            for locator in question.evidence
        }
        assert {"txt", "pdf"} <= formats

    def test_authored_text_matches_the_source_document(self):
        # Authored FROM the source document, never from a chunk: the recorded
        # span has to actually appear in the file at the recorded coordinates.
        for question in GoldenDatasetLoader().load().questions:
            for locator in question.evidence:
                if locator.source_format != "txt":
                    continue
                raw = Path(question.metadata["source_path"]).read_text()
                span = raw[locator.locator["start_char"]:locator.locator["end_char"]]
                assert GoldenDatasetLoader._normalize(span) == locator.normalized_text

    def test_a_missing_source_file_drops_the_locator_rather_than_faking_it(self, tmp_path):
        loader = GoldenDatasetLoader()
        item = {
            "question": "q?", "answer": "a", "document": "not_in_corpus.txt",
            "evidence": [{"text": "x", "locator": {"element_path": "document",
                                                   "start_char": 0, "end_char": 1}}],
        }
        assert loader._parse_evidence(item, 0) == []

    def test_evidence_without_text_or_locator_is_skipped(self):
        loader = GoldenDatasetLoader()
        item = {
            "question": "q?", "source_file": "freedonia_facts.txt",
            "evidence": [{"text": "no locator"}, {"locator": {"page": 1}}],
        }
        assert loader._parse_evidence(item, 0) == []


class TestCacheFingerprintCoversLocators:
    def test_fingerprint_includes_the_locator_payload_and_source_bytes(self):
        fingerprint = GoldenDatasetLoader().fingerprint()
        assert "evidence" in fingerprint
        assert "source_documents" in fingerprint
        assert fingerprint["source_documents"], "source bytes must be fingerprinted"

    def test_reauthoring_a_locator_changes_the_fingerprint(self, monkeypatch, tmp_path):
        loader = GoldenDatasetLoader()
        before = loader.fingerprint()

        original = json.loads(Path(loader._get_path()).read_text())
        mutated = [dict(item) for item in original]
        for item in mutated:
            if item.get("evidence"):
                item["evidence"] = [
                    {**e, "locator": {**e["locator"], "start_char": 999}}
                    for e in item["evidence"]
                ]
                break

        target = tmp_path / "golden_qa.json"
        target.write_text(json.dumps(mutated))
        monkeypatch.setattr(loader, "_get_path", lambda: target)

        assert loader.fingerprint()["evidence"] != before["evidence"]
