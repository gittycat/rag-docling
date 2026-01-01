"""RAGBench dataset loader for RAG benchmarking.

RAGBench is a purpose-built RAG benchmark with 100K examples across
5 industry domains. It includes the TRACe evaluation framework.

Source: https://huggingface.co/datasets/rungalileo/ragbench
"""

import hashlib
from datasets import load_dataset

from evaluation.datasets.base import (
    BenchmarkDataset,
    DatasetInfo,
    Document,
    TestCase,
)


# RAGBench subsets (domains)
RAGBENCH_SUBSETS = [
    "covidqa",
    "cuad",
    "delucionqa",
    "emanual",
    "expertqa",
    "finqa",
    "hagrid",
    "hotpotqa",
    "msmarco",
    "pubmedqa",
    "tatqa",
    "techqa",
]


class RAGBenchDataset(BenchmarkDataset):
    """RAGBench dataset loader.

    RAGBench is ideal for:
    - Comprehensive RAG evaluation
    - Industry-relevant benchmarking
    - Multi-domain testing

    Usage:
        # Load all domains
        dataset = RAGBenchDataset(sample_size=1000)

        # Load specific domain
        dataset = RAGBenchDataset(subset="techqa", sample_size=100)

        dataset.load()
        docs = dataset.get_documents()
        tests = dataset.get_test_cases()
    """

    def __init__(self, subset: str | None = None, **kwargs):
        """Initialize RAGBench loader.

        Args:
            subset: Specific domain to load (e.g., 'techqa', 'finqa').
                   If None, loads all domains.
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self.subset = subset
        self._documents: list[Document] = []
        self._test_cases: list[TestCase] = []

        if subset and subset not in RAGBENCH_SUBSETS:
            available = ", ".join(RAGBENCH_SUBSETS)
            raise ValueError(f"Unknown subset: {subset}. Available: {available}")

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name=f"RAGBench{f' ({self.subset})' if self.subset else ''}",
            description="Large-scale RAG benchmark across industry domains",
            source_url="https://huggingface.co/datasets/rungalileo/ragbench",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_passages=True,
            domains=RAGBENCH_SUBSETS if not self.subset else [self.subset],
            license="Apache 2.0",
        )

    def load(self) -> None:
        """Load RAGBench from HuggingFace."""
        subsets_to_load = [self.subset] if self.subset else RAGBENCH_SUBSETS
        seen_contexts: set[str] = set()
        samples_per_subset = (
            self.sample_size // len(subsets_to_load) if self.sample_size else None
        )

        for subset_name in subsets_to_load:
            try:
                dataset = load_dataset(
                    "rungalileo/ragbench",
                    subset_name,
                    split="test",  # RAGBench uses test split
                    cache_dir=str(self.cache_dir),
                )

                # Apply sample limit per subset
                if samples_per_subset:
                    dataset = dataset.select(
                        range(min(samples_per_subset, len(dataset)))
                    )

                for item in dataset:
                    # RAGBench structure: question, documents, response, etc.
                    question = item.get("question", "")
                    documents = item.get("documents", [])
                    response = item.get("response", "")

                    # Skip if missing essential fields
                    if not question or not documents:
                        continue

                    # Create documents from context
                    gold_passage_ids = []
                    for i, doc_text in enumerate(documents):
                        if not doc_text:
                            continue

                        context_hash = hashlib.md5(doc_text.encode()).hexdigest()[:12]
                        doc_id = f"ragbench-{subset_name}-{context_hash}"

                        if context_hash not in seen_contexts:
                            seen_contexts.add(context_hash)
                            self._documents.append(
                                Document(
                                    doc_id=doc_id,
                                    content=doc_text,
                                    metadata={
                                        "source": "ragbench",
                                        "subset": subset_name,
                                    },
                                )
                            )

                        gold_passage_ids.append(doc_id)

                    # Create test case
                    self._test_cases.append(
                        TestCase(
                            question=question,
                            expected_answer=response,
                            gold_passage_ids=gold_passage_ids,
                            metadata={
                                "source": "ragbench",
                                "subset": subset_name,
                                "relevance_labels": item.get("relevance_labels", []),
                            },
                        )
                    )

            except Exception as e:
                print(f"Warning: Failed to load RAGBench subset '{subset_name}': {e}")
                continue

        self._loaded = True

    def get_documents(self) -> list[Document]:
        self.ensure_loaded()
        return self._documents

    def get_test_cases(self) -> list[TestCase]:
        self.ensure_loaded()
        return self._test_cases

    def get_by_domain(self, domain: str) -> list[TestCase]:
        """Get test cases for a specific domain."""
        self.ensure_loaded()
        return [
            tc for tc in self._test_cases
            if tc.metadata.get("subset") == domain
        ]

    @staticmethod
    def available_subsets() -> list[str]:
        """List available RAGBench subsets/domains."""
        return RAGBENCH_SUBSETS.copy()
