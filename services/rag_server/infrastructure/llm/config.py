"""
LLM Configuration for multi-provider support.

Supports: Ollama, OpenAI, Anthropic, Google Gemini, DeepSeek, Moonshot (Kimi K2)
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from core.config import get_required_env, get_optional_env


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
    LLM configuration loaded from environment variables.

    Environment Variables:
        LLM_PROVIDER: Provider name (default: ollama)
        LLM_MODEL: Model name (required)
        LLM_API_KEY: API key (required for cloud providers)
        LLM_BASE_URL: Custom endpoint URL (optional)
        LLM_TIMEOUT: Request timeout in seconds (default: 120)
        OLLAMA_URL: Ollama server URL (legacy, for backward compat)
        OLLAMA_KEEP_ALIVE: Keep model loaded (Ollama-only, default: 10m)
    """
    provider: LLMProvider
    model: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: float = 120.0
    keep_alive: Optional[str] = None  # Ollama-only

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Load configuration from environment variables."""
        provider_str = get_optional_env("LLM_PROVIDER", "ollama").lower()

        try:
            provider = LLMProvider(provider_str)
        except ValueError:
            valid_providers = ", ".join(p.value for p in LLMProvider)
            raise ValueError(
                f"Invalid LLM_PROVIDER: '{provider_str}'. "
                f"Valid options: {valid_providers}"
            )

        # Default base_url by provider
        default_urls = {
            LLMProvider.OLLAMA: get_optional_env("OLLAMA_URL", "http://localhost:11434"),
            LLMProvider.MOONSHOT: "https://api.moonshot.cn/v1",
        }

        # Get base_url: explicit LLM_BASE_URL takes precedence
        base_url = get_optional_env("LLM_BASE_URL") or default_urls.get(provider)

        # Validate API key for cloud providers
        api_key = get_optional_env("LLM_API_KEY")
        if provider != LLMProvider.OLLAMA and not api_key:
            raise ValueError(
                f"LLM_API_KEY is required for provider '{provider.value}'. "
                f"Please set it in docker-compose.yml or environment."
            )

        return cls(
            provider=provider,
            model=get_required_env("LLM_MODEL"),
            api_key=api_key if api_key else None,
            base_url=base_url,
            timeout=float(get_optional_env("LLM_TIMEOUT", "120")),
            keep_alive=get_optional_env("OLLAMA_KEEP_ALIVE", "10m") if provider == LLMProvider.OLLAMA else None,
        )

    def __repr__(self) -> str:
        """Safe repr that doesn't expose API key."""
        return (
            f"LLMConfig(provider={self.provider.value}, model={self.model}, "
            f"base_url={self.base_url}, timeout={self.timeout})"
        )
