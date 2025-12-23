import os
from fastapi import APIRouter

from schemas.health import ModelsInfoResponse, ConfigResponse
from pipelines.inference import get_inference_config

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/models/info", response_model=ModelsInfoResponse)
async def get_models_info():
    """Get information about the models used in the RAG system"""
    llm_model = os.getenv("LLM_MODEL", "unknown")
    embedding_model = os.getenv("EMBEDDING_MODEL", "unknown")

    inference_config = get_inference_config()
    reranker_enabled = inference_config['reranker_enabled']
    reranker_model = inference_config['reranker_model'] if reranker_enabled else None

    return ModelsInfoResponse(
        llm_model=llm_model,
        llm_hosting="Ollama (local)",
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        reranker_enabled=reranker_enabled
    )


@router.get("/config", response_model=ConfigResponse)
async def get_config():
    """Get configuration settings for the RAG system"""
    max_upload_size = int(os.getenv("MAX_UPLOAD_SIZE", "80"))

    return ConfigResponse(
        max_upload_size_mb=max_upload_size
    )
