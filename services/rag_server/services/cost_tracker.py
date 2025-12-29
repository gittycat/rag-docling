"""Cost tracking service for LLM token usage and cost estimation.

Tracks token usage during evaluation runs and estimates costs
based on per-model pricing tables.
"""

import logging
from dataclasses import dataclass, field

from schemas.metrics import CostMetrics

logger = logging.getLogger(__name__)


# Token pricing per 1M tokens (as of December 2025)
# Format: {model_pattern: {"input": price, "output": price}}
TOKEN_PRICING: dict[str, dict[str, float]] = {
    # OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-mini": {"input": 3.00, "output": 12.00},
    # Anthropic models
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    # Google models
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    # DeepSeek models
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-coder": {"input": 0.14, "output": 0.28},
    # Moonshot models
    "moonshot-v1-8k": {"input": 0.012, "output": 0.012},
    "moonshot-v1-32k": {"input": 0.024, "output": 0.024},
    "moonshot-v1-128k": {"input": 0.06, "output": 0.06},
    # Ollama models (local, free)
    "gemma3": {"input": 0.0, "output": 0.0},
    "gemma2": {"input": 0.0, "output": 0.0},
    "llama3": {"input": 0.0, "output": 0.0},
    "llama2": {"input": 0.0, "output": 0.0},
    "mistral": {"input": 0.0, "output": 0.0},
    "mixtral": {"input": 0.0, "output": 0.0},
    "qwen": {"input": 0.0, "output": 0.0},
    "phi": {"input": 0.0, "output": 0.0},
    "neural-chat": {"input": 0.0, "output": 0.0},
    "codellama": {"input": 0.0, "output": 0.0},
    "nomic-embed-text": {"input": 0.0, "output": 0.0},
}

# Default pricing for unknown models (conservative estimate)
DEFAULT_PRICING = {"input": 1.00, "output": 3.00}


def get_model_pricing(model_name: str) -> dict[str, float]:
    """Get pricing for a model, matching by prefix.

    Args:
        model_name: Model name (e.g., "gpt-4o-mini", "gemma3:4b")

    Returns:
        Dict with "input" and "output" prices per 1M tokens
    """
    # Normalize model name (lowercase, strip version tags)
    normalized = model_name.lower().split(":")[0]

    # Try exact match first
    if normalized in TOKEN_PRICING:
        return TOKEN_PRICING[normalized]

    # Try prefix matching
    for pattern, pricing in TOKEN_PRICING.items():
        if normalized.startswith(pattern):
            return pricing

    logger.warning(f"Unknown model '{model_name}', using default pricing")
    return DEFAULT_PRICING


def estimate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost for a given number of tokens.

    Args:
        model_name: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Estimated cost in USD
    """
    pricing = get_model_pricing(model_name)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


@dataclass
class CostTracker:
    """Tracks token usage and cost during evaluation runs.

    Usage:
        tracker = CostTracker()
        for query in queries:
            result = await query_rag(query)
            tracker.track_query(result.input_tokens, result.output_tokens)
        metrics = tracker.get_metrics("gpt-4o-mini")
    """

    input_tokens: int = 0
    output_tokens: int = 0
    query_count: int = 0
    _per_query_tokens: list[tuple[int, int]] = field(default_factory=list)

    def track_query(self, input_tokens: int, output_tokens: int) -> None:
        """Track token usage for a single query.

        Args:
            input_tokens: Number of input tokens for this query
            output_tokens: Number of output tokens for this query
        """
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.query_count += 1
        self._per_query_tokens.append((input_tokens, output_tokens))

    def get_metrics(self, model_name: str) -> CostMetrics:
        """Get cost metrics for the tracked queries.

        Args:
            model_name: Model name for pricing lookup

        Returns:
            CostMetrics with totals and estimates
        """
        total_tokens = self.input_tokens + self.output_tokens
        total_cost = estimate_cost(model_name, self.input_tokens, self.output_tokens)
        cost_per_query = total_cost / max(self.query_count, 1)

        return CostMetrics(
            total_input_tokens=self.input_tokens,
            total_output_tokens=self.output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=round(total_cost, 6),
            cost_per_query_usd=round(cost_per_query, 6),
        )

    def reset(self) -> None:
        """Reset all tracked values."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.query_count = 0
        self._per_query_tokens.clear()
