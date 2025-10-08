from datasets import Dataset
from ragas import evaluate
from ragas.metrics import context_precision, context_recall, context_entity_recall
from .data_models import EvaluationSample, RetrievalEvaluationResult
from .ragas_config import RagasOllamaConfig
import asyncio


class RetrievalEvaluator:
    def __init__(self, config: RagasOllamaConfig):
        self.config = config
        self.metrics = [context_precision, context_recall]

    def prepare_dataset(self, samples: list[EvaluationSample]) -> Dataset:
        data_dict = {
            "user_input": [],
            "retrieved_contexts": [],
            "reference": [],
        }

        for sample in samples:
            data_dict["user_input"].append(sample.user_input)
            data_dict["retrieved_contexts"].append(sample.retrieved_contexts)
            data_dict["reference"].append(sample.reference or "")

        return Dataset.from_dict(data_dict)

    async def evaluate_async(self, samples: list[EvaluationSample]) -> RetrievalEvaluationResult:
        if not samples:
            raise ValueError("No samples provided for evaluation")

        dataset = self.prepare_dataset(samples)

        evaluator_config = self.config.get_evaluator_config()
        result = evaluate(
            dataset,
            metrics=self.metrics,
            llm=evaluator_config["llm"],
            embeddings=evaluator_config["embeddings"],
        )

        df = result.to_pandas()

        return RetrievalEvaluationResult(
            context_precision=df["context_precision"].mean() if "context_precision" in df.columns else None,
            context_recall=df["context_recall"].mean() if "context_recall" in df.columns else None,
            sample_count=len(samples),
            per_sample_results=df.to_dict("records"),
        )

    def evaluate(self, samples: list[EvaluationSample]) -> RetrievalEvaluationResult:
        return asyncio.run(self.evaluate_async(samples))


def calculate_hit_rate(samples: list[EvaluationSample], k: int = 10) -> float:
    if not samples:
        return 0.0

    hits = 0
    for sample in samples:
        if sample.reference:
            top_k_contexts = sample.retrieved_contexts[:k]
            if any(sample.reference.lower() in context.lower() for context in top_k_contexts):
                hits += 1

    return hits / len(samples)


def calculate_mrr(samples: list[EvaluationSample]) -> float:
    if not samples:
        return 0.0

    reciprocal_ranks = []
    for sample in samples:
        if sample.reference:
            for idx, context in enumerate(sample.retrieved_contexts, start=1):
                if sample.reference.lower() in context.lower():
                    reciprocal_ranks.append(1 / idx)
                    break
            else:
                reciprocal_ranks.append(0.0)

    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
