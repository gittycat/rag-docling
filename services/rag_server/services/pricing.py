"""Model pricing for the RAG server — what /models/info publishes as its rates.

This mirrors `services/evals/evals/pricing.py` (the two services share no
package, the same way LLMProvider is mirrored). Keep the table and the matching
rules in step with that file.

The rule that matters: a model with no known rates is *unpriced*, and unpriced is
reported as null rather than 0.0. The table this replaced returned
{"input": 0.0, "output": 0.0} for anything it did not recognise, which priced
today's configured model (gpt-5-mini) at zero and would have made self-hosted
inference look free by default.
"""

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# JSON object mapping model id -> {"input": <usd per 1M>, "output": <usd per 1M>}.
# The injection point for an amortized self-hosted rate (GPU instance price
# divided by measured throughput) — no code change, no redeploy of this table:
#   MODEL_PRICE_OVERRIDES='{"Qwen/Qwen3-32B-AWQ": {"input": 0.42, "output": 0.42}}'
RATE_OVERRIDE_ENV = "MODEL_PRICE_OVERRIDES"


# USD per 1M tokens. Matched exactly, then by namespace wildcard ("vendor/*"),
# then by the final path segment so HF repo ids resolve.
MODEL_COSTS: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
    "gpt-5.6-sol": {"input": 5.00, "output": 30.00},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    # Anthropic
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.00},
    # Google, DeepSeek, and Moonshot providers are not currently supported
    # (no Docker secret declared) — see infrastructure/llm/config.py.
    #
    # Self-hosted open-weight models are absent on purpose: they are unpriced
    # until someone supplies a measured rate through MODEL_PRICE_OVERRIDES.
}


@dataclass(frozen=True)
class ModelRates:
    """Resolved per-1M-token rates plus where they came from."""

    input_per_1m: float
    output_per_1m: float
    source: str  # "environment" | "table"


def _normalize(model: str) -> str:
    return model.strip().lower()


def _basename(model: str) -> str:
    return model.rsplit("/", 1)[-1]


def _match(model: str, table: dict[str, dict[str, float]]) -> dict[str, float] | None:
    normalized = _normalize(model)
    by_key = {_normalize(key): value for key, value in table.items()}

    if normalized in by_key:
        return by_key[normalized]

    if "/" in normalized:
        wildcard = normalized.rsplit("/", 1)[0] + "/*"
        if wildcard in by_key:
            return by_key[wildcard]

    base = _basename(normalized)
    for key, value in by_key.items():
        if key.endswith("/*"):
            continue
        if _basename(key) == base:
            return value

    return None


def _env_overrides() -> dict[str, dict[str, float]]:
    raw = os.environ.get(RATE_OVERRIDE_ENV, "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"[PRICING] Ignoring malformed {RATE_OVERRIDE_ENV}: {e}")
        return {}

    if not isinstance(parsed, dict):
        logger.warning(f"[PRICING] {RATE_OVERRIDE_ENV} must be a JSON object of model -> rates")
        return {}

    overrides: dict[str, dict[str, float]] = {}
    for model, rates in parsed.items():
        try:
            overrides[model] = {
                "input": float(rates["input"]),
                "output": float(rates["output"]),
            }
        except (TypeError, KeyError, ValueError):
            # Dropped rather than defaulted — a malformed entry must not become $0.
            logger.warning(
                f"[PRICING] Ignoring {RATE_OVERRIDE_ENV} entry for '{model}': "
                'expected {"input": <usd per 1M>, "output": <usd per 1M>}'
            )
    return overrides


def resolve_rates(model: str | None) -> ModelRates | None:
    """Per-1M-token rates for a model, or None when it is unpriced."""
    if not model:
        return None

    override = _match(model, _env_overrides())
    if override is not None:
        return ModelRates(override["input"], override["output"], "environment")

    entry = _match(model, MODEL_COSTS)
    if entry is not None:
        return ModelRates(entry["input"], entry["output"], "table")

    logger.debug(f"[PRICING] No rates for '{model}' — reporting it as unpriced")
    return None
