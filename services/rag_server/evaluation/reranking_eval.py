from .data_models import EvaluationSample
from .retrieval_eval import calculate_hit_rate
from pydantic import BaseModel
import math


class RerankingComparison(BaseModel):
    before_precision_at_1: float
    after_precision_at_1: float
    before_precision_at_3: float
    after_precision_at_3: float
    before_ndcg: float
    after_ndcg: float
    precision_improvement: float
    ndcg_improvement: float
    sample_count: int


class RerankingEvaluator:
    def calculate_precision_at_k(
        self, samples: list[EvaluationSample], k: int = 1
    ) -> float:
        if not samples:
            return 0.0

        total_precision = 0.0
        valid_samples = 0

        for sample in samples:
            if sample.reference and sample.retrieved_contexts:
                top_k = sample.retrieved_contexts[:k]
                relevant_in_top_k = sum(
                    1
                    for ctx in top_k
                    if sample.reference and sample.reference.lower() in ctx.lower()
                )
                total_precision += relevant_in_top_k / k
                valid_samples += 1

        return total_precision / valid_samples if valid_samples > 0 else 0.0

    def calculate_ndcg(self, samples: list[EvaluationSample], k: int = 10) -> float:
        if not samples:
            return 0.0

        ndcg_scores = []

        for sample in samples:
            if not sample.reference or not sample.retrieved_contexts:
                continue

            relevances = [
                1 if sample.reference.lower() in ctx.lower() else 0
                for ctx in sample.retrieved_contexts[:k]
            ]

            dcg = sum(
                (2**rel - 1) / math.log2(idx + 2) for idx, rel in enumerate(relevances)
            )

            ideal_relevances = sorted(relevances, reverse=True)
            idcg = sum(
                (2**rel - 1) / math.log2(idx + 2)
                for idx, rel in enumerate(ideal_relevances)
            )

            ndcg = dcg / idcg if idcg > 0 else 0.0
            ndcg_scores.append(ndcg)

        return sum(ndcg_scores) / len(ndcg_scores) if ndcg_scores else 0.0

    def compare_reranking(
        self,
        samples_before_rerank: list[EvaluationSample],
        samples_after_rerank: list[EvaluationSample],
    ) -> RerankingComparison:
        if len(samples_before_rerank) != len(samples_after_rerank):
            raise ValueError(
                "Before and after reranking samples must have the same length"
            )

        before_p1 = self.calculate_precision_at_k(samples_before_rerank, k=1)
        after_p1 = self.calculate_precision_at_k(samples_after_rerank, k=1)

        before_p3 = self.calculate_precision_at_k(samples_before_rerank, k=3)
        after_p3 = self.calculate_precision_at_k(samples_after_rerank, k=3)

        before_ndcg = self.calculate_ndcg(samples_before_rerank, k=10)
        after_ndcg = self.calculate_ndcg(samples_after_rerank, k=10)

        precision_improvement = (
            ((after_p1 - before_p1) / before_p1 * 100) if before_p1 > 0 else 0.0
        )
        ndcg_improvement = (
            ((after_ndcg - before_ndcg) / before_ndcg * 100) if before_ndcg > 0 else 0.0
        )

        return RerankingComparison(
            before_precision_at_1=before_p1,
            after_precision_at_1=after_p1,
            before_precision_at_3=before_p3,
            after_precision_at_3=after_p3,
            before_ndcg=before_ndcg,
            after_ndcg=after_ndcg,
            precision_improvement=precision_improvement,
            ndcg_improvement=ndcg_improvement,
            sample_count=len(samples_before_rerank),
        )
