"""Data models for the evaluation v2 pipeline."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class EvalDocument:
    """A document to ingest for evaluation."""

    doc_id: str
    content: str
    metadata: dict = field(default_factory=dict)


@dataclass
class EvalTestCase:
    """A test case with optional gold evidence."""

    question: str
    expected_answer: str
    gold_document_ids: list[str] = field(default_factory=list)
    gold_evidence_texts: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class DatasetInfo:
    """Metadata about an evaluation dataset."""

    name: str
    description: str
    source_url: str
    num_documents: int
    num_test_cases: int
    has_gold_evidence: bool
    domains: list[str] = field(default_factory=list)
    license: str = "Unknown"


class EvaluationDataset(ABC):
    """Abstract base class for evaluation datasets."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        sample_size: int | None = None,
        split: str = "validation",
    ):
        self.cache_dir = cache_dir or Path.home() / ".cache" / "rag-eval-v2"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.sample_size = sample_size
        self.split = split
        self._loaded = False

    @property
    @abstractmethod
    def info(self) -> DatasetInfo:
        ...

    @abstractmethod
    def load(self) -> None:
        ...

    @abstractmethod
    def get_documents(self) -> list[EvalDocument]:
        ...

    @abstractmethod
    def get_test_cases(self) -> list[EvalTestCase]:
        ...

    def iter_documents(self, batch_size: int = 100) -> Iterator[list[EvalDocument]]:
        documents = self.get_documents()
        for i in range(0, len(documents), batch_size):
            yield documents[i : i + batch_size]

    def iter_test_cases(self, batch_size: int = 50) -> Iterator[list[EvalTestCase]]:
        test_cases = self.get_test_cases()
        for i in range(0, len(test_cases), batch_size):
            yield test_cases[i : i + batch_size]

    def ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()
            self._loaded = True
