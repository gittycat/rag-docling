import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_embedding_function_initializes():
    """LangChain OllamaEmbeddings should initialize with nomic-embed-text model"""
    from core_logic.embeddings import get_embedding_function

    with patch('core_logic.embeddings.OllamaEmbeddings') as mock_embeddings:
        mock_instance = MagicMock()
        mock_embeddings.return_value = mock_instance

        embedding_fn = get_embedding_function()
        assert embedding_fn is not None

        # Verify OllamaEmbeddings was called with correct parameters
        mock_embeddings.assert_called_once()
        call_kwargs = mock_embeddings.call_args.kwargs
        assert call_kwargs['model'] == 'nomic-embed-text'


def test_embedding_function_has_correct_endpoint():
    """Embedding function should use correct Ollama endpoint"""
    from core_logic.embeddings import get_embedding_function

    with patch('core_logic.embeddings.OllamaEmbeddings') as mock_embeddings:
        mock_instance = MagicMock()
        mock_embeddings.return_value = mock_instance

        # Test with default URL
        embedding_fn = get_embedding_function()

        call_kwargs = mock_embeddings.call_args.kwargs
        assert 'base_url' in call_kwargs
        assert '11434' in call_kwargs['base_url'] or 'docker' in call_kwargs['base_url'].lower()


def test_embedding_function_with_custom_url():
    """Test embedding function respects OLLAMA_URL env var"""
    from core_logic.embeddings import get_embedding_function

    custom_url = "http://custom-ollama:12345"

    with patch.dict(os.environ, {'OLLAMA_URL': custom_url}):
        with patch('core_logic.embeddings.OllamaEmbeddings') as mock_embeddings:
            mock_instance = MagicMock()
            mock_embeddings.return_value = mock_instance

            embedding_fn = get_embedding_function()

            call_kwargs = mock_embeddings.call_args.kwargs
            assert call_kwargs['base_url'] == custom_url


@patch('core_logic.embeddings.OllamaEmbeddings')
def test_embedding_function_generates_embeddings(mock_embeddings_class):
    """Embedding function should generate 768-dimensional embeddings"""
    from core_logic.embeddings import get_embedding_function

    # Mock the embedding instance and embed_documents method
    mock_instance = MagicMock()
    mock_instance.embed_documents.return_value = [[0.1] * 768]
    mock_embeddings_class.return_value = mock_instance

    embedding_fn = get_embedding_function()
    embeddings = embedding_fn.embed_documents(["test document"])

    assert len(embeddings) == 1
    assert len(embeddings[0]) == 768
    assert all(isinstance(x, float) for x in embeddings[0])
    mock_instance.embed_documents.assert_called_once()


@patch('core_logic.embeddings.OllamaEmbeddings')
def test_embedding_function_handles_multiple_texts(mock_embeddings_class):
    """Embedding function should handle batch processing"""
    from core_logic.embeddings import get_embedding_function

    # Mock batch embedding
    mock_instance = MagicMock()
    mock_instance.embed_documents.return_value = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
    mock_embeddings_class.return_value = mock_instance

    embedding_fn = get_embedding_function()
    texts = ["text1", "text2", "text3"]
    embeddings = embedding_fn.embed_documents(texts)

    assert len(embeddings) == 3
    assert all(len(emb) == 768 for emb in embeddings)
    mock_instance.embed_documents.assert_called_once_with(texts)
