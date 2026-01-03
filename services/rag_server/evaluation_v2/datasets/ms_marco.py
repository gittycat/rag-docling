"""MS MARCO dataset loader for evaluation v2."""

import hashlib
from datasets import load_dataset

from evaluation_v2.data_models import (
    EvaluationDataset,
    DatasetInfo,
    EvalDocument,
    EvalTestCase,
)


class MSMARCODataset(EvaluationDataset):
    """MS MARCO passage ranking dataset loader."""

    def __init__(self, config_name: str = "v1.1", **kwargs):
        super().__init__(**kwargs)
        self.config_name = config_name
        self._documents: list[EvalDocument] = []
        self._test_cases: list[EvalTestCase] = []

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name=f"MS MARCO ({self.config_name})",
            description="Passage ranking dataset for retrieval evaluation",
            source_url="https://huggingface.co/datasets/microsoft/ms_marco",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_evidence=True,
            domains=["Web"],
            license="Unknown",
        )

    def load(self) -> None:
        dataset = load_dataset(
            "microsoft/ms_marco",
            self.config_name,
            split=self.split,
            cache_dir=str(self.cache_dir),
        )

        if self.sample_size:
            dataset = dataset.select(range(min(self.sample_size, len(dataset))))

        seen_passages: set[str] = set()

        for item in dataset:
            query = item.get("query", "")
            passages = item.get("passages", [])
            answers = item.get("answers", [])

            if not query or not passages:
                continue

            expected_answer = answers[0] if answers else ""
            gold_doc_ids: list[str] = []
            gold_evidence_texts: list[str] = []

            for passage in passages:
                text = passage.get("passage_text") if isinstance(passage, dict) else ""
                if not text:
                    continue
                passage_hash = hashlib.md5(text.encode()).hexdigest()[:12]
                doc_id = f"msmarco-{passage_hash}"
                if passage_hash not in seen_passages:
                    seen_passages.add(passage_hash)
                    self._documents.append(
                        EvalDocument(
                            doc_id=doc_id,
                            content=text,
                            metadata={"source": "ms_marco"},
                        )
                    )
                if passage.get("is_selected", 0) == 1:
                    gold_doc_ids.append(doc_id)
                    gold_evidence_texts.append(text)

            self._test_cases.append(
                EvalTestCase(
                    question=query,
                    expected_answer=expected_answer,
                    gold_document_ids=gold_doc_ids,
                    gold_evidence_texts=gold_evidence_texts,
                    metadata={"source": "ms_marco"},
                )
            )

        self._loaded = True

    def get_documents(self) -> list[EvalDocument]:
        self.ensure_loaded()
        return self._documents

    def get_test_cases(self) -> list[EvalTestCase]:
        self.ensure_loaded()
        return self._test_cases
