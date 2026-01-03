"""RAGBench dataset loader for evaluation v2."""

import hashlib
from datasets import load_dataset

from evaluation_v2.data_models import (
    EvaluationDataset,
    DatasetInfo,
    EvalDocument,
    EvalTestCase,
)

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


class RAGBenchDataset(EvaluationDataset):
    """RAGBench loader with optional subset selection."""

    def __init__(self, subset: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.subset = subset
        self._documents: list[EvalDocument] = []
        self._test_cases: list[EvalTestCase] = []

        if subset and subset not in RAGBENCH_SUBSETS:
            available = ", ".join(RAGBENCH_SUBSETS)
            raise ValueError(f"Unknown subset: {subset}. Available: {available}")

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name=f"RAGBench{f' ({self.subset})' if self.subset else ''}",
            description="RAG benchmark across industry domains",
            source_url="https://huggingface.co/datasets/rungalileo/ragbench",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_evidence=True,
            domains=RAGBENCH_SUBSETS if not self.subset else [self.subset],
            license="CC BY 4.0",
        )

    def load(self) -> None:
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
                    split="test",
                    cache_dir=str(self.cache_dir),
                )

                if samples_per_subset:
                    dataset = dataset.select(range(min(samples_per_subset, len(dataset))))

                for item in dataset:
                    question = item.get("question", "")
                    documents = item.get("documents", [])
                    response = item.get("response", "")
                    support_info = item.get("sentence_support_information", [])

                    if not question or not documents:
                        continue

                    gold_evidence_texts: list[str] = []
                    documents_sentences = item.get("documents_sentences") or []
                    for support in support_info:
                        supporting_keys = support.get("supporting_sentence_keys", [])
                        for key in supporting_keys:
                            if isinstance(key, (list, tuple)) and len(key) == 2:
                                doc_idx, sent_idx = key
                                if (
                                    isinstance(doc_idx, int)
                                    and isinstance(sent_idx, int)
                                    and doc_idx < len(documents_sentences)
                                    and sent_idx < len(documents_sentences[doc_idx])
                                ):
                                    gold_evidence_texts.append(
                                        documents_sentences[doc_idx][sent_idx]
                                    )
                            elif isinstance(key, dict):
                                doc_idx = key.get("doc_idx")
                                sent_idx = key.get("sent_idx")
                                if (
                                    isinstance(doc_idx, int)
                                    and isinstance(sent_idx, int)
                                    and doc_idx < len(documents_sentences)
                                    and sent_idx < len(documents_sentences[doc_idx])
                                ):
                                    gold_evidence_texts.append(
                                        documents_sentences[doc_idx][sent_idx]
                                    )

                    gold_doc_ids: list[str] = []
                    for doc_text in documents:
                        if not doc_text:
                            continue
                        context_hash = hashlib.md5(doc_text.encode()).hexdigest()[:12]
                        doc_id = f"ragbench-{subset_name}-{context_hash}"
                        if context_hash not in seen_contexts:
                            seen_contexts.add(context_hash)
                            self._documents.append(
                                EvalDocument(
                                    doc_id=doc_id,
                                    content=doc_text,
                                    metadata={"source": "ragbench", "subset": subset_name},
                                )
                            )
                        gold_doc_ids.append(doc_id)

                    self._test_cases.append(
                        EvalTestCase(
                            question=question,
                            expected_answer=response,
                            gold_document_ids=gold_doc_ids,
                            gold_evidence_texts=gold_evidence_texts,
                            metadata={
                                "source": "ragbench",
                                "subset": subset_name,
                                "relevance_labels": item.get("relevance_labels", []),
                            },
                        )
                    )
            except Exception as exc:
                print(f"Warning: failed to load RAGBench subset '{subset_name}': {exc}")
                continue

        self._loaded = True

    def get_documents(self) -> list[EvalDocument]:
        self.ensure_loaded()
        return self._documents

    def get_test_cases(self) -> list[EvalTestCase]:
        self.ensure_loaded()
        return self._test_cases
