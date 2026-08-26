"""
LLM Client Factory - single entry point for LLM instantiation.

Usage:
    from infrastructure.llm.factory import get_llm_client
    llm = get_llm_client()  # Returns configured LLM based on config.yml

    # Or use dependency injection directly:
    from infrastructure.llm.factory import LLMClientManager
    manager = LLMClientManager()
    llm = manager.get_client()
"""

import logging
from typing import Any

from llama_index.core.llms import LLM

from .config import LLMConfig, LLMProvider

logger = logging.getLogger(__name__)


# Provider configuration: maps provider to (module_path, class_name, param_mapping)
# param_mapping: config field -> constructor param name (None = use same name as config field)
# Every mapping forwards `temperature`. It used to be absent, so the judge's
# documented temperature-0 determinism never reached any client: LLMConfig carried
# the value and the factory dropped it on the floor.
_PROVIDER_CONFIG: dict[LLMProvider, tuple[str, str, dict[str, str | None]]] = {
    LLMProvider.OPENAI: (
        "llama_index.llms.openai",
        "OpenAI",
        {
            "model": None,
            "api_key": None,
            "base_url": "api_base",
            "timeout": None,
            "temperature": None,
        },
    ),
    LLMProvider.ANTHROPIC: (
        "llama_index.llms.anthropic",
        "Anthropic",
        # base_url is mapped here even though the Anthropic entry in config.yml
        # rarely sets one: llama_index.llms.anthropic.Anthropic accepts base_url,
        # and a configured value being silently discarded is the failure mode that
        # made active.eval dead configuration in the first place. rag_server's
        # mirror of this table still omits it; nothing depends on the omission.
        {
            "model": None,
            "api_key": None,
            "base_url": None,
            "timeout": None,
            "temperature": None,
        },
    ),
    # Any OpenAI-compatible endpoint we host. Mirrors rag_server's VLLM entry.
    # To add a new provider: an entry here (module path, class name, param mapping)
    # plus everything listed in config.py's LLMProvider docstring.
    LLMProvider.VLLM: (
        "llama_index.llms.openai_like",
        "OpenAILike",
        {
            "model": None,
            "api_key": None,
            "base_url": "api_base",
            "timeout": None,
            "temperature": None,
        },
    ),
}


def create_llm_client(config: LLMConfig) -> LLM:
    """Create LLM client based on provider configuration."""
    provider_config = _PROVIDER_CONFIG.get(config.provider)
    if not provider_config:
        raise ValueError(f"Unsupported LLM provider: {config.provider}")

    module_path, class_name, param_mapping = provider_config

    # Lazy import
    import importlib

    module = importlib.import_module(module_path)
    llm_class = getattr(module, class_name)

    # Build kwargs from config using param mapping
    kwargs: dict[str, Any] = {}
    for config_field, param_name in param_mapping.items():
        value = getattr(config, config_field, None)
        if value is not None:
            # Use mapped name or original field name
            key = param_name if param_name else config_field
            kwargs[key] = value

    if config.provider == LLMProvider.VLLM:
        # vLLM usually runs keyless behind the network boundary; the OpenAI client
        # underneath OpenAILike still requires a non-empty api_key string.
        kwargs.setdefault("api_key", "none")
        # Served models expose /v1/chat/completions, not the legacy completions
        # route. Without this OpenAILike would guess from the model name, which
        # never matches an HF repo id.
        kwargs["is_chat_model"] = True

    return llm_class(**kwargs)


class LLMClientManager:
    """Manages LLM client lifecycle with lazy initialization."""

    def __init__(self, config: LLMConfig | None = None):
        self._config = config
        self._client: LLM | None = None

    def get_client(self) -> LLM:
        """Get or create LLM client (lazy initialization)."""
        if self._client is not None:
            return self._client

        config = self._config or LLMConfig.from_env()
        logger.info(f"[LLM] Initializing {config.provider.value} provider: {config.model}")

        self._client = create_llm_client(config)
        logger.info(f"[LLM] {config.provider.value.capitalize()} client initialized")

        return self._client

    def reset(self) -> None:
        """Reset the client instance. Useful for testing or reconfiguration."""
        self._client = None
        logger.info("[LLM] Client reset")


# Global instance for backward compatibility
_default_manager = LLMClientManager()


def get_llm_client() -> LLM:
    """Get or create LLM client using default manager."""
    return _default_manager.get_client()


def get_llm_config() -> LLMConfig:
    """Get current LLM configuration without creating client."""
    return LLMConfig.from_env()


def reset_llm_client() -> None:
    """Reset the default LLM client. Useful for testing."""
    _default_manager.reset()
