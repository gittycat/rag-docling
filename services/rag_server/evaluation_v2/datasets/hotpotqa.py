"""HotpotQA dataset loader for evaluation v2."""

import hashlib
from datasets import load_dataset

from evaluation_v2.data_models import (
    EvaluationDataset,
    DatasetInfo,
    EvalDocument,
    EvalTestCase,
)


class HotpotQADataset(EvaluationDataset):
    """HotpotQA loader with supporting facts."""

    def __init__(self, setting: str = "distractor", **kwargs):
        super().__init__(**kwargs)
        if setting not in ("distractor", "fullwiki"):
            raise ValueError("setting must be 'distractor' or 'fullwiki'")
        self.setting = setting
        self._documents: list[EvalDocument] = []
        self._test_cases: list[EvalTestCase] = []

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name=f"HotpotQA ({self.setting})",
            description="Multi-hop QA with supporting facts",
            source_url="https://huggingface.co/datasets/hotpotqa/hotpot_qa",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_evidence=True,
            domains=["Wikipedia"],
            license="CC BY-SA 4.0",
        )

    def load(self) -> None:
        dataset = load_dataset(
            "hotpotqa/hotpot_qa",
            self.setting,
            split=self.split,
            cache_dir=str(self.cache_dir),
        )

        if self.sample_size:
            dataset = dataset.select(range(min(self.sample_size, len(dataset))))

        seen_contexts: set[str] = set()

        for item in dataset:
            question = item.get("question", "")
            answer = item.get("answer", "")
            context = item.get("context", {})
            supporting_facts = item.get("supporting_facts", {})

            titles = context.get("title", [])
            sentences_list = context.get("sentences", [])
            support_titles = supporting_facts.get("title", [])
            support_sent_ids = supporting_facts.get("sent_id", [])
            support_titles_set = set(support_titles)

            gold_evidence_texts: list[str] = []
            for title, sent_id in zip(support_titles, support_sent_ids):
                for ctx_title, sentences in zip(titles, sentences_list):
                    if title == ctx_title and isinstance(sent_id, int) and sent_id < len(sentences):
                        gold_evidence_texts.append(sentences[sent_id])

            gold_doc_ids: list[str] = []
            for title, sentences in zip(titles, sentences_list):
                if not sentences:
                    continue
                paragraph = " ".join(sentences)
                context_hash = hashlib.md5(paragraph.encode()).hexdigest()[:12]
                doc_id = f"hotpot-{context_hash}"

                if context_hash not in seen_contexts:
                    seen_contexts.add(context_hash)
                    self._documents.append(
                        EvalDocument(
                            doc_id=doc_id,
                            content=paragraph,
                            metadata={
                                "source": "hotpotqa",
                                "title": title,
                                "setting": self.setting,
                            },
                        )
                    )

                if title in support_titles_set:
                    gold_doc_ids.append(doc_id)

            if not question:
                continue

            self._test_cases.append(
                EvalTestCase(
                    question=question,
                    expected_answer=answer,
                    gold_document_ids=gold_doc_ids,
                    gold_evidence_texts=gold_evidence_texts,
                    metadata={
                        "source": "hotpotqa",
                        "setting": self.setting,
                        "type": item.get("type", ""),
                        "level": item.get("level", ""),
                    },
                )
            )

        self._loaded = True

    def get_documents(self) -> list[EvalDocument]:
        self.ensure_loaded()
        return self._documents

    def get_test_cases(self) -> list[EvalTestCase]:
        self.ensure_loaded()
        return self._test_cases
