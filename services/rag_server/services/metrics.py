"""Service for gathering RAG system metrics and configuration.

Provides methods to:
- Query model information from TEI/HuggingFace
- Gather retrieval configuration
- Get system overview metrics

Note: Evaluation-related functions have been moved to services/eval/.
"""

import logging

import httpx

from schemas.metrics import (
    ModelInfo,
    ModelSize,
    ModelsConfig,
    ChunkerInfo,
    VectorSearchConfig,
    BM25Config,
    HybridSearchConfig,
    ContextualRetrievalConfig,
    RerankerConfig,
    RetrievalConfig,
    SystemMetrics,
)
from infrastructure.config.models_config import (
    ExecutionBoundary,
    effective_reranker_top_n,
)
from pipelines.inference import get_inference_config
from pipelines.ingestion import (
    SIMPLE_TEXT_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    get_chunking_config,
    get_ingestion_config,
)

logger = logging.getLogger(__name__)

# Model reference URLs
MODEL_REFERENCES = {
    "Qwen/Qwen3-Embedding-0.6B": {
        "url": "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B",
        "description": "Qwen3 Embedding 0.6B - self-hosted via TEI (1024 dims)",
        "parameters": "0.6B",
    },
    # HuggingFace reranker models
    "cross-encoder/ms-marco-MiniLM-L-6-v2": {
        "url": "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2",
        "description": "MS MARCO MiniLM L-6 - Fast cross-encoder for passage reranking",
        "parameters": "22M",
        "disk_size_mb": 80,
    },
    "BAAI/bge-reranker-base": {
        "url": "https://huggingface.co/BAAI/bge-reranker-base",
        "description": "BGE Reranker Base - High-quality Chinese/English reranker",
        "parameters": "278M",
        "disk_size_mb": 1100,
    },
    # Anthropic eval models
    "claude-sonnet-4-20250514": {
        "url": "https://docs.anthropic.com/en/docs/about-claude/models",
        "description": "Claude Sonnet 4 - Fast, intelligent model for evaluation tasks",
        "parameters": "Unknown",
        "context_window": 200000,
    },
    "claude-3-5-sonnet-20241022": {
        "url": "https://docs.anthropic.com/en/docs/about-claude/models",
        "description": "Claude 3.5 Sonnet - Balanced performance and cost for evals",
        "parameters": "Unknown",
        "context_window": 200000,
    },
}


async def get_tei_model_info(base_url: str) -> dict | None:
    """Query TEI's /info endpoint for the currently loaded model's details."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/info")
            if response.status_code == 200:
                return response.json()
    except Exception as e:
        logger.warning(f"Failed to get TEI model info at {base_url}: {e}")

    return None


def get_model_reference(model_name: str) -> dict:
    """Get reference information for a model."""
    if model_name in MODEL_REFERENCES:
        return MODEL_REFERENCES[model_name]

    base_name = model_name.split(":")[0]
    for key, value in MODEL_REFERENCES.items():
        if key.startswith(base_name):
            return value

    return {
        "url": None,
        "description": f"Model: {model_name}",
        "parameters": "Unknown",
    }


def _key_status(requires_api_key: bool, api_key: str | None) -> str:
    # A provider that needs no key is reachable as configured; one that does is
    # only reachable once the key resolved at config load. No provider is
    # singled out here — the old code asked has_anthropic_key() no matter which
    # judge was actually configured.
    if requires_api_key and not api_key:
        return "unavailable"
    return "available"


async def get_models_config() -> ModelsConfig:
    """Get complete models configuration with details."""
    from infrastructure.config.models_config import get_models_config as get_config

    config = get_config()
    llm_model = config.llm.model
    embedding_model = config.embedding.model
    eval_model = config.eval.model

    inference_config = get_inference_config()

    # Get LLM info. Ollama's local /api/show and /api/ps introspection is gone;
    # vllm and the cloud providers have no equivalent generic status probe here.
    llm_ref = get_model_reference(llm_model)
    llm_size = ModelSize(
        parameters=llm_ref.get("parameters"),
        context_window=llm_ref.get("context_window"),
    )

    llm_info = ModelInfo(
        name=llm_model,
        provider=config.llm.provider.capitalize(),
        model_type="llm",
        execution_boundary=config.llm.execution_boundary,
        size=llm_size,
        reference_url=llm_ref.get("url"),
        description=llm_ref.get("description"),
        status=_key_status(config.llm.requires_api_key, config.llm.api_key),
    )

    # Get embedding info. TEI's /info endpoint reports the currently loaded model.
    embed_ref = get_model_reference(embedding_model)
    embed_tei_info = None
    if config.embedding.provider == "tei" and config.embedding.base_url:
        embed_tei_info = await get_tei_model_info(config.embedding.base_url)

    embed_size = ModelSize(
        parameters=embed_ref.get("parameters"),
        context_window=(
            embed_tei_info.get("max_input_length")
            if embed_tei_info
            else embed_ref.get("context_window")
        ),
    )

    embedding_info = ModelInfo(
        name=embedding_model,
        provider=config.embedding.provider.capitalize(),
        model_type="embedding",
        execution_boundary=config.embedding.execution_boundary,
        size=embed_size,
        reference_url=embed_ref.get("url"),
        description=embed_ref.get("description"),
        # TEI is the one embedding provider with a live probe; for the rest,
        # "reachable" is only a question of whether the key resolved.
        status=(
            ("available" if embed_tei_info is not None else "unavailable")
            if config.embedding.provider == "tei"
            else _key_status(config.embedding.requires_api_key, config.embedding.api_key)
        ),
    )

    # Get reranker info (if enabled)
    reranker_info = None
    if inference_config["reranker_enabled"]:
        reranker_model = inference_config["reranker_model"]
        reranker_ref = get_model_reference(reranker_model)

        reranker_size = ModelSize(
            parameters=reranker_ref.get("parameters"),
            disk_size_mb=reranker_ref.get("disk_size_mb"),
        )

        reranker_info = ModelInfo(
            name=reranker_model,
            provider="HuggingFace",
            model_type="reranker",
            # Not read from config and not inferred from a provider string: the
            # reranker has no endpoint at all. SentenceTransformerRerank loads the
            # weights into this process, so it executes wherever rag-server does.
            execution_boundary=ExecutionBoundary.CUSTOMER_MANAGED,
            size=reranker_size,
            reference_url=reranker_ref.get("url"),
            description=reranker_ref.get("description"),
            status="available",
        )

    # Get eval model info
    eval_ref = get_model_reference(eval_model)
    eval_size = ModelSize(
        parameters=eval_ref.get("parameters"),
        context_window=eval_ref.get("context_window"),
    )

    eval_info = ModelInfo(
        name=eval_model,
        provider=config.eval.provider.capitalize(),
        model_type="eval",
        execution_boundary=config.eval.execution_boundary,
        size=eval_size,
        reference_url=eval_ref.get("url"),
        description=eval_ref.get("description"),
        status=_key_status(config.eval.requires_api_key, config.eval.api_key),
    )

    return ModelsConfig(
        llm=llm_info,
        embedding=embedding_info,
        reranker=reranker_info,
        eval=eval_info,
    )


def get_retrieval_config() -> RetrievalConfig:
    """Get complete retrieval pipeline configuration."""
    inference_config = get_inference_config()
    ingestion_config = get_ingestion_config()
    chunking = get_chunking_config()

    # Both chunkers are reported, each with only the parameters it has. The
    # SentenceSplitter numbers used to be literals here, unrelated to the ones
    # the pipeline used, and the eval runner recorded them as measured config.
    chunkers = [
        ChunkerInfo(
            name="sentence_splitter",
            applies_to=sorted(SIMPLE_TEXT_EXTENSIONS),
            chunk_size=chunking["chunk_size"],
            chunk_overlap=chunking["chunk_overlap"],
        ),
        ChunkerInfo(
            name="docling",
            applies_to=sorted(SUPPORTED_EXTENSIONS - SIMPLE_TEXT_EXTENSIONS),
            # Docling splits on document structure; it has no size or overlap.
            chunk_size=None,
            chunk_overlap=None,
        ),
    ]

    vector_config = VectorSearchConfig(
        enabled=True,
        chunkers=chunkers,
        chunk_size=chunking["chunk_size"],
        chunk_overlap=chunking["chunk_overlap"],
        vector_store="pgvector",
        index_type="diskann",
        table_name="document_chunks",
    )

    bm25_config = BM25Config(
        enabled=inference_config["hybrid_search_enabled"],
    )

    hybrid_search_config = HybridSearchConfig(
        enabled=inference_config["hybrid_search_enabled"],
        bm25=bm25_config,
        vector=vector_config,
        fusion_method="reciprocal_rank_fusion",
        rrf_k=inference_config["rrf_k"],
    )

    contextual_retrieval_config = ContextualRetrievalConfig(
        enabled=ingestion_config["contextual_retrieval_enabled"],
    )

    top_k = inference_config["retrieval_top_k"]
    top_n = (
        effective_reranker_top_n(inference_config["reranker_top_n"], top_k)
        if inference_config["reranker_enabled"]
        else top_k
    )

    reranker_cfg = RerankerConfig(
        enabled=inference_config["reranker_enabled"],
        model=(
            inference_config["reranker_model"]
            if inference_config["reranker_enabled"]
            else None
        ),
        top_n=top_n if inference_config["reranker_enabled"] else None,
    )

    return RetrievalConfig(
        retrieval_top_k=top_k,
        final_top_n=top_n,
        hybrid_search=hybrid_search_config,
        contextual_retrieval=contextual_retrieval_config,
        reranker=reranker_cfg,
    )


async def _check_bm25() -> str:
    """Probe the BM25 index, then fold in the last live retrieval outcome.

    "unavailable" = the extension/index cannot be queried at all.
    "unhealthy"   = the probe works but the most recent real search failed.
    """
    from infrastructure.database.postgres import get_session
    from infrastructure.search.bm25_retriever import get_bm25_health, probe_bm25

    try:
        async with get_session() as session:
            probe = await probe_bm25(session)
    except Exception as e:
        logger.error(f"BM25 health check error: {e}")
        return "unavailable"

    if probe["status"] != "healthy":
        return "unavailable"

    health = get_bm25_health()
    if health["status"] == "unhealthy":
        logger.warning(
            f"BM25 index is queryable but the last search failed "
            f"({health['consecutive_failures']} consecutive): {health['last_error']}"
        )
        return "unhealthy"
    return "healthy"


async def _check_vector_store() -> str:
    """Probe the pgvector index, then fold in the last live retrieval outcome.

    "unavailable" = the extension/index cannot be queried at all.
    "unhealthy"   = the probe works but the most recent real search failed.
    """
    from infrastructure.database.postgres import get_session
    from infrastructure.search.vector_retriever import get_vector_health, probe_vector_index

    try:
        async with get_session() as session:
            probe = await probe_vector_index(session)
    except Exception as e:
        logger.error(f"Vector store health check error: {e}")
        return "unavailable"

    if probe["status"] != "healthy":
        return "unavailable"

    health = get_vector_health()
    if health["status"] == "unhealthy":
        logger.warning(
            f"Vector index is queryable but the last search failed "
            f"({health['consecutive_failures']} consecutive): {health['last_error']}"
        )
        return "unhealthy"
    return "healthy"


async def get_system_metrics() -> SystemMetrics:
    """Get complete system metrics overview."""
    from infrastructure.database.postgres import get_session
    from infrastructure.database import documents as db_docs

    models = await get_models_config()
    retrieval = get_retrieval_config()

    try:
        async with get_session() as session:
            documents = await db_docs.list_documents(session)
        doc_count = len(documents)
        chunk_count = sum(d.get("chunks", 0) for d in documents)
    except Exception as e:
        logger.warning(f"Failed to get document stats: {e}")
        doc_count = 0
        chunk_count = 0

    component_status = {}

    # Check PostgreSQL
    try:
        from sqlalchemy import text
        from infrastructure.database.postgres import get_engine
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        component_status["postgres"] = "healthy"
    except Exception as e:
        logger.warning(f"PostgreSQL health check error: {e}")
        component_status["postgres"] = "unavailable"

    # Check BM25 (pg_textsearch extension + index). Only meaningful when hybrid
    # search is on; without this a broken index silently turns every hybrid query
    # into a vector-only one.
    if retrieval.hybrid_search.enabled:
        component_status["bm25"] = await _check_bm25()

    # Check the vector half of retrieval (pgvector extension + diskann index).
    # Unlike BM25 this is always meaningful: with hybrid search off it is the
    # only retriever, and with it on a broken index degrades queries to BM25-only.
    component_status["vector_store"] = await _check_vector_store()

    # Check TEI (only meaningful when the active embedding provider is local)
    from infrastructure.config.models_config import get_models_config as get_config

    embedding_config = get_config().embedding
    if embedding_config.provider == "tei" and embedding_config.base_url:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{embedding_config.base_url.rstrip('/')}/health")
                if resp.status_code == 200:
                    component_status["tei"] = "healthy"
                else:
                    logger.warning(f"TEI health check failed: status={resp.status_code}")
                    component_status["tei"] = "unhealthy"
        except Exception as e:
            logger.warning(f"TEI health check error: {e}")
            component_status["tei"] = "unavailable"

    health_status = (
        "healthy"
        if all(s == "healthy" for s in component_status.values())
        else "degraded"
    )

    return SystemMetrics(
        models=models,
        retrieval=retrieval,
        document_count=doc_count,
        chunk_count=chunk_count,
        health_status=health_status,
        component_status=component_status,
    )
