"""DeepEval RAG evaluation metrics.

This module defines the core metrics used for evaluating the RAG pipeline:
- Retrieval Quality: ContextualPrecisionMetric, ContextualRecallMetric
- Generation Quality: FaithfulnessMetric, AnswerRelevancyMetric
- Safety: HallucinationMetric
"""

from typing import List, Optional
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    HallucinationMetric,
)
from deepeval.models import AnthropicModel

from evaluation.deepeval_config import get_default_evaluator


def get_rag_metrics(
    model: Optional[AnthropicModel] = None,
    include_reason: bool = True,
    thresholds: Optional[dict] = None,
) -> List:
    """Get configured RAG evaluation metrics.

    Args:
        model: AnthropicModel instance (defaults to configured evaluator)
        include_reason: Include explanation for metric scores (default: True)
        thresholds: Custom thresholds dict (defaults to recommended values)

    Returns:
        List of configured DeepEval metrics

    Example:
        >>> metrics = get_rag_metrics()
        >>> test_case = LLMTestCase(...)
        >>> evaluate([test_case], metrics)
    """
    # Use default evaluator if not provided
    if model is None:
        model = get_default_evaluator()

    # Default thresholds based on DeepEval best practices
    default_thresholds = {
        "contextual_precision": 0.7,
        "contextual_recall": 0.7,
        "faithfulness": 0.7,
        "answer_relevancy": 0.7,
        "hallucination": 0.5,  # Lower = stricter (0.5 = max 50% hallucinated)
    }

    # Merge custom thresholds
    if thresholds:
        default_thresholds.update(thresholds)

    return [
        # Retrieval Quality Metrics
        ContextualPrecisionMetric(
            threshold=default_thresholds["contextual_precision"],
            model=model,
            include_reason=include_reason,
        ),
        ContextualRecallMetric(
            threshold=default_thresholds["contextual_recall"],
            model=model,
            include_reason=include_reason,
        ),

        # Generation Quality Metrics
        FaithfulnessMetric(
            threshold=default_thresholds["faithfulness"],
            model=model,
            include_reason=include_reason,
        ),
        AnswerRelevancyMetric(
            threshold=default_thresholds["answer_relevancy"],
            model=model,
            include_reason=include_reason,
        ),

        # Safety Metrics
        HallucinationMetric(
            threshold=default_thresholds["hallucination"],
            model=model,
            include_reason=include_reason,
        ),
    ]


def get_retrieval_metrics(
    model: Optional[AnthropicModel] = None,
    include_reason: bool = True,
) -> List:
    """Get retrieval-only metrics (faster, cheaper for retrieval testing).

    Args:
        model: AnthropicModel instance (defaults to configured evaluator)
        include_reason: Include explanation for metric scores

    Returns:
        List of retrieval-focused metrics
    """
    if model is None:
        model = get_default_evaluator()

    return [
        ContextualPrecisionMetric(
            threshold=0.7,
            model=model,
            include_reason=include_reason,
        ),
        ContextualRecallMetric(
            threshold=0.7,
            model=model,
            include_reason=include_reason,
        ),
    ]


def get_generation_metrics(
    model: Optional[AnthropicModel] = None,
    include_reason: bool = True,
) -> List:
    """Get generation-only metrics (for testing LLM output quality).

    Args:
        model: AnthropicModel instance (defaults to configured evaluator)
        include_reason: Include explanation for metric scores

    Returns:
        List of generation-focused metrics
    """
    if model is None:
        model = get_default_evaluator()

    return [
        FaithfulnessMetric(
            threshold=0.7,
            model=model,
            include_reason=include_reason,
        ),
        AnswerRelevancyMetric(
            threshold=0.7,
            model=model,
            include_reason=include_reason,
        ),
        HallucinationMetric(
            threshold=0.5,
            model=model,
            include_reason=include_reason,
        ),
    ]
