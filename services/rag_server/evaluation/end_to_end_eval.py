from .data_models import EvaluationSample, EndToEndEvaluationResult
from .retrieval_eval import RetrievalEvaluator
from .generation_eval import GenerationEvaluator
from .ragas_config import RagasOllamaConfig, create_default_ragas_config
import asyncio


class EndToEndEvaluator:
    def __init__(self, config: RagasOllamaConfig | None = None):
        self.config = config or create_default_ragas_config()
        self.retrieval_evaluator = RetrievalEvaluator(self.config)
        self.generation_evaluator = GenerationEvaluator(self.config)

    async def evaluate_async(
        self, samples: list[EvaluationSample], include_correctness: bool = True
    ) -> EndToEndEvaluationResult:
        if not samples:
            raise ValueError("No samples provided for evaluation")

        retrieval_result = await self.retrieval_evaluator.evaluate_async(samples)
        generation_result = await self.generation_evaluator.evaluate_async(
            samples, include_correctness
        )

        overall_score = self._calculate_overall_score(
            retrieval_result, generation_result
        )

        return EndToEndEvaluationResult(
            retrieval=retrieval_result,
            generation=generation_result,
            overall_score=overall_score,
            sample_count=len(samples),
        )

    def evaluate(
        self, samples: list[EvaluationSample], include_correctness: bool = True
    ) -> EndToEndEvaluationResult:
        return asyncio.run(self.evaluate_async(samples, include_correctness))

    def _calculate_overall_score(self, retrieval_result, generation_result) -> float:
        scores = []

        if retrieval_result.context_precision is not None:
            scores.append(retrieval_result.context_precision)
        if retrieval_result.context_recall is not None:
            scores.append(retrieval_result.context_recall)
        if generation_result.faithfulness is not None:
            scores.append(generation_result.faithfulness)
        if generation_result.answer_relevancy is not None:
            scores.append(generation_result.answer_relevancy)

        return sum(scores) / len(scores) if scores else 0.0
