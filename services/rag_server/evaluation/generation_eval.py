from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, answer_correctness
from .data_models import EvaluationSample, GenerationEvaluationResult
from .ragas_config import RagasOllamaConfig
import asyncio


class GenerationEvaluator:
    def __init__(self, config: RagasOllamaConfig):
        self.config = config
        self.metrics = [faithfulness, answer_relevancy]

    def prepare_dataset(self, samples: list[EvaluationSample]) -> Dataset:
        data_dict = {
            "user_input": [],
            "retrieved_contexts": [],
            "response": [],
            "reference": [],
        }

        for sample in samples:
            data_dict["user_input"].append(sample.user_input)
            data_dict["retrieved_contexts"].append(sample.retrieved_contexts)
            data_dict["response"].append(sample.response)
            data_dict["reference"].append(sample.reference or "")

        return Dataset.from_dict(data_dict)

    async def evaluate_async(
        self, samples: list[EvaluationSample], include_correctness: bool = True
    ) -> GenerationEvaluationResult:
        if not samples:
            raise ValueError("No samples provided for evaluation")

        metrics = self.metrics.copy()
        if include_correctness and all(s.reference for s in samples):
            metrics.append(answer_correctness)

        dataset = self.prepare_dataset(samples)

        evaluator_config = self.config.get_evaluator_config()
        result = evaluate(
            dataset,
            metrics=metrics,
            llm=evaluator_config["llm"],
            embeddings=evaluator_config["embeddings"],
        )

        df = result.to_pandas()

        return GenerationEvaluationResult(
            faithfulness=df["faithfulness"].mean()
            if "faithfulness" in df.columns
            else None,
            answer_relevancy=df["answer_relevancy"].mean()
            if "answer_relevancy" in df.columns
            else None,
            answer_correctness=df["answer_correctness"].mean()
            if "answer_correctness" in df.columns
            else None,
            sample_count=len(samples),
            per_sample_results=df.to_dict("records"),
        )

    def evaluate(
        self, samples: list[EvaluationSample], include_correctness: bool = True
    ) -> GenerationEvaluationResult:
        return asyncio.run(self.evaluate_async(samples, include_correctness))
