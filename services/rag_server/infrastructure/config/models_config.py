"""Model configuration management using Pydantic for type safety and validation."""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class LLMConfig(BaseModel):
    """Configuration for the main LLM."""

    provider: Literal["ollama", "openai", "anthropic", "google", "deepseek", "moonshot"]
    model: str
    base_url: str | None = None
    timeout: int = 120
    keep_alive: str | None = None
    api_key: str | None = None

    @field_validator("model")
    @classmethod
    def model_must_exist(cls, v: str) -> str:
        """Validate that model name is not empty."""
        if not v or not v.strip():
            raise ValueError("LLM model name is required and cannot be empty")
        return v

    def validate_provider_requirements(self) -> None:
        """Validate that required fields are present for the selected provider."""
        if self.provider != "ollama" and not self.api_key:
            raise ValueError(
                f"API key is required for provider '{self.provider}'. "
                f"Set LLM_API_KEY environment variable."
            )


class EmbeddingConfig(BaseModel):
    """Configuration for the embedding model."""

    provider: str
    model: str
    base_url: str | None = None

    @field_validator("model")
    @classmethod
    def model_must_exist(cls, v: str) -> str:
        """Validate that model name is not empty."""
        if not v or not v.strip():
            raise ValueError("Embedding model name is required and cannot be empty")
        return v


class EvalConfig(BaseModel):
    """Configuration for the evaluation model."""

    provider: str
    model: str
    api_key: str | None = None

    @field_validator("model")
    @classmethod
    def model_must_exist(cls, v: str) -> str:
        """Validate that model name is not empty."""
        if not v or not v.strip():
            raise ValueError("Eval model name is required and cannot be empty")
        return v

    def validate_provider_requirements(self) -> None:
        """Validate that required fields are present for the selected provider."""
        if self.provider != "ollama" and not self.api_key:
            raise ValueError(
                f"API key is required for eval provider '{self.provider}'. "
                f"Set ANTHROPIC_API_KEY environment variable."
            )


class RerankerConfig(BaseModel):
    """Configuration for the reranker."""

    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_n: int = 5


class RetrievalConfig(BaseModel):
    """Configuration for retrieval settings."""

    top_k: int = 10
    enable_hybrid_search: bool = True
    rrf_k: int = 60
    enable_contextual_retrieval: bool = False


class ModelsConfig(BaseModel):
    """Root configuration for all models and retrieval settings."""

    llm: LLMConfig
    embedding: EmbeddingConfig
    eval: EvalConfig
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "ModelsConfig":
        """Load configuration from YAML file and inject secrets from environment.

        Args:
            config_path: Path to the models.yml file. If None, searches in standard locations.

        Returns:
            ModelsConfig instance with secrets injected.

        Raises:
            FileNotFoundError: If config file is not found.
            ValueError: If required secrets are missing or invalid.
        """
        # Determine config file path
        if config_path is None:
            # Try multiple standard locations
            possible_paths = [
                Path("/app/config/models.yml"),  # Docker path
                Path(__file__).parent.parent.parent.parent.parent
                / "config"
                / "models.yml",  # Development path
            ]
            config_path = next((p for p in possible_paths if p.exists()), None)
            if config_path is None:
                raise FileNotFoundError(
                    f"models.yml not found in standard locations: {possible_paths}"
                )
        else:
            config_path = Path(config_path)
            if not config_path.exists():
                raise FileNotFoundError(f"Config file not found: {config_path}")

        # Load YAML config
        with open(config_path) as f:
            data = yaml.safe_load(f)

        # Inject secrets from environment variables
        # LLM API key (provider-specific)
        llm_api_key = os.getenv("LLM_API_KEY")
        if "llm" in data and llm_api_key:
            data["llm"]["api_key"] = llm_api_key

        # Eval/Anthropic API key
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
        if "eval" in data and anthropic_api_key:
            data["eval"]["api_key"] = anthropic_api_key

        # Create and validate config
        config = cls(**data)

        # Run provider-specific validations
        config.llm.validate_provider_requirements()
        config.eval.validate_provider_requirements()

        return config


# Singleton instance
_models_config: ModelsConfig | None = None


def get_models_config(config_path: str | Path | None = None) -> ModelsConfig:
    """Get the singleton ModelsConfig instance.

    Args:
        config_path: Optional path to config file. Only used on first call.

    Returns:
        ModelsConfig instance.
    """
    global _models_config
    if _models_config is None:
        _models_config = ModelsConfig.load(config_path)
    return _models_config


def reset_models_config() -> None:
    """Reset the singleton instance. Used for testing."""
    global _models_config
    _models_config = None
