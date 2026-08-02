"""Golden dataset gold-passage annotations.

The loader used to hardcode `gold_passages=[]`, which made retrieval metrics
meaningless on the only question set that reflects a user's own corpus.
"""

import json

import pytest

from evals.datasets.golden import GoldenDatasetLoader


@pytest.fixture
def golden_file(tmp_path, monkeypatch):
    def _write(entries):
        path = tmp_path / "golden_qa.json"
        path.write_text(json.dumps(entries))
        monkeypatch.setattr(GoldenDatasetLoader, "GOLDEN_PATH", path)
        monkeypatch.setattr(GoldenDatasetLoader, "GOLDEN_PATH_DOCKER", tmp_path / "nope.json")
        return path

    return _write


def test_entries_without_annotations_still_load(golden_file):
    golden_file([{"question": "Q?", "answer": "A", "document": "doc.html"}])
    dataset = GoldenDatasetLoader().load()

    assert len(dataset) == 1
    assert dataset.questions[0].gold_passages == []


def test_full_passage_annotations_are_parsed(golden_file):
    golden_file([
        {
            "question": "Q?",
            "answer": "A",
            "document": "doc.html",
            "gold_passages": [
                {"doc_id": "d1", "chunk_id": "d1:3", "text": "the passage", "relevance_score": 0.8}
            ],
            "context_passages": [{"doc_id": "d2", "chunk_id": "d2:1", "text": "distractor"}],
        }
    ])
    question = GoldenDatasetLoader().load().questions[0]

    assert len(question.gold_passages) == 1
    gold = question.gold_passages[0]
    assert (gold.doc_id, gold.chunk_id, gold.text) == ("d1", "d1:3", "the passage")
    assert gold.relevance_score == 0.8
    assert len(question.context_passages) == 1


def test_bare_strings_derive_ids_from_the_document_field(golden_file):
    golden_file([
        {"question": "Q?", "answer": "A", "document": "doc.html",
         "gold_passages": ["first passage", "second passage"]}
    ])
    question = GoldenDatasetLoader().load().questions[0]

    assert [p.text for p in question.gold_passages] == ["first passage", "second passage"]
    assert all(p.doc_id == "doc.html" for p in question.gold_passages)
    # Chunk ids must be distinct or the two passages collapse in every set-based metric
    assert len({p.chunk_id for p in question.gold_passages}) == 2


def test_gold_doc_ids_shorthand_produces_doc_level_passages(golden_file):
    golden_file([
        {"question": "Q?", "answer": "A", "gold_doc_ids": ["report.pdf", "notes.md"]}
    ])
    question = GoldenDatasetLoader().load().questions[0]

    assert {p.doc_id for p in question.gold_passages} == {"report.pdf", "notes.md"}
    # No text: these can only ever be resolved at document level
    assert all(p.text == "" for p in question.gold_passages)


def test_gold_doc_ids_do_not_duplicate_a_documented_passage(golden_file):
    golden_file([
        {
            "question": "Q?",
            "answer": "A",
            "gold_passages": [{"doc_id": "report.pdf", "chunk_id": "report.pdf:2", "text": "body"}],
            "gold_doc_ids": ["report.pdf"],
        }
    ])
    question = GoldenDatasetLoader().load().questions[0]

    assert len(question.gold_passages) == 1
    assert question.gold_passages[0].text == "body"


def test_unanswerable_flag_is_honoured(golden_file):
    golden_file([{"question": "Q?", "answer": None, "is_unanswerable": True}])
    assert GoldenDatasetLoader().load().questions[0].is_unanswerable is True
