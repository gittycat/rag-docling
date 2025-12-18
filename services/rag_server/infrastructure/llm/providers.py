"""
Provider-specific LLM client creation functions.

Each function lazily imports the provider's LlamaIndex integration
to avoid loading unused dependencies.
"""
from llama_index.core.llms import LLM
from .config import LLMConfig


def create_ollama_client(config: LLMConfig) -> LLM:
    """Create Ollama LLM client for local inference."""
    from llama_index.llms.ollama import Ollama

    return Ollama(
        model=config.model,
        base_url=config.base_url,
        request_timeout=config.timeout,
        keep_alive=config.keep_alive,
    )


def create_openai_client(config: LLMConfig) -> LLM:
    """
    Create OpenAI LLM client.

    Also used for OpenAI-compatible APIs (Moonshot, Azure, etc.)
    via custom base_url.
    """
    from llama_index.llms.openai import OpenAI

    kwargs = {
        "model": config.model,
        "timeout": config.timeout,
    }

    if config.api_key:
        kwargs["api_key"] = config.api_key

    if config.base_url:
        kwargs["api_base"] = config.base_url

    return OpenAI(**kwargs)


def create_anthropic_client(config: LLMConfig) -> LLM:
    """Create Anthropic Claude LLM client."""
    from llama_index.llms.anthropic import Anthropic

    return Anthropic(
        model=config.model,
        api_key=config.api_key,
        timeout=config.timeout,
    )


def create_google_client(config: LLMConfig) -> LLM:
    """Create Google Gemini LLM client."""
    from llama_index.llms.google_genai import GoogleGenAI

    return GoogleGenAI(
        model=config.model,
        api_key=config.api_key,
    )


def create_deepseek_client(config: LLMConfig) -> LLM:
    """Create DeepSeek LLM client."""
    from llama_index.llms.deepseek import DeepSeek

    return DeepSeek(
        model=config.model,
        api_key=config.api_key,
    )
