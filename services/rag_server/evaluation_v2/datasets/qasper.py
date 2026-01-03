"""Qasper dataset loader for evaluation v2."""

import hashlib
from datasets import load_dataset

from evaluation_v2.data_models import (
    EvaluationDataset,
    DatasetInfo,
    EvalDocument,
    EvalTestCase,
)


class QasperDataset(EvaluationDataset):
    """Qasper loader for long-form, evidence-grounded QA."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._documents: list[EvalDocument] = []
        self._test_cases: list[EvalTestCase] = []

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name="Qasper",
            description="Evidence-grounded QA over long scientific documents",
            source_url="https://huggingface.co/datasets/qasper",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_evidence=True,
            domains=["Scientific"],
            license="CC BY 4.0",
        )

    def load(self) -> None:
        dataset = load_dataset(
            "qasper",
            split=self.split,
            cache_dir=str(self.cache_dir),
        )

        if self.sample_size:
            dataset = dataset.select(range(min(self.sample_size, len(dataset))))

        for item in dataset:
            paper_id = item.get("paper_id") or hashlib.md5(
                str(item.get("title", "")).encode()
            ).hexdigest()[:12]
            doc_id = f"qasper-{paper_id}"

            full_text = item.get("full_text")
            if isinstance(full_text, list):
                content = "\n\n".join(
                    part for part in full_text if isinstance(part, str)
                )
            else:
                content = full_text or item.get("abstract", "") or ""

            if content:
                self._documents.append(
                    EvalDocument(
                        doc_id=doc_id,
                        content=content,
                        metadata={"source": "qasper", "title": item.get("title", "")},
                    )
                )

            qas = item.get("qas", [])
            for qa in qas:
                question = qa.get("question", "")
                answers = qa.get("answers", [])

                expected_answer = ""
                gold_evidence_texts: list[str] = []
                for ans in answers:
                    if isinstance(ans, dict):
                        expected_answer = ans.get("answer", "") or ans.get("answer_text", "")
                        evidence = ans.get("evidence", [])
                        if isinstance(evidence, list):
                            for ev in evidence:
                                if isinstance(ev, str):
                                    gold_evidence_texts.append(ev)
                                elif isinstance(ev, dict):
                                    ev_text = ev.get("text") or ev.get("evidence_text")
                                    if ev_text:
                                        gold_evidence_texts.append(ev_text)
                    if expected_answer:
                        break

                if not question:
                    continue

                self._test_cases.append(
                    EvalTestCase(
                        question=question,
                        expected_answer=expected_answer,
                        gold_document_ids=[doc_id],
                        gold_evidence_texts=gold_evidence_texts,
                        metadata={"source": "qasper"},
                    )
                )

        self._loaded = True

    def get_documents(self) -> list[EvalDocument]:
        self.ensure_loaded()
        return self._documents

    def get_test_cases(self) -> list[EvalTestCase]:
        self.ensure_loaded()
        return self._test_cases
