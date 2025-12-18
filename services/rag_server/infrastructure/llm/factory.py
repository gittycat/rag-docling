"""
LLM Client Factory - single entry point for LLM instantiation.

Usage:
    from infrastructure.llm.factory import get_llm_client
    llm = get_llm_client()  # Returns configured LLM based on env vars
"""
from typing import Optional
import logging

from llama_index.core.llms import LLM
from .config import LLMConfig, LLMProvider
from .providers import (
    create_ollama_client,
    create_openai_client,
    create_anthropic_client,
    create_google_client,
    create_deepseek_client,
)

logger = logging.getLogger(__name__)

# Singleton instance
_llm_instance: Optional[LLM] = None


def get_llm_client() -> LLM:
    """
    Get or create LLM client based on environment configuration.

    Singleton pattern - LLM is created once at startup and reused.
    Configure via environment variables:
        - LLM_PROVIDER: ollama, openai, anthropic, google, deepseek, moonshot
        - LLM_MODEL: Model name
        - LLM_API_KEY: API key (required for cloud providers)
        - LLM_BASE_URL: Custom endpoint (optional)
        - LLM_TIMEOUT: Request timeout in seconds

    Returns:
        Configured LLM instance
    """
    global _llm_instance

    if _llm_instance is not None:
        return _llm_instance

    config = LLMConfig.from_env()
    logger.info(f"[LLM] Initializing {config.provider.value} provider: {config.model}")

    # Provider-to-creator mapping
    creators = {
        LLMProvider.OLLAMA: create_ollama_client,
        LLMProvider.OPENAI: create_openai_client,
        LLMProvider.ANTHROPIC: create_anthropic_client,
        LLMProvider.GOOGLE: create_google_client,
        LLMProvider.DEEPSEEK: create_deepseek_client,
        LLMProvider.MOONSHOT: create_openai_client,  # Uses OpenAI-compatible API
    }

    creator = creators.get(config.provider)
    if not creator:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")

    _llm_instance = creator(config)

    if config.provider == LLMProvider.OLLAMA:
        logger.info(f"[LLM] Ollama client initialized: keep_alive={config.keep_alive}")
    elif config.provider == LLMProvider.MOONSHOT:
        logger.info(f"[LLM] Moonshot (OpenAI-compatible) client initialized: base_url={config.base_url}")
    else:
        logger.info(f"[LLM] {config.provider.value.capitalize()} client initialized successfully")

    return _llm_instance


def get_llm_config() -> LLMConfig:
    """
    Get current LLM configuration.

    Useful for inspecting config without creating client.
    """
    return LLMConfig.from_env()


def reset_llm_client() -> None:
    """
    Reset the singleton LLM client.

    Useful for testing or reconfiguration.
    """
    global _llm_instance
    _llm_instance = None
    logger.info("[LLM] Client reset")
