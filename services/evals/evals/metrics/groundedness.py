"""Claim-level groundedness and claim-to-citation entailment.

What the existing metrics miss. `metrics/citation.py` scores a citation against
the dataset's gold passage set: a citation is "correct" when the chunk it points
at is one of the passages annotated relevant for the question. That is a
*retrieval* question wearing a citation's clothes. It is satisfied by an answer
that cites a gold passage after a sentence the passage does not support, and it
is unsatisfiable on any dataset without passage annotations.

`metrics/generation.py`'s `faithfulness` is the other half of the blind spot: one
judge call over the whole answer against the whole context. It can say an answer
drifted; it cannot say which sentence drifted, and it never looks at citations at
all — an answer with every citation pointing at the wrong chunk scores a perfect
1.0 as long as the union of the context supports the prose.

This group asks the question neither one asks: for each claim the answer makes,
does the passage *it cites* actually entail *it*?

| Metric | Question | Judge |
|---|---|---|
| `claim_groundedness` | is this claim supported anywhere in the retrieved context | yes |
| `citation_entailment` | does this cited passage support the claim it is attached to | yes |
| `claim_citation_support` | do this claim's own citations support it | yes (shared) |
| `uncited_claim_rate` | how many claims carry no citation at all | no |

Cost. Judging is per claim, and per (claim, citation) link on top of that, so an
uncapped answer could cost dozens of judge calls where `faithfulness` costs one.
`max_claims_per_answer` and `max_citations_per_claim` bound it, truncation is
reported in `details` rather than hidden, and the three judge metrics share a
single `ClaimEntailmentEvaluator` so the work is done once per question instead of
once per metric.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from evals.claims import Claim, extract_claims
from evals.judges import LLMJudge
from evals.metrics.abstention import is_abstention
from evals.metrics.base import BaseMetric
from evals.metrics.citation import chunk_by_rank
from evals.schemas import (
    EvalQuestion,
    EvalResponse,
    MetricGroup,
    MetricResult,
)

logger = logging.getLogger(__name__)

# Claims per answer and citations per claim that get judged. Both are cost brakes,
# not statements about what matters: an answer's later claims are as real as its
# first ones, so truncation is always reported.
DEFAULT_MAX_CLAIMS = 5
DEFAULT_MAX_CITATIONS_PER_CLAIM = 2

# A link at or above this counts as "supported" for the claim-level tally. 0.5 is
# the rubric's "supports part of the claim", so a claim whose citation covers only
# half of what it asserts counts as supported here and is visible as a fractional
# score in `citation_entailment`. The two metrics disagreeing is the signal.
SUPPORT_THRESHOLD = 0.5


@dataclass
class ClaimAnalysis:
    """Everything the four metrics need for one question, judged once."""

    claims: list[Claim] = field(default_factory=list)
    # claim index -> entailment against the whole retrieved context
    context_scores: dict[int, float] = field(default_factory=dict)
    # (claim index, 1-based source index) -> entailment against that one passage
    link_scores: dict[tuple[int, int], float] = field(default_factory=dict)
    truncated_claims: int = 0
    truncated_links: int = 0
    unresolved_citations: int = 0
    note: str | None = None

    @property
    def cited_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.is_cited]


def _links_for(analysis: ClaimAnalysis, claim: Claim) -> list[float]:
    return [
        score
        for (claim_index, _source), score in analysis.link_scores.items()
        if claim_index == claim.index
    ]


class ClaimEntailmentEvaluator:
    """Judges the claims of one answer, once, for every metric in this group.

    Three metrics need overlapping slices of the same judged work. Letting each
    compute its own would triple the judge bill and — because the judge cache is
    keyed by prompt, not by run — hide that behind cache hits only on the second
    and third pass. The evaluator memoizes per question id and holds an in-flight
    task, so concurrent metrics await the same computation rather than racing to
    duplicate it.
    """

    def __init__(
        self,
        judge: LLMJudge,
        max_claims: int = DEFAULT_MAX_CLAIMS,
        max_citations_per_claim: int = DEFAULT_MAX_CITATIONS_PER_CLAIM,
        concurrency: int = 8,
    ):
        self.judge = judge
        self.max_claims = max_claims
        self.max_citations_per_claim = max_citations_per_claim
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def analyze(self, question: EvalQuestion, response: EvalResponse) -> ClaimAnalysis:
        key = question.id
        async with self._lock:
            task = self._tasks.get(key)
            if task is None:
                task = asyncio.create_task(self._analyze(response))
                self._tasks[key] = task
        return await task

    def reset(self) -> None:
        """Drop memoized analyses. Called between batches, not between metrics."""
        self._tasks.clear()

    async def _score(self, claim: Claim, passage: str) -> float:
        async with self._sem:
            result = await self.judge.evaluate_entailment(claim=claim.text, passage=passage)
        return result.score

    async def _analyze(self, response: EvalResponse) -> ClaimAnalysis:
        answer = response.answer or ""

        # A refusal makes no claims. Scoring it 0.0 would punish exactly the
        # behaviour the abstention metrics reward; it is undefined here.
        if is_abstention(answer):
            return ClaimAnalysis(note="Answer is an abstention — no claims to ground")

        all_claims = extract_claims(answer)
        if not all_claims:
            return ClaimAnalysis(note="No claim-like sentences found in the answer")

        claims = all_claims[: self.max_claims]
        analysis = ClaimAnalysis(
            claims=claims,
            truncated_claims=len(all_claims) - len(claims),
        )

        context = "\n\n".join(c.text for c in response.retrieved_chunks if c.text)
        chunks = chunk_by_rank(response)

        # (coroutine, where its result belongs) so one gather covers both passes.
        jobs: list[tuple[Any, tuple[str, Any]]] = []

        if context:
            for claim in claims:
                jobs.append((self._score(claim, context), ("context", claim.index)))

        for claim in claims:
            cited = claim.source_indices[: self.max_citations_per_claim]
            analysis.truncated_links += len(claim.source_indices) - len(cited)
            for source_index in cited:
                chunk = chunks.get(source_index)
                if chunk is None or not chunk.text:
                    # The answer cited a source number that was never retrieved.
                    # That is a real defect, but an entailment score cannot express
                    # it: there is no passage to judge against. Counted, not scored.
                    analysis.unresolved_citations += 1
                    continue
                jobs.append(
                    (self._score(claim, chunk.text), ("link", (claim.index, source_index)))
                )

        if not jobs:
            if not context:
                analysis.note = "No context retrieved"
            return analysis

        results = await asyncio.gather(*(job for job, _ in jobs), return_exceptions=True)

        for (_, (kind, target)), result in zip(jobs, results):
            if isinstance(result, BaseException):
                # A failed judge call is missing data, not a zero. Dropping the
                # entry keeps it out of every average that would have used it.
                logger.warning(f"[GROUNDEDNESS] Entailment call failed ({kind}): {result}")
                continue
            if kind == "context":
                analysis.context_scores[target] = result
            else:
                analysis.link_scores[target] = result

        return analysis


def _undefined(metric: BaseMetric, note: str) -> MetricResult:
    return MetricResult(
        name=metric.name,
        value=None,
        group=metric.group,
        sample_size=0,
        details={"note": note},
    )


def _truncation_details(analysis: ClaimAnalysis) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if analysis.truncated_claims:
        details["truncated_claims"] = analysis.truncated_claims
    if analysis.truncated_links:
        details["truncated_links"] = analysis.truncated_links
    if analysis.unresolved_citations:
        details["unresolved_citations"] = analysis.unresolved_citations
    return details


class _GroundednessMetric(BaseMetric):
    """Shared plumbing: every metric here reads one shared ClaimAnalysis."""

    def __init__(self, evaluator: ClaimEntailmentEvaluator):
        self.evaluator = evaluator

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.GROUNDEDNESS

    @property
    def requires_gold(self) -> bool:
        return False

    @property
    def requires_judge(self) -> bool:
        return True


class ClaimGroundedness(_GroundednessMetric):
    """Fraction of the answer's claims that the retrieved context supports.

    `faithfulness` asks the same question in one call over the whole answer; this
    asks it per claim, so a single fabricated sentence in an otherwise grounded
    answer moves the score by a known amount instead of being averaged away inside
    one judge's holistic impression.

    Higher is better. 1.0 means every claim is supported by the context.
    """

    @property
    def name(self) -> str:
        return "claim_groundedness"

    @property
    def description(self) -> str:
        return "Fraction of the answer's claims supported by the retrieved context"

    async def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        analysis = await self.evaluator.analyze(question, response)

        if not analysis.claims:
            return _undefined(self, analysis.note or "No claims in the answer")

        if not any(c.text for c in response.retrieved_chunks):
            # Claims with no context behind them are ungrounded, not unmeasurable.
            return MetricResult(
                name=self.name,
                value=0.0,
                group=self.group,
                sample_size=1,
                details={"note": "No context retrieved", "claim_count": len(analysis.claims)},
            )

        scores = list(analysis.context_scores.values())
        if not scores:
            return _undefined(self, "Every entailment call failed for this question")

        return MetricResult(
            name=self.name,
            value=sum(scores) / len(scores),
            group=self.group,
            sample_size=1,
            details={
                "claim_count": len(analysis.claims),
                "judged_claims": len(scores),
                "ungrounded_claims": [
                    analysis.claims[i].text[:160]
                    for i, score in analysis.context_scores.items()
                    if score < SUPPORT_THRESHOLD
                ],
                **_truncation_details(analysis),
            },
        )


class CitationEntailment(_GroundednessMetric):
    """Fraction of citation links whose passage entails the claim it is attached to.

    One score per (claim, cited passage) pair — the metric `citation_precision`
    only appears to provide. Where `citation_precision` asks "was this chunk in the
    gold set", this asks "does this chunk say what the sentence citing it says",
    which is the property a reader checks when they follow a citation.

    Needs `eval.citation_scope: explicit` in config.yml; without it the model is
    never asked for inline markers, there are no links, and this is undefined.

    Higher is better. 1.0 means every citation supports its claim.
    """

    @property
    def name(self) -> str:
        return "citation_entailment"

    @property
    def description(self) -> str:
        return "Fraction of citation links whose passage entails the claim citing it"

    async def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        analysis = await self.evaluator.analyze(question, response)

        if not analysis.claims:
            return _undefined(self, analysis.note or "No claims in the answer")
        if not analysis.cited_claims:
            return _undefined(
                self,
                "No inline citations in the answer — set eval.citation_scope to "
                "'explicit' in config.yml for the model to emit them",
            )
        if not analysis.link_scores:
            return _undefined(self, "No citation could be resolved to a retrieved passage")

        scores = list(analysis.link_scores.values())

        return MetricResult(
            name=self.name,
            value=sum(scores) / len(scores),
            group=self.group,
            sample_size=1,
            details={
                "link_count": len(scores),
                "unsupported_links": sum(1 for s in scores if s < SUPPORT_THRESHOLD),
                **_truncation_details(analysis),
            },
        )


class ClaimCitationSupport(_GroundednessMetric):
    """Fraction of cited claims that at least one of their own citations supports.

    The claim-level view of the same links `citation_entailment` averages. They
    separate when a claim carries several citations and only one of them is apt:
    the link average drops, this stays at 1.0. A gap between the two is a
    shotgun-citation signal — the answer citing everything nearby and landing on
    the right passage by volume.

    Higher is better. 1.0 means every cited claim is backed by what it cites.
    """

    @property
    def name(self) -> str:
        return "claim_citation_support"

    @property
    def description(self) -> str:
        return "Fraction of cited claims backed by at least one of their own citations"

    async def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        analysis = await self.evaluator.analyze(question, response)

        if not analysis.claims:
            return _undefined(self, analysis.note or "No claims in the answer")

        cited = analysis.cited_claims
        if not cited:
            return _undefined(
                self,
                "No inline citations in the answer — set eval.citation_scope to "
                "'explicit' in config.yml for the model to emit them",
            )

        judged = [(claim, _links_for(analysis, claim)) for claim in cited]
        judged = [(claim, scores) for claim, scores in judged if scores]
        if not judged:
            return _undefined(self, "No citation could be resolved to a retrieved passage")

        supported = sum(1 for _, scores in judged if max(scores) >= SUPPORT_THRESHOLD)

        return MetricResult(
            name=self.name,
            value=supported / len(judged),
            group=self.group,
            sample_size=1,
            details={
                "cited_claims": len(cited),
                "judged_claims": len(judged),
                "supported_claims": supported,
                "unsupported_claims": [
                    claim.text[:160] for claim, scores in judged
                    if max(scores) < SUPPORT_THRESHOLD
                ],
                **_truncation_details(analysis),
            },
        )


class UncitedClaimRate(BaseMetric):
    """Fraction of the answer's claims that carry no citation marker at all.

    The coverage side of attribution, and the reason the two entailment metrics
    cannot be read alone: an answer that cites one sentence perfectly and leaves
    nine uncited scores 1.0 on both of them. Needs no judge — a marker is either
    present or it is not.

    Lower is better. 0.0 means every claim is attributed. When *no* claim in the
    answer carries a marker, this is indistinguishable from `eval.citation_scope`
    being `'retrieved'`, under which the RAG server never asks the model for
    inline markers at all — every answer would score a constant 1.0 regardless
    of what it actually said. `CitationEntailment` and `ClaimCitationSupport`
    already treat "no cited claims" as undefined rather than data for the same
    reason; this metric follows suit instead of reporting a number that looks
    measured and is not.
    """

    def __init__(self, max_claims: int = DEFAULT_MAX_CLAIMS):
        self.max_claims = max_claims

    @property
    def name(self) -> str:
        return "uncited_claim_rate"

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.GROUNDEDNESS

    @property
    def description(self) -> str:
        return "Fraction of claims with no citation marker (lower is better)"

    @property
    def requires_gold(self) -> bool:
        return False

    def compute(
        self,
        question: EvalQuestion,
        response: EvalResponse,
        **kwargs: Any,
    ) -> MetricResult:
        answer = response.answer or ""
        if is_abstention(answer):
            return _undefined(self, "Answer is an abstention — no claims to attribute")

        all_claims = extract_claims(answer)
        if not all_claims:
            return _undefined(self, "No claim-like sentences found in the answer")

        claims = all_claims[: self.max_claims]
        uncited = sum(1 for c in claims if not c.is_cited)

        if uncited == len(claims):
            return _undefined(
                self,
                "No inline citations anywhere in the answer — set eval.citation_scope "
                "to 'explicit' in config.yml for this metric to be measurable",
            )

        return MetricResult(
            name=self.name,
            value=uncited / len(claims),
            group=self.group,
            sample_size=1,
            details={
                "claim_count": len(claims),
                "uncited_claims": uncited,
                "truncated_claims": len(all_claims) - len(claims),
            },
        )
