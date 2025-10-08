import pytest
from evaluation.dataset_loader import load_golden_qa_dataset, get_default_dataset_path, GoldenQA
from pathlib import Path


def test_get_default_dataset_path():
    path = get_default_dataset_path()

    assert isinstance(path, Path)
    assert path.name == "golden_qa.json"
    assert "eval_data" in str(path)


def test_load_golden_qa_dataset():
    dataset_path = get_default_dataset_path()

    if not dataset_path.exists():
        pytest.skip(f"Dataset not found at {dataset_path}")

    dataset = load_golden_qa_dataset(dataset_path)

    assert isinstance(dataset, list)
    assert len(dataset) > 0

    for qa in dataset:
        assert isinstance(qa, GoldenQA)
        assert qa.question
        assert qa.answer
        assert qa.document


def test_golden_qa_model():
    qa = GoldenQA(
        question="What is Python?",
        answer="Python is a programming language",
        document="python.html",
        context_hint="About programming",
        query_type="factual",
    )

    assert qa.question == "What is Python?"
    assert qa.answer == "Python is a programming language"
    assert qa.document == "python.html"
    assert qa.context_hint == "About programming"
    assert qa.query_type == "factual"


def test_golden_qa_optional_fields():
    qa = GoldenQA(
        question="What is Python?",
        answer="Python is a programming language",
        document="python.html",
    )

    assert qa.context_hint is None
    assert qa.query_type is None


def test_load_nonexistent_dataset():
    with pytest.raises(FileNotFoundError):
        load_golden_qa_dataset("/nonexistent/path/to/dataset.json")
