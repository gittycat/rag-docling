"""Startup guard that the active embedding model matches the declared vector dimension.

document_chunks.embedding is vector(N) with N = vector_store.dimension, so a
model producing a different width corrupts retrieval silently. The check probes
the model locally (no Postgres round-trip — see check_embedding_dimension_match).
"""

import pytest
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.config.models_config import (
    ModelsConfig,
    LLMConfig,
    EmbeddingConfig,
    EvalConfig,
    RerankerConfig,
    RetrievalConfig,
    VectorStoreConfig,
)


def create_mock_models_config(dimension: int = 1024):
    return ModelsConfig(
        llm=LLMConfig(provider="vllm", model="Qwen/Qwen2.5-14B-Instruct", base_url="http://vllm:8000/v1"),
        embedding=EmbeddingConfig(provider="tei", model="Qwen/Qwen3-Embedding-0.6B", base_url="http://tei:80"),
        eval=EvalConfig(provider="anthropic", model="claude-sonnet-4-20250514", api_key="test-key"),
        reranker=RerankerConfig(enabled=True),
        retrieval=RetrievalConfig(),
        vector_store=VectorStoreConfig(dimension=dimension),
    )


def _run_check_with(config, embed_model):
    """Run the startup check with a stubbed Settings.embed_model."""
    from core.config import check_embedding_dimension_match
    from llama_index.core import Settings

    Settings.embed_model = embed_model
    try:
        with patch("infrastructure.config.models_config.get_models_config", return_value=config):
            check_embedding_dimension_match()
    finally:
        Settings._embed_model = None


def _mock_embed_model(*, embedding=None, side_effect=None):
    from llama_index.core.embeddings import BaseEmbedding

    model = MagicMock(spec=BaseEmbedding)
    if side_effect is not None:
        model.get_text_embedding.side_effect = side_effect
    else:
        model.get_text_embedding.return_value = embedding
    return model


def test_dimension_match_passes_when_equal():
    embed_model = _mock_embed_model(embedding=[0.1] * 1024)

    _run_check_with(create_mock_models_config(dimension=1024), embed_model)  # no error

    embed_model.get_text_embedding.assert_called_once_with("dim-probe")


def test_dimension_match_raises_on_mismatch():
    config = create_mock_models_config(dimension=1024)
    embed_model = _mock_embed_model(embedding=[0.1] * 1536)

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        _run_check_with(config, embed_model)


def test_dimension_match_raises_on_1024_768_mismatch():
    """The exact regression this guard exists for: config.yml still declares the
    old 768-dim schema (pre-TEI/Qwen3 migration) while the active embedding model
    now produces 1024-dim vectors, or vice versa.
    """
    config = create_mock_models_config(dimension=1024)
    embed_model = _mock_embed_model(embedding=[0.1] * 768)

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        _run_check_with(config, embed_model)

    config = create_mock_models_config(dimension=768)
    embed_model = _mock_embed_model(embedding=[0.1] * 1024)

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        _run_check_with(config, embed_model)


def test_dimension_match_honours_a_non_default_configured_dimension():
    """The declared dimension comes from config.yml, not a hardcoded value."""
    config = create_mock_models_config(dimension=768)

    _run_check_with(config, _mock_embed_model(embedding=[0.1] * 768))  # no error

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        _run_check_with(config, _mock_embed_model(embedding=[0.1] * 1024))


def test_dimension_match_skips_when_embedding_model_is_unreachable():
    """Startup must not hard-fail if the embedding backend isn't up yet."""
    config = create_mock_models_config(dimension=1024)
    embed_model = _mock_embed_model(side_effect=ConnectionError("tei unreachable"))

    _run_check_with(config, embed_model)  # no error, logs a warning instead
