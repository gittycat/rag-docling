"""Evaluation metrics for RAG systems."""

from evals.metrics.base import BaseMetric
from evals.metrics.retrieval import (
    RecallAtK,
    PrecisionAtK,
    MRR,
    NDCG,
    FusionLift,
    RerankPromotions,
    RerankDemotions,
    CandidateRecallCeiling,
    EvidenceSetRecall,
    EvidenceContainment,
    EvidenceFragmentation,
    OrphanedEvidenceRate,
)
from evals.metrics.generation import (
    Faithfulness,
    AnswerCorrectness,
    AnswerCompleteness,
    ContextualPrefixFactuality,
    AnswerRelevancy,
)
from evals.metrics.citation import (
    CitationPrecision,
    CitationRecall,
    SectionAccuracy,
)
from evals.metrics.groundedness import (
    ClaimEntailmentEvaluator,
    ClaimGroundedness,
    CitationEntailment,
    ClaimCitationSupport,
    UncitedClaimRate,
)
from evals.metrics.abstention import (
    UnanswerableAccuracy,
    FalsePositiveRate,
    FalseNegativeRate,
)
from evals.metrics.performance import (
    LatencyP50,
    LatencyP95,
    CostPerQuery,
    IngestionCostPerDocument,
    IngestionLatencyPerDocument,
)
from evals.schemas.results import MetricGroup

# Metric groups for easy selection
METRIC_GROUPS = {
    MetricGroup.RETRIEVAL: [
        RecallAtK, PrecisionAtK, MRR, NDCG,
        FusionLift, RerankPromotions, RerankDemotions, CandidateRecallCeiling,
        EvidenceSetRecall, EvidenceContainment, EvidenceFragmentation, OrphanedEvidenceRate,
    ],
    MetricGroup.GENERATION: [Faithfulness, AnswerCorrectness, AnswerCompleteness, AnswerRelevancy],
    MetricGroup.CITATION: [CitationPrecision, CitationRecall, SectionAccuracy],
    MetricGroup.GROUNDEDNESS: [
        ClaimGroundedness,
        CitationEntailment,
        ClaimCitationSupport,
        UncitedClaimRate,
        ContextualPrefixFactuality,
    ],
    MetricGroup.ABSTENTION: [UnanswerableAccuracy, FalsePositiveRate, FalseNegativeRate],
    MetricGroup.PERFORMANCE: [
        LatencyP50, LatencyP95, CostPerQuery,
        IngestionCostPerDocument, IngestionLatencyPerDocument,
    ],
}

__all__ = [
    # Base
    "BaseMetric",
    # Retrieval
    "RecallAtK",
    "PrecisionAtK",
    "MRR",
    "NDCG",
    "FusionLift",
    "RerankPromotions",
    "RerankDemotions",
    "CandidateRecallCeiling",
    "EvidenceSetRecall",
    "EvidenceContainment",
    "EvidenceFragmentation",
    "OrphanedEvidenceRate",
    # Generation
    "Faithfulness",
    "AnswerCorrectness",
    "AnswerCompleteness",
    "ContextualPrefixFactuality",
    "AnswerRelevancy",
    # Citation
    "CitationPrecision",
    "CitationRecall",
    "SectionAccuracy",
    # Groundedness
    "ClaimEntailmentEvaluator",
    "ClaimGroundedness",
    "CitationEntailment",
    "ClaimCitationSupport",
    "UncitedClaimRate",
    # Abstention
    "UnanswerableAccuracy",
    "FalsePositiveRate",
    "FalseNegativeRate",
    # Performance
    "LatencyP50",
    "LatencyP95",
    "CostPerQuery",
    "IngestionCostPerDocument",
    "IngestionLatencyPerDocument",
    # Groups
    "METRIC_GROUPS",
]
