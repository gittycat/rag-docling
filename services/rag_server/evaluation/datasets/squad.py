"""SQuAD 2.0 dataset loader for RAG benchmarking.

SQuAD 2.0 (Stanford Question Answering Dataset) contains 150K questions,
including 50K unanswerable questions. Each question has a context passage
and an answer extracted from the passage.

Source: https://huggingface.co/datasets/rajpurkar/squad
"""

import hashlib
from datasets import load_dataset

from evaluation.datasets.base import (
    BenchmarkDataset,
    DatasetInfo,
    Document,
    TestCase,
)


class SQuADDataset(BenchmarkDataset):
    """SQuAD 2.0 dataset loader.

    SQuAD is ideal for:
    - Quick pipeline validation (self-contained contexts)
    - Testing unanswerable question handling
    - Baseline retrieval evaluation

    Usage:
        dataset = SQuADDataset(sample_size=100)
        dataset.load()

        # Get documents for ingestion
        for doc in dataset.get_documents():
            upload_to_rag(doc)

        # Get test cases for evaluation
        for test in dataset.get_test_cases():
            result = query_rag(test.question)
            evaluate(result, test.expected_answer)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._documents: list[Document] = []
        self._test_cases: list[TestCase] = []
        self._context_to_doc_id: dict[str, str] = {}

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name="SQuAD 2.0",
            description="Stanford Question Answering Dataset with unanswerable questions",
            source_url="https://huggingface.co/datasets/rajpurkar/squad_v2",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_passages=True,
            domains=["Wikipedia"],
            license="CC BY-SA 4.0",
        )

    def load(self) -> None:
        """Load SQuAD 2.0 from HuggingFace."""
        # Load dataset
        dataset = load_dataset(
            "rajpurkar/squad_v2",
            split=self.split,
            cache_dir=str(self.cache_dir),
        )

        # Apply sample size limit
        if self.sample_size:
            dataset = dataset.select(range(min(self.sample_size, len(dataset))))

        # Process into documents and test cases
        seen_contexts: set[str] = set()

        for item in dataset:
            context = item["context"]
            question = item["question"]
            answers = item["answers"]

            # Create document from context (deduplicate)
            context_hash = hashlib.md5(context.encode()).hexdigest()[:12]
            doc_id = f"squad-{context_hash}"

            if context_hash not in seen_contexts:
                seen_contexts.add(context_hash)
                self._documents.append(
                    Document(
                        doc_id=doc_id,
                        content=context,
                        metadata={
                            "source": "squad",
                            "title": item.get("title", ""),
                        },
                    )
                )
                self._context_to_doc_id[context_hash] = doc_id

            # Create test case
            # SQuAD 2.0 has empty answers for unanswerable questions
            if answers["text"]:
                expected_answer = answers["text"][0]
                is_answerable = True
            else:
                expected_answer = ""
                is_answerable = False

            self._test_cases.append(
                TestCase(
                    question=question,
                    expected_answer=expected_answer,
                    gold_passage_ids=[doc_id],
                    metadata={
                        "source": "squad",
                        "is_answerable": is_answerable,
                        "answer_start": answers["answer_start"][0] if answers["answer_start"] else -1,
                    },
                )
            )

        self._loaded = True

    def get_documents(self) -> list[Document]:
        self.ensure_loaded()
        return self._documents

    def get_test_cases(self) -> list[TestCase]:
        self.ensure_loaded()
        return self._test_cases

    def get_answerable_only(self) -> list[TestCase]:
        """Get only answerable test cases (excludes unanswerable questions)."""
        self.ensure_loaded()
        return [tc for tc in self._test_cases if tc.metadata.get("is_answerable", True)]

    def get_unanswerable_only(self) -> list[TestCase]:
        """Get only unanswerable test cases."""
        self.ensure_loaded()
        return [tc for tc in self._test_cases if not tc.metadata.get("is_answerable", True)]
