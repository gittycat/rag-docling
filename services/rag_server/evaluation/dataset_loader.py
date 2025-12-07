"""Golden dataset loader for RAG evaluation.

This module provides utilities for loading and managing the golden Q&A dataset
used for evaluating the RAG system's accuracy.
"""

import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class GoldenQA(BaseModel):
    """Golden Q&A pair with metadata."""

    question: str
    answer: str = Field(alias="expected_answer")  # Support both "answer" and "expected_answer"
    document: str | None = Field(None, alias="document_id")  # Support both field names
    context_hint: str | None = None
    query_type: str | None = None  # "factual" or "reasoning"
    difficulty: str | None = None  # "easy", "medium", "hard"
    tags: list[str] | None = None
    id: str | None = None

    class Config:
        populate_by_name = True  # Allow both field name and alias


def load_golden_qa_dataset(dataset_path: str | Path) -> list[GoldenQA]:
    """Load golden Q&A dataset from JSON file.

    Args:
        dataset_path: Path to golden_qa.json

    Returns:
        List of GoldenQA objects

    Raises:
        FileNotFoundError: If dataset file doesn't exist
    """
    dataset_path = Path(dataset_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    with open(dataset_path, "r") as f:
        data = json.load(f)

    # Handle both list format (current) and dict format (future)
    if isinstance(data, dict):
        qa_list = data.get("test_cases", [])
    else:
        qa_list = data

    return [GoldenQA(**item) for item in qa_list]


def get_default_dataset_path() -> Path:
    """Get path to default golden dataset."""
    return Path(__file__).parent.parent / "eval_data" / "golden_qa.json"


def load_default_dataset() -> list[GoldenQA]:
    """Load default golden dataset."""
    return load_golden_qa_dataset(get_default_dataset_path())


def load_golden_dataset(
    dataset_path: Optional[Path] = None,
    filter_by_type: Optional[str] = None,
    filter_by_difficulty: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[GoldenQA]:
    """Load golden Q&A dataset with optional filtering.

    Args:
        dataset_path: Path to golden_qa.json (defaults to eval_data/golden_qa.json)
        filter_by_type: Filter by query_type ("factual" or "reasoning")
        filter_by_difficulty: Filter by difficulty ("easy", "medium", "hard")
        limit: Maximum number of items to return

    Returns:
        List of GoldenQA objects

    Example:
        >>> dataset = load_golden_dataset()
        >>> factual_questions = load_golden_dataset(filter_by_type="factual")
        >>> hard_questions = load_golden_dataset(filter_by_difficulty="hard", limit=5)
    """
    if dataset_path is None:
        dataset_path = get_default_dataset_path()

    golden_dataset = load_golden_qa_dataset(dataset_path)

    # Apply filters
    if filter_by_type:
        golden_dataset = [qa for qa in golden_dataset if qa.query_type == filter_by_type]

    if filter_by_difficulty:
        golden_dataset = [
            qa for qa in golden_dataset if qa.difficulty == filter_by_difficulty
        ]

    # Apply limit
    if limit:
        golden_dataset = golden_dataset[:limit]

    return golden_dataset


def get_dataset_stats(dataset: list[GoldenQA]) -> dict:
    """Get statistics about the golden dataset.

    Args:
        dataset: List of GoldenQA objects

    Returns:
        Dictionary with dataset statistics

    Example:
        >>> dataset = load_golden_dataset()
        >>> stats = get_dataset_stats(dataset)
        >>> print(f"Total: {stats['total']}, Factual: {stats['by_type']['factual']}")
    """
    stats = {
        "total": len(dataset),
        "by_type": {},
        "by_difficulty": {},
        "by_document": {},
        "with_tags": 0,
    }

    for qa in dataset:
        # Count by type
        if qa.query_type:
            stats["by_type"][qa.query_type] = stats["by_type"].get(qa.query_type, 0) + 1

        # Count by difficulty
        if qa.difficulty:
            stats["by_difficulty"][qa.difficulty] = (
                stats["by_difficulty"].get(qa.difficulty, 0) + 1
            )

        # Count by document
        if qa.document:
            stats["by_document"][qa.document] = (
                stats["by_document"].get(qa.document, 0) + 1
            )

        # Count with tags
        if qa.tags:
            stats["with_tags"] += 1

    return stats
