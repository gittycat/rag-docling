"""Splitting an answer into claims and the citations attached to each one.

Why this exists. Every citation metric in `metrics/citation.py` scores a citation
against the *gold passage set* — it asks whether the cited chunk is one of the
passages the dataset marked relevant. It never asks whether that chunk says what
the sentence citing it says. An answer can therefore cite a gold passage after a
sentence the passage does not support and score a perfect `citation_precision`.

Grounding an answer at claim level needs two things this module provides:

1. **The claims.** Sentence-level, not LLM-decomposed. An LLM decomposition step
   would be another judged call per question, non-deterministic, and would put a
   second model's segmentation between the answer and its score. Sentences are
   what the generator actually emits citations against, and sentence-level
   attribution is what the attribution literature (ALCE and successors) scores.
2. **Which citation belongs to which claim.** The RAG server's
   `extract_numeric_citations` flattens the whole answer into one de-duplicated
   list of source indices, losing the association entirely. The marker grammar
   here is deliberately the same as that function's, so a marker the server counts
   as a citation is a marker this module attaches to a claim.

Nothing here calls an LLM. Claim segmentation must be reproducible: the same
answer has to yield the same claims in every run, or per-question scores stop
being pairable across runs.
"""

import re
from dataclasses import dataclass

# Same grammar as rag_server's extract_numeric_citations: [1], [1,2], [1-3] and
# the parenthesised forms. Parsed here per claim rather than per answer.
_MARKER = re.compile(r"[\[(](\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)[\])]")

# Sentence boundary: terminal punctuation, optional closing quote/bracket, space.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+")

# Tokens that end in a period without ending a sentence. A split inside "e.g." or
# "Fig. 3" would manufacture a fragment claim and judge it against the context,
# which reads as an ungrounded claim when it is a segmentation artifact.
_ABBREVIATIONS = frozenset({
    "e.g.", "i.e.", "etc.", "cf.", "vs.", "al.", "fig.", "eq.", "no.", "approx.",
    "dr.", "mr.", "mrs.", "ms.", "prof.", "st.", "jr.", "sr.", "inc.", "ltd.",
    "sec.", "ch.", "pp.", "ref.", "est.", "min.", "max.", "avg.",
})

# Markdown scaffolding that carries no assertion of its own.
_LIST_PREFIX = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_HEADING_PREFIX = re.compile(r"^\s*#{1,6}\s+")

# A fragment shorter than this is a header, a label or a stray token, not a claim
# worth spending a judge call on.
_MIN_CLAIM_WORDS = 4


@dataclass(frozen=True)
class Claim:
    """One assertion from an answer, with the source indices cited alongside it.

    Attributes:
        index: 0-based position in the answer, used as the claim's identity in
            per-question detail maps.
        text: The sentence with its citation markers removed. This is what a judge
            is asked to check; leaving `[2]` in the text invites the judge to
            reason about the marker instead of the assertion.
        source_indices: 1-based source indices cited for this claim, in the order
            they appear. Empty when the claim carries no marker.
    """

    index: int
    text: str
    source_indices: tuple[int, ...] = ()

    @property
    def is_cited(self) -> bool:
        return bool(self.source_indices)


def parse_markers(text: str) -> list[int]:
    """1-based source indices from the citation markers in `text`, in order.

    Ranges expand; duplicates collapse. Mirrors the server's parsing so the two
    never disagree about what counts as a citation.
    """
    indices: list[int] = []
    seen: set[int] = set()

    for match in _MARKER.findall(text):
        for part in (p.strip() for p in match.split(",")):
            if "-" in part:
                bounds = [b.strip() for b in part.split("-", 1)]
                if len(bounds) == 2 and bounds[0].isdigit() and bounds[1].isdigit():
                    start, end = int(bounds[0]), int(bounds[1])
                    if start <= end:
                        for idx in range(start, end + 1):
                            if idx not in seen:
                                seen.add(idx)
                                indices.append(idx)
            elif part.isdigit():
                idx = int(part)
                if idx not in seen:
                    seen.add(idx)
                    indices.append(idx)

    return indices


def strip_markers(text: str) -> str:
    """The sentence without its citation markers, whitespace normalized.

    Removing "[1]" from "each chunk [1]." leaves "each chunk ." — a space before
    punctuation that a judge reads as a typo in the claim it is scoring. Closed up
    here rather than left for the prompt to tolerate.
    """
    stripped = re.sub(r"\s+", " ", _MARKER.sub("", text))
    return re.sub(r"\s+([.,;:!?])", r"\1", stripped).strip()


def _segments(answer: str) -> list[str]:
    """Paragraph and list-item blocks, with soft line wraps rejoined.

    A generator's answer is wrapped at whatever width it felt like. Splitting on
    newlines would cut "This reduces\\nretrieval failures" into two fragments and
    judge each half as a claim, so a line only starts a new segment when it starts
    a new list item, a new heading, or follows a blank line.
    """
    segments: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            segments.append(" ".join(current))
            current.clear()

    for raw_line in answer.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if _LIST_PREFIX.match(raw_line) or _HEADING_PREFIX.match(raw_line):
            flush()
            line = _HEADING_PREFIX.sub("", _LIST_PREFIX.sub("", raw_line)).strip()
        current.append(line)

    flush()
    return segments


def _ends_with_abbreviation(fragment: str) -> bool:
    tail = fragment.rstrip().split()
    if not tail:
        return False
    last = tail[-1].lower()
    if last in _ABBREVIATIONS:
        return True
    # A single initial ("J.") or a decimal that swallowed the boundary ("3.").
    return bool(re.fullmatch(r"(?:[a-z]|\d+)\.", last))


def _split_sentences(text: str) -> list[str]:
    """Split on sentence boundaries, rejoining splits made inside abbreviations."""
    pieces = _SENTENCE_BOUNDARY.split(text)
    sentences: list[str] = []

    for piece in pieces:
        if sentences and _ends_with_abbreviation(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {piece}"
        else:
            sentences.append(piece)

    return sentences


def _is_claim(text: str) -> bool:
    """Whether a stripped sentence asserts something worth grounding."""
    if not text or not any(c.isalpha() for c in text):
        return False
    if text.rstrip().endswith("?"):
        return False  # a question the answer poses is not a claim it makes
    return len(text.split()) >= _MIN_CLAIM_WORDS


def extract_claims(answer: str, max_claims: int | None = None) -> list[Claim]:
    """Segment `answer` into claims, each carrying the sources cited for it.

    A marker that trails the sentence terminator ("... in 2021. [2] The next
    sentence") belongs to the sentence before it — that is where generators
    routinely put it — so leading markers are handed back to the previous claim
    rather than credited to the one that happens to follow.

    `max_claims` truncates from the front; callers report the truncation so a
    capped answer is visibly capped rather than quietly scored on a prefix.
    """
    if not answer or not answer.strip():
        return []

    claims: list[Claim] = []
    pending_indices: list[int] = []  # markers that opened a line, owed backwards

    for segment in _segments(answer):
        for sentence in _split_sentences(segment):
            sentence = sentence.strip()
            if not sentence:
                continue

            indices = parse_markers(sentence)
            text = strip_markers(sentence)

            # Markers before any prose in this sentence belong to the previous
            # claim; a marker after prose belongs to this one.
            leading = _MARKER.match(sentence)
            if leading and not text and indices:
                pending_indices.extend(indices)
                continue
            if leading and indices:
                head = sentence[: leading.end()]
                owed = parse_markers(head)
                if claims:
                    claims[-1] = _with_indices(claims[-1], owed)
                indices = [i for i in indices if i not in owed]

            if pending_indices:
                if claims:
                    claims[-1] = _with_indices(claims[-1], pending_indices)
                pending_indices = []

            if not _is_claim(text):
                continue

            claims.append(Claim(index=len(claims), text=text, source_indices=tuple(indices)))

    if pending_indices and claims:
        claims[-1] = _with_indices(claims[-1], pending_indices)

    if max_claims is not None and len(claims) > max_claims:
        return claims[:max_claims]
    return claims


def _with_indices(claim: Claim, extra: list[int]) -> Claim:
    merged = list(claim.source_indices)
    for idx in extra:
        if idx not in merged:
            merged.append(idx)
    return Claim(index=claim.index, text=claim.text, source_indices=tuple(merged))
