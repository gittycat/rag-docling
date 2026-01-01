"""Base classes for benchmark dataset loaders."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class Document:
    """A document to be ingested into the RAG system."""

    doc_id: str
    content: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary format for API upload."""
        return {
            "doc_id": self.doc_id,
            "content": self.content,
            "metadata": self.metadata,
        }


@dataclass
class TestCase:
    """A test case for RAG evaluation."""

    question: str
    expected_answer: str
    gold_passage_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        return {
            "question": self.question,
            "expected_answer": self.expected_answer,
            "gold_passage_ids": self.gold_passage_ids,
            "metadata": self.metadata,
        }


@dataclass
class DatasetInfo:
    """Metadata about a dataset."""

    name: str
    description: str
    source_url: str
    num_documents: int
    num_test_cases: int
    has_gold_passages: bool
    domains: list[str] = field(default_factory=list)
    license: str = "Unknown"


class BenchmarkDataset(ABC):
    """Abstract base class for benchmark dataset loaders.

    Subclasses must implement:
    - load(): Download/load the dataset
    - get_documents(): Return documents for ingestion
    - get_test_cases(): Return test cases for evaluation
    - info: Property returning DatasetInfo
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        sample_size: int | None = None,
        split: str = "validation",
    ):
        """Initialize dataset loader.

        Args:
            cache_dir: Directory to cache downloaded datasets
            sample_size: Limit number of test cases (None = all)
            split: Dataset split to use (train, validation, test)
        """
        self.cache_dir = cache_dir or Path.home() / ".cache" / "rag-bench"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sample_size = sample_size
        self.split = split
        self._loaded = False

    @property
    @abstractmethod
    def info(self) -> DatasetInfo:
        """Return dataset metadata."""
        ...

    @abstractmethod
    def load(self) -> None:
        """Download and load the dataset.

        Should populate internal data structures for documents and test cases.
        """
        ...

    @abstractmethod
    def get_documents(self) -> list[Document]:
        """Return documents for ingestion into RAG system.

        Returns:
            List of Document objects ready for ingestion
        """
        ...

    @abstractmethod
    def get_test_cases(self) -> list[TestCase]:
        """Return test cases for evaluation.

        Returns:
            List of TestCase objects with questions and expected answers
        """
        ...

    def iter_documents(self, batch_size: int = 100) -> Iterator[list[Document]]:
        """Iterate over documents in batches.

        Args:
            batch_size: Number of documents per batch

        Yields:
            Lists of Document objects
        """
        documents = self.get_documents()
        for i in range(0, len(documents), batch_size):
            yield documents[i : i + batch_size]

    def iter_test_cases(self, batch_size: int = 50) -> Iterator[list[TestCase]]:
        """Iterate over test cases in batches.

        Args:
            batch_size: Number of test cases per batch

        Yields:
            Lists of TestCase objects
        """
        test_cases = self.get_test_cases()
        for i in range(0, len(test_cases), batch_size):
            yield test_cases[i : i + batch_size]

    def ensure_loaded(self) -> None:
        """Ensure dataset is loaded, loading if necessary."""
        if not self._loaded:
            self.load()
            self._loaded = True

    def __repr__(self) -> str:
        info = self.info
        return f"{self.__class__.__name__}(docs={info.num_documents}, tests={info.num_test_cases})"
