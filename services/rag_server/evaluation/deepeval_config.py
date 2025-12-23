"""DeepEval configuration with Anthropic Claude as LLM judge.

This module provides configuration for using Anthropic's Claude models
as the LLM-as-a-judge for DeepEval metrics evaluation.
"""

from deepeval.models import AnthropicModel
from infrastructure.config.models_config import get_models_config


def get_evaluator_model(
    model: str | None = None,
    temperature: float = 0.0
) -> AnthropicModel:
    """Get configured Anthropic model for DeepEval metrics.

    Args:
        model: Optional model name override (uses config/models.yml if not provided)
        temperature: Model temperature (default: 0.0 for deterministic evaluation)

    Returns:
        Configured AnthropicModel instance

    Raises:
        ValueError: If ANTHROPIC_API_KEY is not set in environment
    """
    config = get_models_config()

    # Validate API key is set
    if not config.eval.api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is required for evaluation. "
            "Set it in secrets/.env file."
        )

    # Use provided model or get from config
    model_name = model or config.eval.model

    return AnthropicModel(
        model=model_name,
        temperature=temperature
    )


# Default evaluator instance
def get_default_evaluator() -> AnthropicModel:
    """Get default evaluator with recommended settings for RAG evaluation."""
    return get_evaluator_model()
