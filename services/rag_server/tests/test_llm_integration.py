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
)


def create_mock_models_config():
    """Create a mock ModelsConfig for tests (uses vllm/tei, no API key required)."""
    return ModelsConfig(
        llm=LLMConfig(
            provider="vllm",
            model="Qwen/Qwen2.5-14B-Instruct",
            base_url="http://vllm:8000/v1",
            timeout=120,
        ),
        embedding=EmbeddingConfig(
            provider="tei",
            model="Qwen/Qwen3-Embedding-0.6B",
            base_url="http://tei:80",
        ),
        eval=EvalConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            api_key="test-key",
        ),
        reranker=RerankerConfig(enabled=True),
        retrieval=RetrievalConfig(),
    )


def test_get_system_prompt():
    """System prompt should define LLM behavior and style"""
    from infrastructure.llm.prompts import get_system_prompt

    mock_config = create_mock_models_config()

    with patch(
        "infrastructure.llm.prompts.get_models_config",
        return_value=mock_config,
    ):
        prompt = get_system_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        # Should mention being professional and accurate
        assert "professional" in prompt.lower() or "accurate" in prompt.lower()
        # Should instruct to be direct and avoid fillers
        assert "direct" in prompt.lower() or "concise" in prompt.lower()


def test_get_context_prompt():
    """Context prompt should have template placeholders and grounding instructions"""
    from infrastructure.llm.prompts import get_context_prompt

    mock_config = create_mock_models_config()

    with patch(
        "infrastructure.llm.prompts.get_models_config",
        return_value=mock_config,
    ):
        prompt = get_context_prompt()

        assert isinstance(prompt, str)
        assert len(prompt) > 0
        # Should have LlamaIndex placeholder for context
        assert "{context_str}" in prompt
        # Should have grounding instructions
        assert "context" in prompt.lower()
        assert "only" in prompt.lower() or "provided" in prompt.lower()
        # Should handle insufficient information
        assert "don't have" in prompt.lower() or "not contain" in prompt.lower()


def test_get_condense_prompt():
    """Condense prompt should return None to use LlamaIndex default"""
    from infrastructure.llm.prompts import get_condense_prompt

    mock_config = create_mock_models_config()

    with patch(
        "infrastructure.llm.prompts.get_models_config",
        return_value=mock_config,
    ):
        prompt = get_condense_prompt()

        # Should be None to use LlamaIndex's DEFAULT_CONDENSE_PROMPT
        assert prompt is None


def test_get_llm_client():
    """LLM client should be configured with the vLLM (OpenAI-compatible) URL and model"""
    from infrastructure.llm.factory import get_llm_client, reset_llm_client

    mock_config = create_mock_models_config()
    mock_config.llm.model = "test-model"
    mock_config.llm.base_url = "http://test:8000/v1"

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=mock_config,
    ):
        reset_llm_client()  # Clear singleton for test isolation

        llm = get_llm_client()

        assert llm is not None
        # Should be an OpenAILike instance (vllm dispatches through the
        # OpenAI-compatible client — see infrastructure/llm/factory.py)
        assert hasattr(llm, "model")
        assert llm.model == "test-model"
        assert hasattr(llm, "api_base")
        assert "test:8000" in llm.api_base


def test_system_prompt_no_conversational_fillers():
    """System prompt should explicitly discourage conversational fillers"""
    from infrastructure.llm.prompts import get_system_prompt

    mock_config = create_mock_models_config()

    with patch(
        "infrastructure.llm.prompts.get_models_config",
        return_value=mock_config,
    ):
        prompt = get_system_prompt()

        # Should mention avoiding fillers like "Let me explain", "Okay", etc.
        filler_mentions = [
            "let me" in prompt.lower(),
            "okay" in prompt.lower(),
            "well" in prompt.lower(),
            "sure" in prompt.lower(),
            "filler" in prompt.lower(),
        ]
        # At least one filler should be mentioned as something to avoid
        assert any(filler_mentions), "Prompt should mention avoiding conversational fillers"


def test_context_prompt_structure():
    """Context prompt should follow LlamaIndex chat engine format"""
    from infrastructure.llm.prompts import get_context_prompt

    mock_config = create_mock_models_config()

    with patch(
        "infrastructure.llm.prompts.get_models_config",
        return_value=mock_config,
    ):
        prompt = get_context_prompt()

        # Should be formatted for chat engine (not query engine PromptTemplate)
        # Context comes first, then instructions
        context_index = prompt.index("{context_str}")
        instructions_keywords = ["instructions", "answer", "provide"]

        # Instructions should appear after context placeholder
        has_instructions_after = any(
            keyword in prompt[context_index:].lower() for keyword in instructions_keywords
        )
        assert has_instructions_after, "Instructions should appear after context"


def test_prompts_are_consistent():
    """All prompt functions should return consistent types"""
    from infrastructure.llm.prompts import (
        get_system_prompt,
        get_context_prompt,
        get_condense_prompt,
    )

    mock_config = create_mock_models_config()

    with patch(
        "infrastructure.llm.prompts.get_models_config",
        return_value=mock_config,
    ):
        system = get_system_prompt()
        context = get_context_prompt()
        condense = get_condense_prompt()

        # System and context should be strings
        assert isinstance(system, str)
        assert isinstance(context, str)
        # Condense should be None (uses default) or string
        assert condense is None or isinstance(condense, str)

        # Prompts should be different
        assert system != context


def test_llm_client_timeout():
    """LLM client should have appropriate timeout setting"""
    from infrastructure.llm.factory import get_llm_client, reset_llm_client

    mock_config = create_mock_models_config()
    mock_config.llm.model = "test-model"
    mock_config.llm.base_url = "http://test:8000/v1"
    mock_config.llm.timeout = 120

    with patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=mock_config,
    ):
        reset_llm_client()  # Clear singleton for test isolation

        llm = get_llm_client()

        # Should have timeout configured
        assert hasattr(llm, "timeout")
        # Timeout should be reasonable (e.g., 120s)
        assert llm.timeout >= 60.0, "Timeout should be at least 60 seconds"
