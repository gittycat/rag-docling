"""DeepEval configuration with Anthropic Claude as LLM judge.

This module provides configuration for using Anthropic's Claude models
as the LLM-as-a-judge for DeepEval metrics evaluation.
"""

import os
from deepeval.models import AnthropicModel


def get_evaluator_model(
    model: str = "claude-sonnet-4-20250514",
    temperature: float = 0.0
) -> AnthropicModel:
    """Get configured Anthropic model for DeepEval metrics.

    Args:
        model: Anthropic model name (default: claude-sonnet-4-20250514 for cost-effectiveness)
        temperature: Model temperature (default: 0.0 for deterministic evaluation)

    Returns:
        Configured AnthropicModel instance

    Raises:
        ValueError: If ANTHROPIC_API_KEY environment variable is not set
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY environment variable is required for evaluation. "
            "Set it in your .env file or environment."
        )

    # Override with env var if set
    model = os.getenv("EVAL_MODEL", model)

    return AnthropicModel(
        model=model,
        temperature=temperature
    )


# Default evaluator instance
def get_default_evaluator() -> AnthropicModel:
    """Get default evaluator with recommended settings for RAG evaluation."""
    return get_evaluator_model()
