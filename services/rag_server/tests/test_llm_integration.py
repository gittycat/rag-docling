import pytest
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_get_system_prompt():
    """System prompt should define LLM behavior and style"""
    from core_logic.llm_handler import get_system_prompt

    prompt = get_system_prompt()

    assert isinstance(prompt, str)
    assert len(prompt) > 0
    # Should mention being professional and accurate
    assert 'professional' in prompt.lower() or 'accurate' in prompt.lower()
    # Should instruct to be direct and avoid fillers
    assert 'direct' in prompt.lower() or 'concise' in prompt.lower()

def test_get_context_prompt():
    """Context prompt should have template placeholders and grounding instructions"""
    from core_logic.llm_handler import get_context_prompt

    prompt = get_context_prompt()

    assert isinstance(prompt, str)
    assert len(prompt) > 0
    # Should have LlamaIndex placeholder for context
    assert '{context_str}' in prompt
    # Should have grounding instructions
    assert 'context' in prompt.lower()
    assert 'only' in prompt.lower() or 'provided' in prompt.lower()
    # Should handle insufficient information
    assert "don't have" in prompt.lower() or "not contain" in prompt.lower()

def test_get_condense_prompt():
    """Condense prompt should return None to use LlamaIndex default"""
    from core_logic.llm_handler import get_condense_prompt

    prompt = get_condense_prompt()

    # Should be None to use LlamaIndex's DEFAULT_CONDENSE_PROMPT
    assert prompt is None

@patch.dict('os.environ', {'OLLAMA_URL': 'http://test:11434', 'LLM_MODEL': 'test-model'})
def test_get_llm_client():
    """LLM client should be configured with Ollama URL and model"""
    from core_logic.llm_handler import get_llm_client

    llm = get_llm_client()

    assert llm is not None
    # Should be Ollama instance
    assert hasattr(llm, 'model')
    assert llm.model == 'test-model'
    assert hasattr(llm, 'base_url')
    assert 'test:11434' in llm.base_url

def test_system_prompt_no_conversational_fillers():
    """System prompt should explicitly discourage conversational fillers"""
    from core_logic.llm_handler import get_system_prompt

    prompt = get_system_prompt()

    # Should mention avoiding fillers like "Let me explain", "Okay", etc.
    filler_mentions = [
        'let me' in prompt.lower(),
        'okay' in prompt.lower(),
        'well' in prompt.lower(),
        'sure' in prompt.lower(),
        'filler' in prompt.lower()
    ]
    # At least one filler should be mentioned as something to avoid
    assert any(filler_mentions), "Prompt should mention avoiding conversational fillers"

def test_context_prompt_structure():
    """Context prompt should follow LlamaIndex chat engine format"""
    from core_logic.llm_handler import get_context_prompt

    prompt = get_context_prompt()

    # Should be formatted for chat engine (not query engine PromptTemplate)
    # Context comes first, then instructions
    context_index = prompt.index('{context_str}')
    instructions_keywords = ['instructions', 'answer', 'provide']

    # Instructions should appear after context placeholder
    has_instructions_after = any(
        keyword in prompt[context_index:].lower()
        for keyword in instructions_keywords
    )
    assert has_instructions_after, "Instructions should appear after context"

def test_prompts_are_consistent():
    """All prompt functions should return consistent types"""
    from core_logic.llm_handler import (
        get_system_prompt,
        get_context_prompt,
        get_condense_prompt
    )

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

@patch.dict('os.environ', {'OLLAMA_URL': 'http://test:11434', 'LLM_MODEL': 'test-model'})
def test_llm_client_timeout():
    """LLM client should have appropriate timeout setting"""
    from core_logic.llm_handler import get_llm_client

    llm = get_llm_client()

    # Should have request_timeout configured
    assert hasattr(llm, 'request_timeout')
    # Timeout should be reasonable (e.g., 120s)
    assert llm.request_timeout >= 60.0, "Timeout should be at least 60 seconds"
