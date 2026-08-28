"""Model pricing and token accounting — the single source of $/token truth.

"Unpriced" is a state of its own, distinct from free. `resolve_rates` returns
None for a model nobody has priced, and an unpriced model is excluded from cost
scoring rather than counted as $0: a model that has not been priced is
unmeasured, not free. The old table labelled every unmatched id as free, which
meant self-hosted inference won the cost objective by definition instead of by
measurement. Zero is a rate you configure explicitly, never a fallback.

Rates resolve in this order:

1. rates injected by the caller (`/models/info` already plumbs
   `cost_per_1m_input_tokens` / `cost_per_1m_output_tokens` into the runner),
2. the `MODEL_PRICE_OVERRIDES` environment mapping,
3. the static table below,
4. unpriced.

Layers 1 and 2 are how an amortized self-hosted rate — GPU instance price
divided by measured throughput — is supplied without a code change.
"""

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# JSON object mapping model id -> {"input": <usd per 1M>, "output": <usd per 1M>}.
# Ids match by the same rules as the static table, so an HF repo id works:
#   MODEL_PRICE_OVERRIDES='{"Qwen/Qwen3-32B-AWQ": {"input": 0.42, "output": 0.42}}'
RATE_OVERRIDE_ENV = "MODEL_PRICE_OVERRIDES"


# Cost lookup table (USD per 1M tokens). Ids are matched exactly, then by
# namespace wildcard ("vendor/*"), then by the final path segment so that HF
# repo ids resolve. A model that matches nothing is unpriced, not free.
MODEL_COSTS: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "claude-sonnet-5": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    # Retained for historical runs only — priced so an old run is not scored as
    # free even though this retired id returns 404 for new calls.
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.00},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
    "gpt-5.6-sol": {"input": 5.00, "output": 30.00},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # Google, DeepSeek, and Moonshot providers are not currently supported
    # (no Docker secret declared) — see rag_server/infrastructure/llm/config.py.
    #
    # Self-hosted open-weight models are deliberately absent. There used to be a
    # "vllm/*" entry priced at zero; it never matched anything, because a served
    # model is identified by its HF repo id ("Qwen/Qwen3-32B-AWQ"), not by the
    # server that hosts it. Restoring it would answer the question this table
    # exists to answer — is self-hosting cheaper — with an assumption. Supply the
    # amortized rate through MODEL_PRICE_OVERRIDES instead, including an explicit
    # zero if that is genuinely the intent.
}

# Per 1M input tokens. A self-hosted embedder is intentionally absent: it must
# receive a measured amortized rate through MODEL_PRICE_OVERRIDES, just like a
# self-hosted generation model. An explicit zero override remains valid.
EMBEDDING_COSTS: dict[str, float] = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}


@dataclass(frozen=True)
class ModelRates:
    """Resolved per-1M-token rates plus where they came from."""

    input_per_1m: float
    output_per_1m: float
    source: str  # "injected" | "environment" | "table"

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.input_per_1m
            + completion_tokens * self.output_per_1m
        ) / 1_000_000


@dataclass
class UsageTotals:
    """Token usage accumulated for one component of a run (generation, judging).

    Judge calls are three per query and dominate an eval run's token volume, so
    they are accounted separately rather than folded into the generation totals:
    the two numbers answer different questions.
    """

    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    # Calls the endpoint answered without a usage block. Recorded separately so a
    # zero cost is explainable: `calls: 0` means the sink never fired, while
    # `calls: 40, calls_without_usage: 40` means the provider reported nothing.
    calls_without_usage: int = 0

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Report one LLM call. This is the sink handed to the judge."""
        prompt = int(prompt_tokens or 0)
        completion = int(completion_tokens or 0)
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.calls += 1
        if prompt + completion == 0:
            self.calls_without_usage += 1

    @property
    def has_usage(self) -> bool:
        return self.calls > 0 and (self.prompt_tokens + self.completion_tokens) > 0

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "calls": self.calls,
            "calls_without_usage": self.calls_without_usage,
        }


def _normalize(model: str) -> str:
    return model.strip().lower()


def _basename(model: str) -> str:
    return model.rsplit("/", 1)[-1]


def _match(model: str, table: dict[str, dict[str, float]]) -> dict[str, float] | None:
    normalized = _normalize(model)
    by_key = {_normalize(key): value for key, value in table.items()}

    if normalized in by_key:
        return by_key[normalized]

    # Namespace wildcard: "vendor/*" matches "vendor/anything" and nothing else.
    # The previous implementation also matched on `provider in model.lower()`,
    # which made the wildcard both too broad and — for real HF ids — useless.
    if "/" in normalized:
        wildcard = normalized.rsplit("/", 1)[0] + "/*"
        if wildcard in by_key:
            return by_key[wildcard]

    # HF repo ids: "Qwen/Qwen3-32B-AWQ" resolves against a bare-name entry and a
    # bare name resolves against a repo-id entry. Only the final path segment is
    # compared, so no vendor prefix can swallow an unrelated id.
    base = _basename(normalized)
    for key, value in by_key.items():
        if key.endswith("/*"):
            continue
        if _basename(key) == base:
            return value

    return None


_env_cache: tuple[str, dict[str, dict[str, float]]] | None = None


def _env_overrides() -> dict[str, dict[str, float]]:
    global _env_cache

    raw = os.environ.get(RATE_OVERRIDE_ENV, "").strip()
    if not raw:
        return {}
    if _env_cache is not None and _env_cache[0] == raw:
        return _env_cache[1]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"[PRICING] Ignoring malformed {RATE_OVERRIDE_ENV}: {e}")
        _env_cache = (raw, {})
        return {}

    overrides: dict[str, dict[str, float]] = {}
    if not isinstance(parsed, dict):
        logger.warning(f"[PRICING] {RATE_OVERRIDE_ENV} must be a JSON object of model -> rates")
        parsed = {}

    for model, rates in parsed.items():
        try:
            overrides[model] = {
                "input": float(rates["input"]),
                "output": float(rates["output"]),
            }
        except (TypeError, KeyError, ValueError):
            # A malformed entry must not silently become $0 — drop it so the
            # model reads as unpriced and the operator sees why.
            logger.warning(
                f"[PRICING] Ignoring {RATE_OVERRIDE_ENV} entry for '{model}': "
                'expected {"input": <usd per 1M>, "output": <usd per 1M>}'
            )

    _env_cache = (raw, overrides)
    return overrides


def resolve_rates(
    model: str | None,
    input_per_1m: float | None = None,
    output_per_1m: float | None = None,
) -> ModelRates | None:
    """Resolve per-1M-token rates for a model, or None when it is unpriced.

    Injected rates win over everything, which is how a measured self-hosted rate
    is supplied. Passing only one half of the pair is an error rather than a
    half-priced model.
    """
    if (input_per_1m is None) != (output_per_1m is None):
        raise ValueError(
            "Injected rates must supply both cost_per_1m_input_tokens and "
            "cost_per_1m_output_tokens, or neither."
        )
    if input_per_1m is not None and output_per_1m is not None:
        return ModelRates(float(input_per_1m), float(output_per_1m), "injected")

    if not model:
        return None

    override = _match(model, _env_overrides())
    if override is not None:
        return ModelRates(override["input"], override["output"], "environment")

    entry = _match(model, MODEL_COSTS)
    if entry is not None:
        return ModelRates(entry["input"], entry["output"], "table")

    logger.debug(f"[PRICING] No rates for '{model}' — treating it as unpriced")
    return None


def is_priced(model: str | None) -> bool:
    return resolve_rates(model) is not None


def get_model_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    input_per_1m: float | None = None,
    output_per_1m: float | None = None,
) -> float | None:
    """Cost in USD for one call, or None when the model is unpriced."""
    rates = resolve_rates(model, input_per_1m, output_per_1m)
    if rates is None:
        return None
    return rates.cost(prompt_tokens, completion_tokens)


def resolve_embedding_rate(model: str | None) -> tuple[float, str] | None:
    """Resolve an embedding input-token rate, preserving unpriced as unknown."""
    if not model:
        return None
    override = _match(model, _env_overrides())
    if override is not None:
        return override["input"], "environment"
    table = {key: {"input": value, "output": value} for key, value in EMBEDDING_COSTS.items()}
    entry = _match(model, table)
    if entry is None:
        return None
    return entry["input"], "table"


def get_embedding_cost(model: str, tokens: int) -> float | None:
    """Embedding cost in USD, or None when the model is unpriced."""
    resolved = resolve_embedding_rate(model)
    if resolved is None:
        return None
    rate, _ = resolved
    return tokens * rate / 1_000_000
