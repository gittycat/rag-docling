"""Tests for the metrics and configuration API endpoints.

Tests the following endpoints:
- GET /metrics/system
- GET /metrics/models
- GET /metrics/retrieval
- GET /metrics/eval/definitions
- GET /metrics/eval/runs
- GET /metrics/eval/summary
"""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.config.models_config import (
    ChunkingConfig,
    ExecutionBoundary,
    ModelsConfig,
    LLMConfig,
    EmbeddingConfig,
    EvalConfig,
    RerankerConfig,
    RetrievalConfig,
)


def create_mock_models_config():
    """Create a mock ModelsConfig for tests (uses vllm/tei, no API key required)."""
    return ModelsConfig(
        llm=LLMConfig(
            provider="vllm",
            model="Qwen/Qwen2.5-14B-Instruct",
            base_url="http://vllm:8000/v1",
            timeout=120,
            execution_boundary=ExecutionBoundary.CUSTOMER_MANAGED,
        ),
        embedding=EmbeddingConfig(
            provider="tei",
            model="Qwen/Qwen3-Embedding-0.6B",
            base_url="http://tei:80",
            execution_boundary=ExecutionBoundary.CUSTOMER_MANAGED,
        ),
        eval=EvalConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            api_key="test-key",
            requires_api_key=True,
            execution_boundary=ExecutionBoundary.THIRD_PARTY,
        ),
        reranker=RerankerConfig(enabled=True),
        retrieval=RetrievalConfig(),
    )


from main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_models_config_fixture():
    """Auto-use fixture to mock models config for all tests in this file."""
    mock_config = create_mock_models_config()
    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=mock_config,
    ):
        with patch(
            "infrastructure.config.models_config._default_manager._config",
            mock_config,
        ):
            yield mock_config


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_tei():
    """Mock TEI's /info and /health API responses."""
    with patch('services.metrics.httpx.AsyncClient') as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model_id": "Qwen/Qwen3-Embedding-0.6B",
            "max_input_length": 8192,
        }

        # Create async context manager mock
        async_client_instance = AsyncMock()
        async_client_instance.post.return_value = mock_response
        async_client_instance.get.return_value = mock_response
        async_client_instance.__aenter__.return_value = async_client_instance
        async_client_instance.__aexit__.return_value = None

        mock_client.return_value = async_client_instance

        yield mock_client


@pytest.fixture
def mock_system_metrics():
    """Mock the get_system_metrics function to return test data."""
    from schemas.metrics import (
        SystemMetrics,
        ModelsConfig,
        ModelInfo,
        ModelSize,
        RetrievalConfig,
        HybridSearchConfig,
        BM25Config,
        VectorSearchConfig,
        ContextualRetrievalConfig,
        RerankerConfig,
    )

    mock_metrics = SystemMetrics(
        system_name="ragbench",
        version="1.0.0",
        models=ModelsConfig(
            llm=ModelInfo(
                name="Qwen/Qwen2.5-14B-Instruct",
                provider="Vllm",
                model_type="llm",
                execution_boundary=ExecutionBoundary.CUSTOMER_MANAGED,
                size=ModelSize(parameters="14B"),
                reference_url=None,
                description="Test LLM",
                status="available",
            ),
            embedding=ModelInfo(
                name="Qwen/Qwen3-Embedding-0.6B",
                provider="Tei",
                model_type="embedding",
                execution_boundary=ExecutionBoundary.CUSTOMER_MANAGED,
                size=ModelSize(parameters="0.6B"),
                reference_url="https://huggingface.co/Qwen/Qwen3-Embedding-0.6B",
                description="Test embeddings",
                status="available",
            ),
            reranker=ModelInfo(
                name="cross-encoder/ms-marco-MiniLM-L-6-v2",
                provider="HuggingFace",
                model_type="reranker",
                execution_boundary=ExecutionBoundary.CUSTOMER_MANAGED,
                size=ModelSize(parameters="22M", disk_size_mb=80),
                reference_url="https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2",
                description="Test reranker",
                status="available",
            ),
            eval=ModelInfo(
                name="claude-sonnet-4-20250514",
                provider="Anthropic",
                model_type="eval",
                execution_boundary=ExecutionBoundary.THIRD_PARTY,
                reference_url="https://docs.anthropic.com",
                description="Test eval",
                status="available",
            ),
        ),
        retrieval=RetrievalConfig(
            retrieval_top_k=10,
            final_top_n=5,
            hybrid_search=HybridSearchConfig(
                enabled=True,
                bm25=BM25Config(enabled=True),
                vector=VectorSearchConfig(
                    enabled=True,
                    chunk_size=500,
                    chunk_overlap=50,
                    vector_store="pgvector",
                    index_type="diskann",
                    table_name="document_chunks",
                ),
                fusion_method="reciprocal_rank_fusion",
                rrf_k=60,
            ),
            contextual_retrieval=ContextualRetrievalConfig(enabled=False),
            reranker=RerankerConfig(
                enabled=True,
                model="cross-encoder/ms-marco-MiniLM-L-6-v2",
                top_n=5,
            ),
        ),
        document_count=2,
        chunk_count=15,
        health_status="healthy",
        component_status={"postgres": "healthy", "tei": "healthy"},
    )

    async def mock_get_system_metrics():
        return mock_metrics

    with patch('services.metrics.get_system_metrics', mock_get_system_metrics):
        yield mock_metrics


@pytest.fixture
def mock_env_vars():
    """Mock environment variables."""
    env_vars = {
        'LLM_MODEL': 'Qwen/Qwen2.5-14B-Instruct',
        'EMBEDDING_MODEL': 'Qwen/Qwen3-Embedding-0.6B',
        'EVAL_MODEL': 'claude-sonnet-4-20250514',
        'ENABLE_RERANKER': 'true',
        'RERANKER_MODEL': 'cross-encoder/ms-marco-MiniLM-L-6-v2',
        'ENABLE_HYBRID_SEARCH': 'true',
        'RRF_K': '60',
        'RETRIEVAL_TOP_K': '10',
        'ENABLE_CONTEXTUAL_RETRIEVAL': 'false',
        'DATABASE_HOST': 'localhost',
        'DATABASE_PORT': '5432',
        'DATABASE_NAME': 'ragbench',
    }
    with patch.dict('os.environ', env_vars):
        yield env_vars


# ============================================================================
# Models Endpoint Tests
# ============================================================================

def test_models_endpoint_returns_200(mock_tei, mock_env_vars):
    """GET /metrics/models should return 200."""
    response = client.get("/metrics/models")
    assert response.status_code == 200


def test_models_endpoint_returns_llm_info(mock_tei, mock_env_vars):
    """GET /metrics/models should include LLM model info."""
    response = client.get("/metrics/models")
    data = response.json()

    assert "llm" in data
    assert data["llm"]["name"] == "Qwen/Qwen2.5-14B-Instruct"
    assert data["llm"]["provider"] == "Vllm"
    assert data["llm"]["model_type"] == "llm"
    assert data["llm"]["execution_boundary"] == "customer_managed"


def test_models_endpoint_returns_embedding_info(mock_tei, mock_env_vars):
    """GET /metrics/models should include embedding model info."""
    response = client.get("/metrics/models")
    data = response.json()

    assert "embedding" in data
    assert data["embedding"]["name"] == "Qwen/Qwen3-Embedding-0.6B"
    assert data["embedding"]["provider"] == "Tei"
    assert data["embedding"]["model_type"] == "embedding"


def test_models_endpoint_returns_reranker_info(mock_tei, mock_env_vars):
    """GET /metrics/models should include reranker model info when enabled."""
    response = client.get("/metrics/models")
    data = response.json()

    assert "reranker" in data
    assert data["reranker"]["name"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert data["reranker"]["provider"] == "HuggingFace"


def test_models_endpoint_returns_eval_info(mock_tei, mock_env_vars):
    """GET /metrics/models should include eval model info."""
    response = client.get("/metrics/models")
    data = response.json()

    assert "eval" in data
    assert data["eval"]["name"] == "claude-sonnet-4-20250514"
    assert data["eval"]["provider"] == "Anthropic"


def test_models_endpoint_reports_configured_eval_provider(mock_tei, mock_env_vars):
    """The eval provider must come from config, not a hardcoded 'Anthropic'."""
    openai_judge_config = create_mock_models_config()
    openai_judge_config.eval = EvalConfig(
        provider="openai",
        model="gpt-5.2",
        api_key="test-key",
        requires_api_key=True,
        execution_boundary=ExecutionBoundary.THIRD_PARTY,
    )

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=openai_judge_config,
    ):
        response = client.get("/metrics/models")
        data = response.json()

    assert data["eval"]["name"] == "gpt-5.2"
    assert data["eval"]["provider"] == "Openai"
    assert data["eval"]["execution_boundary"] == "third_party"


def test_models_endpoint_reports_boundary_for_every_role(mock_tei, mock_env_vars):
    """Every model role reports where it executes."""
    response = client.get("/metrics/models")
    data = response.json()

    assert data["llm"]["execution_boundary"] == "customer_managed"
    assert data["embedding"]["execution_boundary"] == "customer_managed"
    # The reranker runs in-process, so it executes wherever rag-server does.
    assert data["reranker"]["execution_boundary"] == "customer_managed"
    assert data["eval"]["execution_boundary"] == "third_party"


def test_undeclared_boundary_is_reported_as_unknown(mock_tei, mock_env_vars):
    """A model definition with no boundary reports null — never coerced to 'local'."""
    undeclared_config = create_mock_models_config()
    undeclared_config.llm.execution_boundary = None
    undeclared_config.eval.execution_boundary = None

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=undeclared_config,
    ):
        response = client.get("/metrics/models")
        data = response.json()

    assert data["llm"]["execution_boundary"] is None
    assert data["eval"]["execution_boundary"] is None


def test_eval_status_follows_the_configured_provider_key(mock_tei, mock_env_vars):
    """A judge whose key is missing is 'unavailable'; a keyless judge is 'available'."""
    missing_key_config = create_mock_models_config()
    missing_key_config.eval = EvalConfig(
        provider="openai",
        model="gpt-5.2",
        requires_api_key=True,
        api_key=None,
        execution_boundary=ExecutionBoundary.THIRD_PARTY,
    )

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=missing_key_config,
    ):
        assert client.get("/metrics/models").json()["eval"]["status"] == "unavailable"

    self_hosted_config = create_mock_models_config()
    self_hosted_config.eval = EvalConfig(
        provider="vllm",
        model="Qwen/Qwen3-32B-AWQ",
        base_url="http://vllm:8000/v1",
        requires_api_key=False,
        execution_boundary=ExecutionBoundary.CUSTOMER_MANAGED,
    )

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=self_hosted_config,
    ):
        data = client.get("/metrics/models").json()

    assert data["eval"]["status"] == "available"
    assert data["eval"]["execution_boundary"] == "customer_managed"


def test_models_endpoint_includes_reference_urls(mock_tei, mock_env_vars):
    """GET /metrics/models should include reference URLs for models."""
    response = client.get("/metrics/models")
    data = response.json()

    # The LLM (vllm, an arbitrary HF repo id) has no static MODEL_REFERENCES
    # entry; the embedding model (a known TEI/HF model) does.
    assert data["embedding"]["reference_url"] is not None
    assert "huggingface.co" in data["embedding"]["reference_url"]


# ============================================================================
# Retrieval Config Endpoint Tests
# ============================================================================

def test_retrieval_endpoint_returns_200(mock_env_vars):
    """GET /metrics/retrieval should return 200."""
    response = client.get("/metrics/retrieval")
    assert response.status_code == 200


def test_retrieval_endpoint_returns_hybrid_config(mock_env_vars):
    """GET /metrics/retrieval should include hybrid search config."""
    response = client.get("/metrics/retrieval")
    data = response.json()

    assert "hybrid_search" in data
    assert data["hybrid_search"]["enabled"] is True
    assert data["hybrid_search"]["rrf_k"] == 60
    assert data["hybrid_search"]["fusion_method"] == "reciprocal_rank_fusion"


# ── Chunking is configuration, not three coincidentally-equal literals ───────


def test_retrieval_endpoint_reports_configured_chunk_size(
    mock_models_config_fixture, mock_env_vars
):
    """The defect: 500/50 were hardcoded here, in the SentenceSplitter, and in
    LlamaIndex Settings, agreeing only by coincidence. The eval runner read this
    endpoint and recorded the literal as measured configuration."""
    mock_models_config_fixture.chunking = ChunkingConfig(chunk_size=321, chunk_overlap=21)

    data = client.get("/metrics/retrieval").json()

    vector = data["hybrid_search"]["vector"]
    assert vector["chunk_size"] == 321
    assert vector["chunk_overlap"] == 21


def test_the_docling_path_reports_no_size_rather_than_the_splitters(mock_env_vars):
    """Docling splits on document structure and has no size or overlap. Reporting
    the SentenceSplitter's numbers for it would invent a value that path never
    used — the exact defect being fixed."""
    data = client.get("/metrics/retrieval").json()
    chunkers = {c["name"]: c for c in data["hybrid_search"]["vector"]["chunkers"]}

    assert set(chunkers) == {"sentence_splitter", "docling"}
    assert chunkers["docling"]["chunk_size"] is None
    assert chunkers["docling"]["chunk_overlap"] is None
    assert chunkers["sentence_splitter"]["chunk_size"] is not None
    assert ".pdf" in chunkers["docling"]["applies_to"]
    assert ".md" in chunkers["sentence_splitter"]["applies_to"]


def test_retrieval_endpoint_returns_bm25_config(mock_env_vars):
    """GET /metrics/retrieval should include BM25 config."""
    response = client.get("/metrics/retrieval")
    data = response.json()

    assert "hybrid_search" in data
    assert "bm25" in data["hybrid_search"]
    assert data["hybrid_search"]["bm25"]["enabled"] is True


def test_retrieval_endpoint_returns_reranker_config(mock_env_vars):
    """GET /metrics/retrieval should include reranker config."""
    response = client.get("/metrics/retrieval")
    data = response.json()

    assert "reranker" in data
    assert data["reranker"]["enabled"] is True
    assert data["reranker"]["model"] == "cross-encoder/ms-marco-MiniLM-L-6-v2"


def test_retrieval_endpoint_returns_top_k(mock_env_vars):
    """GET /metrics/retrieval should include top-k settings."""
    response = client.get("/metrics/retrieval")
    data = response.json()

    assert data["retrieval_top_k"] == 10
    assert "final_top_n" in data


def test_retrieval_endpoint_includes_research_references(mock_env_vars):
    """GET /metrics/retrieval should include research references."""
    response = client.get("/metrics/retrieval")
    data = response.json()

    assert "research_reference" in data["hybrid_search"]
    assert "improvement_claim" in data["hybrid_search"]


# ============================================================================
# System Metrics Endpoint Tests
# ============================================================================

def test_system_metrics_endpoint_returns_200(mock_system_metrics):
    """GET /metrics/system should return 200."""
    response = client.get("/metrics/system")
    assert response.status_code == 200


def test_system_metrics_returns_models(mock_system_metrics):
    """GET /metrics/system should include models configuration."""
    response = client.get("/metrics/system")
    data = response.json()

    assert "models" in data
    assert "llm" in data["models"]
    assert "embedding" in data["models"]


def test_system_metrics_returns_retrieval(mock_system_metrics):
    """GET /metrics/system should include retrieval configuration."""
    response = client.get("/metrics/system")
    data = response.json()

    assert "retrieval" in data
    assert "hybrid_search" in data["retrieval"]


def test_system_metrics_returns_document_count(mock_system_metrics):
    """GET /metrics/system should include document count."""
    response = client.get("/metrics/system")
    data = response.json()

    assert "document_count" in data
    assert isinstance(data["document_count"], int)


def test_system_metrics_returns_document_stats(mock_system_metrics):
    """GET /metrics/system should include document statistics."""
    response = client.get("/metrics/system")
    data = response.json()

    assert "document_count" in data
    assert "chunk_count" in data


def test_system_metrics_returns_health_status(mock_system_metrics):
    """GET /metrics/system should include health status."""
    response = client.get("/metrics/system")
    data = response.json()

    assert "health_status" in data
    assert "component_status" in data


def test_system_metrics_returns_timestamp(mock_system_metrics):
    """GET /metrics/system should include a timestamp."""
    response = client.get("/metrics/system")
    data = response.json()

    assert "timestamp" in data
    assert "system_name" in data


# ============================================================================
# Edge Cases
# ============================================================================

def test_models_with_reranker_disabled(mock_tei):
    """GET /metrics/models should handle disabled reranker."""
    disabled_reranker_config = create_mock_models_config()
    disabled_reranker_config.reranker.enabled = False

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=disabled_reranker_config,
    ):
        with patch(
            "infrastructure.config.models_config._default_manager._config",
            disabled_reranker_config,
        ):
            response = client.get("/metrics/models")
            data = response.json()

            # Reranker should be None when disabled
            assert data["reranker"] is None


def test_retrieval_with_hybrid_disabled():
    """GET /metrics/retrieval should handle disabled hybrid search."""
    disabled_hybrid_config = create_mock_models_config()
    disabled_hybrid_config.retrieval.enable_hybrid_search = False

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=disabled_hybrid_config,
    ):
        with patch(
            "infrastructure.config.models_config._default_manager._config",
            disabled_hybrid_config,
        ):
            response = client.get("/metrics/retrieval")
            data = response.json()

            assert data["hybrid_search"]["enabled"] is False
