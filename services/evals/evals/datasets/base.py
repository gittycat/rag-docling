"""Base class for dataset loaders."""

import random
from abc import ABC, abstractmethod
from typing import Any

from evals.schemas import EvalDataset, EvalQuestion, QueryType


class BaseDatasetLoader(ABC):
    """Abstract base class for dataset loaders.

    Each dataset loader is responsible for:
    1. Loading data from HuggingFace or other sources
    2. Converting to the unified EvalDataset/EvalQuestion schema
    3. Providing metadata about the dataset

    Subclasses must implement:
    - load(): Load and return the full dataset
    - get_metadata(): Return dataset metadata
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this dataset."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of the dataset."""
        ...

    @property
    @abstractmethod
    def source_url(self) -> str:
        """URL to the original dataset source."""
        ...

    @property
    def primary_aspects(self) -> list[str]:
        """Primary evaluation aspects this dataset is good for."""
        return ["generation"]

    @property
    def domains(self) -> list[str]:
        """Domains covered by this dataset."""
        return ["general"]

    @abstractmethod
    def load(
        self,
        split: str = "test",
        max_samples: int | None = None,
        seed: int | None = None,
    ) -> EvalDataset:
        """Load the dataset.

        Args:
            split: Which split to load (train, validation, test)
            max_samples: Maximum number of samples to load (None = all)
            seed: Random seed for sampling

        Returns:
            EvalDataset with loaded questions
        """
        ...

    def get_metadata(self) -> dict[str, Any]:
        """Get metadata about this dataset."""
        return {
            "name": self.name,
            "description": self.description,
            "source_url": self.source_url,
            "primary_aspects": self.primary_aspects,
            "domains": self.domains,
        }

    def fingerprint(self) -> dict[str, Any]:
        """Cache-key inputs beyond (name, split, max_samples, seed).

        Subclasses that pin an upstream revision or accept extra load()
        parameters that change the resulting data (e.g. RAGBench's `subsets`)
        should override this, so a cache built against one upstream snapshot
        is never mistaken for a cache built against another.
        """
        return {}

    def _rng(self, seed: int | None) -> random.Random:
        """A private RNG for this load — never `random.seed()`/`random.sample()`
        on the module-level `random` instance, which is process-wide shared
        state. Two datasets loaded back to back (or a dataset load nested
        inside a caller that also uses `random`) must not perturb each other.
        """
        return random.Random(seed)

    def _infer_query_type(self, question: str, metadata: dict) -> QueryType:
        """Infer query type from question text and metadata.

        Can be overridden by subclasses for dataset-specific logic.
        """
        question_lower = question.lower()

        # Check for summary/report patterns
        summary_keywords = ["summarize", "summary", "report", "list all", "describe"]
        if any(kw in question_lower for kw in summary_keywords):
            return QueryType.SUMMARY

        # Check for comparison patterns
        comparison_keywords = ["compare", "difference", "versus", "vs", "contrast"]
        if any(kw in question_lower for kw in comparison_keywords):
            return QueryType.COMPARISON

        # Check for procedural patterns
        procedural_keywords = ["how to", "how do", "how can", "steps to", "process"]
        if any(kw in question_lower for kw in procedural_keywords):
            return QueryType.PROCEDURAL

        # Default to factoid
        return QueryType.FACTOID

    def _sample_order(self, n: int, max_samples: int | None, seed: int | None) -> range | list[int]:
        """Index order to iterate a split of size `n` in.

        When sampling, this is a seeded permutation of the *entire* split
        rather than a prefix — the caller stops once it has converted
        `max_samples` items, which draws an unbiased sample and tolerates
        per-item conversion failures (skipped items just aren't counted)
        without ever falling back to "whatever came first".
        """
        if max_samples is None:
            return range(n)
        order = list(range(n))
        self._rng(seed).shuffle(order)
        return order

    def _create_question_id(self, dataset_name: str, index: int, orig_id: str | None = None) -> str:
        """Create a unique question ID."""
        if orig_id:
            return f"{dataset_name}:{orig_id}"
        return f"{dataset_name}:{index}"
