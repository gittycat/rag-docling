"""
LLM provider types and internal configuration container.

Provides:
- LLMProvider enum: Canonical list of supported providers
- LLMConfig dataclass: Internal config container for provider functions

Configuration is loaded from config.yml via infrastructure.config.models_config.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers.

    To add a new provider: enum value here, a key field in BOTH
    services/evals/infrastructure/settings.py and services/rag_server/app/settings.py,
    an import mapping in infrastructure/llm/factory.py, a Docker secret declaration in
    the compose files, and a cost-table entry.
    """
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    # Any OpenAI-compatible HTTP endpoint we host ourselves (vLLM, TGI's OpenAI
    # shim, llama.cpp's server). The name follows rag_server's enum, which has
    # carried this value since self-hosted inference landed there; `base_url` is
    # what actually decides where it points, not the provider string.
    VLLM = "vllm"


@dataclass
class LLMConfig:
    """Internal configuration container for LLM provider functions."""

    provider: LLMProvider
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: float = 120.0
    # The judge runs at 0 for determinism (evals/judges/llm_judge.py). Every
    # provider entry in factory.py's _PROVIDER_CONFIG maps it, so a configured
    # temperature reaches the client instead of being silently dropped.
    temperature: Optional[float] = None

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load LLM config from config.yml."""
        from infrastructure.config.models_config import get_models_config

        try:
            models_config = get_models_config()
            llm_config = models_config.llm

            try:
                provider = LLMProvider(llm_config.provider)
            except ValueError:
                valid_providers = ", ".join(p.value for p in LLMProvider)
                raise ValueError(
                    f"Invalid LLM provider in config: '{llm_config.provider}'. "
                    f"Valid options: {valid_providers}"
                )

            return cls(
                provider=provider,
                model=llm_config.model,
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                timeout=llm_config.timeout,
            )
        except Exception as e:
            logger.error(f"Failed to load LLM config from file: {e}")
            raise

    def __repr__(self) -> str:
        """Safe repr that doesn't expose API key."""
        return (
            f"LLMConfig(provider={self.provider.value}, model={self.model}, "
            f"base_url={self.base_url}, timeout={self.timeout})"
        )
