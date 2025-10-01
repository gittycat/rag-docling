import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_embedding_function_initializes():
    """ChromaDB OllamaEmbeddingFunction should initialize with nomic-embed-text model"""
    from core_logic.embeddings import get_embedding_function

    embedding_fn = get_embedding_function()
    assert embedding_fn is not None
    # Check that it's an OllamaEmbeddingFunction
    assert embedding_fn.__class__.__name__ == "OllamaEmbeddingFunction"
    # Check model_name attribute
    assert embedding_fn.model_name == "nomic-embed-text"

def test_embedding_function_has_correct_endpoint():
    """Embedding function should use correct Ollama endpoint"""
    from core_logic.embeddings import get_embedding_function
    import os

    # Test with default URL
    embedding_fn = get_embedding_function()
    assert embedding_fn._client._client.base_url is not None
    base_url = str(embedding_fn._client._client.base_url)
    assert '11434' in base_url or 'docker' in base_url.lower()

@patch('chromadb.utils.embedding_functions.OllamaEmbeddingFunction.__call__')
def test_embedding_function_generates_embeddings(mock_call):
    """Embedding function should generate 768-dimensional embeddings"""
    from core_logic.embeddings import get_embedding_function

    # Mock the response
    mock_call.return_value = [[0.1] * 768]

    embedding_fn = get_embedding_function()
    embeddings = embedding_fn(["test document"])

    assert len(embeddings) == 1
    assert len(embeddings[0]) == 768
    assert all(isinstance(x, float) for x in embeddings[0])
    mock_call.assert_called_once()

@patch('chromadb.utils.embedding_functions.OllamaEmbeddingFunction.__call__')
def test_embedding_function_handles_multiple_texts(mock_call):
    """Embedding function should handle batch processing"""
    from core_logic.embeddings import get_embedding_function

    # Mock batch embedding
    mock_call.return_value = [[0.1] * 768, [0.2] * 768, [0.3] * 768]

    embedding_fn = get_embedding_function()
    texts = ["text1", "text2", "text3"]
    embeddings = embedding_fn(texts)

    assert len(embeddings) == 3
    assert all(len(emb) == 768 for emb in embeddings)
    mock_call.assert_called_once_with(texts)
