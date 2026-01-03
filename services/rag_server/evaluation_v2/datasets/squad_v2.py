"""SQuAD v2 dataset loader for evaluation v2."""

import hashlib
from datasets import load_dataset

from evaluation_v2.data_models import (
    EvaluationDataset,
    DatasetInfo,
    EvalDocument,
    EvalTestCase,
)


class SquadV2Dataset(EvaluationDataset):
    """SQuAD v2 loader with unanswerable questions."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._documents: list[EvalDocument] = []
        self._test_cases: list[EvalTestCase] = []

    @property
    def info(self) -> DatasetInfo:
        self.ensure_loaded()
        return DatasetInfo(
            name="SQuAD v2",
            description="SQuAD with unanswerable questions",
            source_url="https://huggingface.co/datasets/rajpurkar/squad_v2",
            num_documents=len(self._documents),
            num_test_cases=len(self._test_cases),
            has_gold_evidence=True,
            domains=["Wikipedia"],
            license="CC BY-SA 4.0",
        )

    def load(self) -> None:
        dataset = load_dataset(
            "rajpurkar/squad_v2",
            split=self.split,
            cache_dir=str(self.cache_dir),
        )

        if self.sample_size:
            dataset = dataset.select(range(min(self.sample_size, len(dataset))))

        seen_contexts: set[str] = set()

        for item in dataset:
            context = item.get("context", "")
            question = item.get("question", "")
            answers = item.get("answers", {})

            if not context or not question:
                continue

            context_hash = hashlib.md5(context.encode()).hexdigest()[:12]
            doc_id = f"squad-{context_hash}"

            if context_hash not in seen_contexts:
                seen_contexts.add(context_hash)
                self._documents.append(
                    EvalDocument(
                        doc_id=doc_id,
                        content=context,
                        metadata={"source": "squad_v2", "title": item.get("title", "")},
                    )
                )

            answer_texts = answers.get("text", []) if isinstance(answers, dict) else []
            expected_answer = answer_texts[0] if answer_texts else ""
            gold_evidence = [expected_answer] if expected_answer else []

            self._test_cases.append(
                EvalTestCase(
                    question=question,
                    expected_answer=expected_answer,
                    gold_document_ids=[doc_id],
                    gold_evidence_texts=gold_evidence,
                    metadata={
                        "source": "squad_v2",
                        "is_answerable": bool(expected_answer),
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
