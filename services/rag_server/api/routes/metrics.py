import logging
from fastapi import APIRouter, HTTPException

from schemas.metrics import (
    SystemMetrics,
    ModelsConfig,
    RetrievalConfig,
    MetricDefinition,
    EvaluationHistory,
    EvaluationSummary,
)
from services.metrics import (
    get_system_metrics as fetch_system_metrics,
    get_models_config,
    get_retrieval_config,
    get_metric_definitions,
    load_evaluation_history,
    get_evaluation_summary as fetch_eval_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/metrics/system", response_model=SystemMetrics)
async def get_system_metrics():
    """Get complete system metrics and configuration overview.

    Returns comprehensive information about:
    - All models (LLM, embedding, reranker, eval) with sizes and references
    - Retrieval pipeline configuration (hybrid search, BM25, reranking)
    - Evaluation metrics definitions
    - Latest evaluation results
    - Document statistics
    - Component health status
    """
    try:
        return await fetch_system_metrics()
    except Exception as e:
        logger.error(f"[METRICS] Error fetching system metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/models", response_model=ModelsConfig)
async def get_detailed_models_info():
    """Get detailed information about all models used in the RAG system.

    Returns for each model (LLM, embedding, reranker, eval):
    - Model name and provider
    - Size information (parameters, disk size, context window)
    - Reference URL to model documentation
    - Current status (loaded, available, unavailable)
    """
    try:
        return await get_models_config()
    except Exception as e:
        logger.error(f"[METRICS] Error fetching models config: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/retrieval", response_model=RetrievalConfig)
async def get_retrieval_configuration():
    """Get retrieval pipeline configuration.

    Returns configuration for:
    - Hybrid search (BM25 + Vector + RRF fusion)
    - Contextual retrieval (Anthropic method)
    - Reranking settings
    - Top-K and Top-N parameters
    - Research references and improvement claims
    """
    try:
        return get_retrieval_config()
    except Exception as e:
        logger.error(f"[METRICS] Error fetching retrieval config: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/evaluation/definitions", response_model=list[MetricDefinition])
async def get_evaluation_metric_definitions():
    """Get definitions for all evaluation metrics.

    Returns for each metric:
    - Name and category (retrieval, generation, safety)
    - Description of what it measures
    - Pass/fail threshold
    - Interpretation guide
    - Reference documentation URL
    """
    try:
        return get_metric_definitions()
    except Exception as e:
        logger.error(f"[METRICS] Error fetching metric definitions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/evaluation/history", response_model=EvaluationHistory)
async def get_evaluation_history(limit: int = 20):
    """Get historical evaluation runs.

    Args:
        limit: Maximum number of runs to return (default: 20)

    Returns:
        List of evaluation runs with detailed results and metrics
    """
    try:
        return load_evaluation_history(limit=limit)
    except Exception as e:
        logger.error(f"[METRICS] Error fetching evaluation history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics/evaluation/summary", response_model=EvaluationSummary)
async def get_evaluation_summary():
    """Get evaluation summary with trends.

    Returns:
    - Latest evaluation run
    - Total number of runs
    - Metric trends over time (improving/declining/stable)
    - Best performing run
    """
    try:
        return fetch_eval_summary()
    except Exception as e:
        logger.error(f"[METRICS] Error fetching evaluation summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
