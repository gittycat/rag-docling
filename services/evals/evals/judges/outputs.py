"""The judge's output contract: a JSON schema, a request format, and a parser.

Why this exists. The judge used to be prompted for free text and parsed by
scanning for a line beginning ``SCORE:``. That is tolerable against a frontier
model that follows formatting instructions and fragile against an open-weight
model served by vLLM, where a stray preamble, a markdown fence or a chatty
"Sure! SCORE: 0.8" changes what the parser sees. A malformed response is not a
low score — it is a lost sample — so format drift shows up as shrinking sample
sizes rather than as an obvious failure.

The contract has two levels, and the judge always accepts either:

1. **Constrained** — the request carries an OpenAI-style ``response_format`` with
   a JSON schema. vLLM enforces it with guided decoding, OpenAI with structured
   outputs; the model cannot emit anything else.
2. **Free text** — the historical ``SCORE:`` / ``REASONING:`` form, kept verbatim
   for endpoints that reject ``response_format`` (Anthropic's transport, older
   OpenAI-compatible servers, any stub).

``parse_judge_response`` tries JSON first and falls back to the text parser, so a
model that ignores the schema and answers in prose is still scored.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

# Bumped whenever the schema, the score scale or the prompt instructions change.
# It is part of the judge cache key: a cached score produced under a different
# output contract is not comparable to one produced under this contract.
JUDGE_CONTRACT_VERSION = "1"

# Providers whose transport speaks the OpenAI `response_format` field. Anthropic
# is deliberately absent: its API expresses the same idea through tool use, which
# is a different request shape, and the text fallback covers it correctly.
_STRUCTURED_OUTPUT_PROVIDERS = frozenset({"openai", "vllm"})

JUDGE_SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Score from 0.0 (worst) to 1.0 (best).",
        },
        "reasoning": {
            "type": "string",
            "description": "One or two sentences justifying the score.",
        },
    },
    "required": ["score", "reasoning"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ParsedJudgeOutput:
    """A validated judge verdict and how it was obtained."""

    score: float
    reasoning: str
    structured: bool


class JudgeError(Exception):
    """The judge could not produce a score.

    Raised instead of returning a 0.0 score: a failed judge call is missing data,
    not evidence of a bad answer. Callers exclude the sample from the average.

    Defined here rather than in llm_judge so the parser can raise it without
    importing the judge. ``evals.judges.llm_judge`` re-exports both names, which
    is where the rest of the codebase imports them from.
    """


class JudgeParseError(JudgeError):
    """The LLM response contained no parseable score."""


def supports_structured_output(provider: str) -> bool:
    """Whether this provider's transport accepts an OpenAI-style response_format."""
    return (provider or "").lower() in _STRUCTURED_OUTPUT_PROVIDERS


def judge_response_format(schema_name: str = "judge_score") -> dict[str, Any]:
    """The `response_format` request field constraining the reply to JUDGE_SCORE_SCHEMA.

    Understood by OpenAI (structured outputs) and by vLLM's OpenAI server (guided
    decoding). ``strict`` is what makes OpenAI enforce rather than merely suggest.
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema_name,
            "strict": True,
            "schema": JUDGE_SCORE_SCHEMA,
        },
    }


def output_format_instructions(structured: bool) -> str:
    """The prompt suffix telling the model how to answer.

    Kept next to the schema so the two cannot drift apart. The free-text wording
    is unchanged from before this module existed.
    """
    if structured:
        return (
            "Respond with a single JSON object and nothing else:\n"
            '{"score": <number between 0.0 and 1.0>, "reasoning": "<one or two sentences>"}'
        )
    return (
        "Provide your response in the following format:\n"
        "SCORE: [0.0-1.0]\n"
        "REASONING: [Your explanation]"
    )


def response_format_rejected(error: Exception) -> bool:
    """Whether an error looks like the endpoint refusing `response_format`.

    An OpenAI-compatible server that does not implement guided decoding answers a
    schema-constrained request with a 400 naming the field. That is a capability
    signal, not a transient failure: the judge downgrades to free text once and
    stops paying for the round trip. Matched on the message because the error type
    is whatever the transport raises.
    """
    text = f"{type(error).__name__}: {error}".lower()
    markers = ("response_format", "response format", "json_schema", "guided", "structured output")
    return any(marker in text for marker in markers)


# A model that emits ```json ... ``` is honoring the contract in spirit; strip the
# fence rather than lose the sample.
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_fence(raw: str) -> str:
    match = _FENCE.match(raw.strip())
    return match.group(1) if match else raw.strip()


def _coerce_score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise JudgeParseError(f"Judge score is not a number: {value!r}")
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise JudgeParseError(f"Judge score is not a number: {value!r}")
    if score != score or score in (float("inf"), float("-inf")):
        raise JudgeParseError(f"Judge score is not finite: {value!r}")
    # Clamp rather than reject: an out-of-range score is a scale mistake, not an
    # unreadable answer, and the text parser has always clamped.
    return max(0.0, min(1.0, score))


def parse_structured_response(raw: str) -> ParsedJudgeOutput:
    """Parse and validate a JSON judge verdict. Raises JudgeParseError otherwise."""
    try:
        payload = json.loads(_strip_fence(raw))
    except (json.JSONDecodeError, TypeError) as e:
        raise JudgeParseError(f"Judge response is not JSON: {raw.strip()[:200]!r}") from e

    if not isinstance(payload, dict):
        raise JudgeParseError(f"Judge response is not a JSON object: {raw.strip()[:200]!r}")
    if "score" not in payload:
        raise JudgeParseError(f"Judge JSON has no 'score' key: {sorted(payload)!r}")

    reasoning = payload.get("reasoning", "")
    if reasoning is None:
        reasoning = ""
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)

    return ParsedJudgeOutput(
        score=_coerce_score(payload["score"]),
        reasoning=reasoning.strip(),
        structured=True,
    )


def parse_text_response(raw: str) -> ParsedJudgeOutput:
    """Parse the historical SCORE:/REASONING: form. Raises JudgeParseError otherwise."""
    lines = raw.strip().split("\n")
    score: float | None = None
    reasoning = ""

    for line in lines:
        line = line.strip()
        if line.upper().startswith("SCORE:") and score is None:
            score_str = line.split(":", 1)[1].strip()
            # Handle various formats: "0.8", "0.8/1", "80%"
            is_percent = "%" in score_str
            score_str = score_str.replace("/1", "").replace("%", "")
            try:
                parsed = float(score_str)
            except ValueError:
                raise JudgeParseError(f"Unparseable score in judge response: {line!r}")
            if is_percent:
                parsed /= 100
            score = max(0.0, min(1.0, parsed))  # Clamp to 0-1
        elif line.upper().startswith("REASONING:"):
            reasoning = line.split(":", 1)[1].strip()

    # If reasoning not found in REASONING: line, use remainder of response
    if not reasoning:
        score_line_found = False
        for line in lines:
            if line.upper().startswith("SCORE:"):
                score_line_found = True
            elif score_line_found:
                reasoning += line + " "
        reasoning = reasoning.strip()

    if score is None:
        raise JudgeParseError(f"No SCORE line in judge response: {raw.strip()[:200]!r}")

    return ParsedJudgeOutput(score=score, reasoning=reasoning, structured=False)


def parse_judge_response(raw: str) -> ParsedJudgeOutput:
    """Parse a judge reply in either form.

    JSON first because a constrained endpoint always produces it; the text parser
    catches models that ignored the schema. Both failing is a real parse failure
    and must reach the retry loop — a 0.0 here would be indistinguishable from a
    genuine "not grounded at all" verdict.
    """
    stripped = _strip_fence(raw or "")
    if stripped.startswith("{"):
        try:
            return parse_structured_response(raw)
        except JudgeParseError:
            # A truncated or malformed JSON object may still carry a SCORE: line.
            pass
    return parse_text_response(raw or "")
