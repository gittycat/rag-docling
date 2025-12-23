"""
LLM Configuration for multi-provider support.

Supports: Ollama, OpenAI, Anthropic, Google Gemini, DeepSeek, Moonshot (Kimi K2)

DEPRECATED: This module is deprecated. Use infrastructure.config.models_config instead.
Kept for backward compatibility during migration.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OLLAMA = "ollama"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    MOONSHOT = "moonshot"


@dataclass
class LLMConfig:
    """
    LLM configuration loaded from config file.

    Configuration is now loaded from config/models.yml instead of environment variables.
    API keys are still loaded from environment (secrets/.env).
    """
    provider: LLMProvider
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: float = 120.0
    keep_alive: Optional[str] = None  # Ollama-only

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """
        Load configuration from config file (config/models.yml).

        This method is kept for backward compatibility but now loads from
        the new config file instead of environment variables.
        """
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
                keep_alive=llm_config.keep_alive,
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
