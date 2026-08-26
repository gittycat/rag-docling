import os
from fastapi import APIRouter

from schemas.health import ModelsInfoResponse, ConfigResponse
from pipelines.inference import get_inference_config
from infrastructure.config.models_config import get_models_config
from services.pricing import resolve_rates

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/models/info", response_model=ModelsInfoResponse)
async def get_models_info():
    """Get information about the models used in the RAG system"""
    models_config = get_models_config()
    llm_model = models_config.llm.model
    llm_provider = models_config.llm.provider

    # Read the declared boundary rather than inferring it from the provider name:
    # an OpenAI-compatible transport points at a self-hosted vLLM or at a vendor,
    # so the provider string does not determine where the model executes.
    llm_execution_boundary = models_config.llm.execution_boundary

    # Rates come from services/pricing.py, and an unrecognised model is reported
    # as unpriced (null) rather than free. The table that used to live inline here
    # had no entry for the currently configured model and answered $0 for it.
    cost_rates = resolve_rates(llm_model)

    # Read from config.yml, not an EMBEDDING_MODEL env var: no compose file ever
    # set that variable, so this reported "unknown" and made eval provenance
    # untrustworthy (docs/suggestions.md §6). config.yml is the single source of
    # truth the embedding client itself is built from.
    embedding_model = models_config.embedding.model

    inference_config = get_inference_config()
    reranker_enabled = inference_config['reranker_enabled']
    reranker_model = inference_config['reranker_model'] if reranker_enabled else None

    return ModelsInfoResponse(
        llm_model=llm_model,
        llm_provider=llm_provider,
        llm_execution_boundary=llm_execution_boundary,
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        reranker_enabled=reranker_enabled,
        cost_per_1m_input_tokens=cost_rates.input_per_1m if cost_rates else None,
        cost_per_1m_output_tokens=cost_rates.output_per_1m if cost_rates else None,
        cost_rate_source=cost_rates.source if cost_rates else "unpriced",
    )


@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """Get configuration settings for the RAG system"""
    max_upload_size = int(os.getenv("MAX_UPLOAD_SIZE", "80"))

    return ConfigResponse(
        max_upload_size_mb=max_upload_size
    )
