"""HotpotQA dataset loader for RAG benchmarking.

HotpotQA is a multi-hop question answering dataset with 113K QA pairs.
It features sentence-level supporting facts for explainable QA.

Source: https://huggingface.co/datasets/hotpotqa/hotpot_qa
"""

import hashlib
from datasets import load_dataset

from evaluation.datasets.base import (
    BenchmarkDataset,
    DatasetInfo,
    Document,
    TestCase,
)


class HotpotQADataset(BenchmarkDataset):
    """HotpotQA dataset loader.

    HotpotQA is ideal for:
    - Multi-hop reasoning evaluation
    - Sentence-level retrieval assessment
    - Testing complex question handling

    The dataset has two settings:
    - distractor: Gold paragraphs + 8 distractor paragraphs
    - fullwiki: Requires retrieval from full Wikipedia

    Usage:
        # Distractor setting (easier, includes gold passages)
        dataset = HotpotQADataset(setting="distractor", sample_size=100)

        # Full wiki setting (harder, pure retrieval task)
        dataset = HotpotQADataset(setting="fullwiki", sample_size=100)

        dataset.load()
        docs = dataset.get_documents()
        tests = dataset.get_test_cases()
    """

    def __init__(self, setting: str = "distractor", **kwargs):
        """Initialize HotpotQA loader.

        Args:
            setting: 'distractor' (with gold + distractors) or 'fullwiki'
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        if setting not in ("distractor", "fullwiki"):
            raise ValueError(f"Invalid setting: {setting}. Use 'distractor' or 'fullwiki'")

        self.setting = setting
        self._documents: list[Document] = []
        self._test_cases: list[TestCase] = []

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name=f"HotpotQA ({self.setting})",
            description="Multi-hop question answering with supporting facts",
            source_url="https://huggingface.co/datasets/hotpotqa/hotpot_qa",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_passages=True,
            domains=["Wikipedia"],
            license="CC BY-SA 4.0",
        )

    def load(self) -> None:
        """Load HotpotQA from HuggingFace."""
        # HotpotQA uses 'distractor' or 'fullwiki' as the name
        dataset = load_dataset(
            "hotpotqa/hotpot_qa",
            self.setting,
            split=self.split,
            cache_dir=str(self.cache_dir),
        )

        # Apply sample size limit
        if self.sample_size:
            dataset = dataset.select(range(min(self.sample_size, len(dataset))))

        seen_contexts: set[str] = set()

        for item in dataset:
            question = item["question"]
            answer = item["answer"]
            context = item["context"]  # dict with 'title' and 'sentences' lists
            supporting_facts = item["supporting_facts"]  # dict with 'title' and 'sent_id'

            # Extract supporting fact titles for gold passage identification
            supporting_titles = set(supporting_facts.get("title", []))

            # Create documents from context paragraphs
            gold_passage_ids = []
            titles = context.get("title", [])
            sentences_list = context.get("sentences", [])

            for title, sentences in zip(titles, sentences_list):
                if not sentences:
                    continue

                # Combine sentences into paragraph
                paragraph = " ".join(sentences)
                context_hash = hashlib.md5(paragraph.encode()).hexdigest()[:12]
                doc_id = f"hotpot-{context_hash}"

                # Track if this is a supporting (gold) passage
                is_gold = title in supporting_titles

                if context_hash not in seen_contexts:
                    seen_contexts.add(context_hash)
                    self._documents.append(
                        Document(
                            doc_id=doc_id,
                            content=paragraph,
                            metadata={
                                "source": "hotpotqa",
                                "title": title,
                                "setting": self.setting,
                                "is_supporting": is_gold,
                            },
                        )
                    )

                if is_gold:
                    gold_passage_ids.append(doc_id)

            # Create test case
            self._test_cases.append(
                TestCase(
                    question=question,
                    expected_answer=answer,
                    gold_passage_ids=gold_passage_ids,
                    metadata={
                        "source": "hotpotqa",
                        "setting": self.setting,
                        "type": item.get("type", ""),  # 'comparison' or 'bridge'
                        "level": item.get("level", ""),  # 'easy', 'medium', 'hard'
                        "supporting_facts": supporting_facts,
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

    def get_by_type(self, question_type: str) -> list[TestCase]:
        """Get test cases by question type ('comparison' or 'bridge')."""
        self.ensure_loaded()
        return [
            tc for tc in self._test_cases
            if tc.metadata.get("type") == question_type
        ]

    def get_by_difficulty(self, level: str) -> list[TestCase]:
        """Get test cases by difficulty level ('easy', 'medium', 'hard')."""
        self.ensure_loaded()
        return [
            tc for tc in self._test_cases
            if tc.metadata.get("level") == level
        ]

    def get_multi_hop_only(self) -> list[TestCase]:
        """Get only bridge-type questions (true multi-hop reasoning)."""
        return self.get_by_type("bridge")
