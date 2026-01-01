"""Dataset loaders for RAG benchmarking.

This module provides loaders for various public QA datasets that can be used
to evaluate RAG system performance.
"""

from evaluation.datasets.base import (
    BenchmarkDataset,
    Document,
    TestCase,
    DatasetInfo,
)
from evaluation.datasets.squad import SQuADDataset
from evaluation.datasets.ragbench import RAGBenchDataset
from evaluation.datasets.hotpotqa import HotpotQADataset

__all__ = [
    "BenchmarkDataset",
    "Document",
    "TestCase",
    "DatasetInfo",
    "SQuADDataset",
    "RAGBenchDataset",
    "HotpotQADataset",
    "get_dataset",
    "list_datasets",
]


DATASET_REGISTRY: dict[str, type[BenchmarkDataset]] = {
    "squad": SQuADDataset,
    "ragbench": RAGBenchDataset,
    "hotpotqa": HotpotQADataset,
}


def get_dataset(name: str, **kwargs) -> BenchmarkDataset:
    """Get a dataset by name.

    Args:
        name: Dataset name (squad, ragbench, hotpotqa)
        **kwargs: Additional arguments passed to dataset constructor

    Returns:
        Initialized dataset loader

    Raises:
        ValueError: If dataset name is not recognized
    """
    name_lower = name.lower()
    if name_lower not in DATASET_REGISTRY:
        available = ", ".join(DATASET_REGISTRY.keys())
        raise ValueError(f"Unknown dataset: {name}. Available: {available}")

    return DATASET_REGISTRY[name_lower](**kwargs)


def list_datasets() -> list[str]:
    """List available dataset names."""
    return list(DATASET_REGISTRY.keys())
