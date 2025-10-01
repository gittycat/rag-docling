import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

@patch('ollama.Client')
def test_generate_response_with_context(mock_client_class):
    """Generate LLM response using context from retrieved documents"""
    from core_logic.llm_handler import generate_response

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    # Mock Ollama response
    mock_client.generate.return_value = {
        'response': 'This is the generated answer based on the context.'
    }

    query = "What is the capital of France?"
    context = "France is a country in Europe. Its capital is Paris."

    response = generate_response(query, context)

    assert response is not None
    assert 'generated answer' in response.lower()
    mock_client.generate.assert_called_once()

    # Verify the prompt includes both query and context
    call_args = mock_client.generate.call_args
    prompt = call_args.kwargs.get('prompt', '')
    assert query.lower() in prompt.lower()
    assert context.lower() in prompt.lower()

@patch('ollama.Client')
def test_construct_prompt_with_context(mock_client_class):
    """Construct proper RAG prompt with query and context"""
    from core_logic.llm_handler import construct_prompt

    query = "What is RAG?"
    context_docs = [
        "RAG stands for Retrieval Augmented Generation.",
        "It combines retrieval with LLM generation."
    ]

    prompt = construct_prompt(query, context_docs)

    assert query in prompt
    assert all(doc in prompt for doc in context_docs)
    # Should have instruction to use context
    assert 'context' in prompt.lower() or 'information' in prompt.lower()

@patch('ollama.Client')
def test_generate_response_without_context(mock_client_class):
    """Generate response when no relevant context is found"""
    from core_logic.llm_handler import generate_response

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_client.generate.return_value = {
        'response': 'I don\'t have enough information to answer that question.'
    }

    query = "What is the meaning of life?"
    context = ""  # No context

    response = generate_response(query, context)

    assert response is not None
    assert 'information' in response.lower() or 'answer' in response.lower()

@patch('ollama.Client')
def test_llm_uses_correct_model(mock_client_class):
    """Verify LLM uses the configured model"""
    from core_logic.llm_handler import generate_response

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_client.generate.return_value = {'response': 'Test response'}

    generate_response("test query", "test context")

    call_args = mock_client.generate.call_args
    model = call_args.kwargs.get('model', '')
    assert model is not None
    assert len(model) > 0  # Should have a model specified

@patch('ollama.Client')
def test_handle_llm_error(mock_client_class):
    """Handle errors from Ollama gracefully"""
    from core_logic.llm_handler import generate_response

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    # Simulate connection error
    mock_client.generate.side_effect = Exception("Connection failed")

    with pytest.raises(Exception, match="Connection failed"):
        generate_response("test query", "test context")
