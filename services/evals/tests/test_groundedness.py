"""Claim segmentation and the groundedness metric group.

The judge is stubbed throughout: these tests are about which claim gets checked
against which passage, and what the metrics do when there is nothing to check.
Whether a real judge scores a given pair correctly is the calibration suite's
question, not this one's.
"""

import asyncio

import pytest

from evals.claims import Claim, extract_claims, parse_markers, strip_markers
from evals.judges.llm_judge import JudgeResult
from evals.metrics.groundedness import (
    CitationEntailment,
    ClaimCitationSupport,
    ClaimEntailmentEvaluator,
    ClaimGroundedness,
    UncitedClaimRate,
)
from evals.schemas import EvalQuestion, EvalResponse, RetrievedChunk


# ── Fixtures ──────────────────────────────────────────────────────────────────


class StubJudge:
    """Scores (claim, passage) pairs from a lookup, recording every call."""

    def __init__(self, scores: dict[tuple[str, str], float] | None = None, default: float = 1.0):
        self.scores = scores or {}
        self.default = default
        self.calls: list[tuple[str, str]] = []

    async def evaluate_entailment(self, claim: str, passage: str) -> JudgeResult:
        self.calls.append((claim, passage))
        for (claim_key, passage_key), score in self.scores.items():
            if claim_key in claim and passage_key in passage:
                return JudgeResult(metric_name="entailment", score=score)
        return JudgeResult(metric_name="entailment", score=self.default)


def _question(qid: str = "q1") -> EvalQuestion:
    return EvalQuestion(id=qid, question="What changed?", expected_answer="")


def _response(answer: str, chunks: list[str]) -> EvalResponse:
    return EvalResponse(
        question_id="q1",
        answer=answer,
        retrieved_chunks=[
            RetrievedChunk(
                doc_id=f"doc-{i}",
                chunk_id=f"chunk-{i}",
                text=text,
                rank=i + 1,
            )
            for i, text in enumerate(chunks)
        ],
    )


def _evaluator(judge, **kwargs) -> ClaimEntailmentEvaluator:
    return ClaimEntailmentEvaluator(judge=judge, **kwargs)


# ── Claim segmentation ────────────────────────────────────────────────────────


class TestClaimSegmentation:
    def test_marker_attaches_to_its_own_sentence(self):
        claims = extract_claims(
            "Reranking runs after hybrid search [1]. Latency grows with top-k [2]."
        )

        assert [c.source_indices for c in claims] == [(1,), (2,)]

    def test_trailing_marker_belongs_to_the_preceding_claim(self):
        # Generators routinely put the marker after the terminator. Crediting it
        # to the sentence that follows would score the wrong pair.
        claims = extract_claims(
            "The cache is content addressed. [2] The key covers the fingerprint."
        )

        assert claims[0].source_indices == (2,)
        assert claims[1].source_indices == ()

    def test_ranges_and_lists_expand(self):
        assert parse_markers("supported [1-3] and also [5, 7]") == [1, 2, 3, 5, 7]

    def test_soft_wrapped_sentence_is_one_claim(self):
        # Splitting on newlines would judge "This reduces" as its own claim.
        claims = extract_claims("This reduces retrieval\nfailures by about 35% [2].")

        assert len(claims) == 1
        assert claims[0].text == "This reduces retrieval failures by about 35%."

    def test_abbreviation_does_not_end_a_sentence(self):
        claims = extract_claims("See Fig. 3 for the full ablation table [1].")

        assert len(claims) == 1

    def test_markers_are_stripped_without_leaving_a_gap(self):
        assert strip_markers("each chunk [1].") == "each chunk."

    def test_short_fragments_and_questions_are_not_claims(self):
        claims = extract_claims("Summary\n\nOk.\n\nWhat about the reranker?")

        assert claims == []

    def test_list_items_are_separate_claims(self):
        claims = extract_claims(
            "- The reranker runs after hybrid search [1].\n"
            "- Costs rise with the corpus size [2]."
        )

        assert len(claims) == 2
        assert claims[1].source_indices == (2,)


# ── claim_groundedness ────────────────────────────────────────────────────────


class TestClaimGroundedness:
    async def test_all_claims_grounded(self):
        judge = StubJudge(default=1.0)
        metric = ClaimGroundedness(_evaluator(judge))
        response = _response(
            "Reranking runs after hybrid search [1]. Latency grows with top-k [1].",
            ["Reranking is applied to the fused result set. Latency scales with top-k."],
        )

        result = await metric.compute(_question(), response)

        assert result.value == 1.0
        assert result.details["claim_count"] == 2

    async def test_one_fabricated_claim_moves_the_score(self):
        # The point of the metric: `faithfulness` averages this away inside one
        # holistic verdict, this reports it as a known fraction.
        judge = StubJudge({("moon", ""): 0.0}, default=1.0)
        metric = ClaimGroundedness(_evaluator(judge))
        response = _response(
            "Reranking runs after hybrid search. The index is stored on the moon.",
            ["Reranking is applied to the fused result set."],
        )

        result = await metric.compute(_question(), response)

        assert result.value == 0.5
        assert result.details["ungrounded_claims"] == ["The index is stored on the moon."]

    async def test_abstention_is_undefined_not_zero(self):
        metric = ClaimGroundedness(_evaluator(StubJudge()))
        response = _response("I don't have enough information to answer.", ["some context"])

        result = await metric.compute(_question(), response)

        assert result.value is None

    async def test_no_context_scores_zero(self):
        metric = ClaimGroundedness(_evaluator(StubJudge()))
        response = _response("Reranking runs after hybrid search here.", [])

        result = await metric.compute(_question(), response)

        assert result.value == 0.0

    async def test_claims_are_capped(self):
        judge = StubJudge()
        metric = ClaimGroundedness(_evaluator(judge, max_claims=2))
        answer = " ".join(f"Claim number {i} is asserted here." for i in range(5))

        result = await metric.compute(_question(), _response(answer, ["context text"]))

        assert result.details["claim_count"] == 2
        assert result.details["truncated_claims"] == 3


# ── citation_entailment ───────────────────────────────────────────────────────


class TestCitationEntailment:
    async def test_citation_pointing_at_an_unsupporting_passage_scores_zero(self):
        # The gap this group exists to close: chunk-2 is a perfectly good retrieved
        # passage, so every metric in metrics/citation.py can score this 1.0.
        judge = StubJudge({("reranker", "reranker"): 1.0, ("embedding", "reranker"): 0.0})
        metric = CitationEntailment(_evaluator(judge))
        response = _response(
            "The embedding model was changed to a TEI endpoint [1].",
            ["The reranker runs after hybrid search."],
        )

        result = await metric.compute(_question(), response)

        assert result.value == 0.0
        assert result.details["unsupported_links"] == 1

    async def test_each_link_is_judged_against_its_own_passage(self):
        judge = StubJudge()
        metric = CitationEntailment(_evaluator(judge))
        response = _response(
            "The reranker runs after hybrid search [1]. Costs rise with corpus size [2].",
            ["Reranking is applied to the fused set.", "Cost grows with the corpus."],
        )

        await metric.compute(_question(), response)

        links = [(c, p) for c, p in judge.calls if "\n\n" not in p]
        assert ("The reranker runs after hybrid search.", "Reranking is applied to the fused set.") in links
        assert ("Costs rise with corpus size.", "Cost grows with the corpus.") in links

    async def test_undefined_without_inline_citations(self):
        # citation_scope: retrieved — the model was never asked for markers, so
        # there is nothing to check. Zero would read as "every citation is wrong".
        metric = CitationEntailment(_evaluator(StubJudge()))
        response = _response("The reranker runs after hybrid search.", ["some context"])

        result = await metric.compute(_question(), response)

        assert result.value is None
        assert "citation_scope" in result.details["note"]

    async def test_citation_to_a_missing_source_is_counted_not_scored(self):
        judge = StubJudge()
        metric = CitationEntailment(_evaluator(judge))
        response = _response(
            "The reranker runs after hybrid search [7].",
            ["Reranking is applied to the fused set."],
        )

        result = await metric.compute(_question(), response)

        assert result.value is None
        assert "resolved" in result.details["note"]

    async def test_citations_per_claim_are_capped(self):
        judge = StubJudge()
        metric = CitationEntailment(_evaluator(judge, max_citations_per_claim=1))
        response = _response(
            "The reranker runs after hybrid search [1,2].",
            ["Reranking is applied.", "Also about reranking."],
        )

        result = await metric.compute(_question(), response)

        assert result.details["link_count"] == 1
        assert result.details["truncated_links"] == 1


# ── claim_citation_support ────────────────────────────────────────────────────


class TestClaimCitationSupport:
    async def test_one_apt_citation_supports_the_claim(self):
        # Diverges from citation_entailment on purpose: the link average drops to
        # 0.5, the claim is still backed by something it cited.
        judge = StubJudge({("reranker", "Reranking"): 1.0, ("reranker", "Cost"): 0.0})
        evaluator = _evaluator(judge)
        response = _response(
            "The reranker runs after hybrid search [1,2].",
            ["Reranking is applied to the fused set.", "Cost grows with the corpus."],
        )

        support = await ClaimCitationSupport(evaluator).compute(_question(), response)
        links = await CitationEntailment(evaluator).compute(_question(), response)

        assert support.value == 1.0
        assert links.value == 0.5

    async def test_claim_whose_every_citation_misses(self):
        judge = StubJudge(default=0.0)
        metric = ClaimCitationSupport(_evaluator(judge))
        response = _response(
            "The embedding model changed to a TEI endpoint [1].",
            ["Reranking is applied to the fused set."],
        )

        result = await metric.compute(_question(), response)

        assert result.value == 0.0
        assert result.details["unsupported_claims"] == [
            "The embedding model changed to a TEI endpoint."
        ]

    async def test_uncited_claims_are_excluded_not_failed(self):
        # An uncited claim is uncited_claim_rate's business. Counting it as
        # unsupported here would double-charge the same defect.
        judge = StubJudge(default=1.0)
        metric = ClaimCitationSupport(_evaluator(judge))
        response = _response(
            "The reranker runs after hybrid search [1]. Costs rise with corpus size.",
            ["Reranking is applied to the fused set."],
        )

        result = await metric.compute(_question(), response)

        assert result.value == 1.0
        assert result.details["cited_claims"] == 1


# ── uncited_claim_rate ────────────────────────────────────────────────────────


class TestUncitedClaimRate:
    def test_counts_claims_without_markers(self):
        metric = UncitedClaimRate()
        response = _response(
            "The reranker runs after hybrid search [1]. Costs rise with corpus size. "
            "Latency grows with the top-k value.",
            ["ctx"],
        )

        result = metric.compute(_question(), response)

        assert result.value == pytest.approx(2 / 3)

    def test_fully_attributed_answer_scores_zero(self):
        metric = UncitedClaimRate()
        response = _response("The reranker runs after hybrid search [1].", ["ctx"])

        assert metric.compute(_question(), response).value == 0.0

    def test_abstention_is_undefined(self):
        metric = UncitedClaimRate()
        response = _response("I don't have enough information to answer.", ["ctx"])

        assert metric.compute(_question(), response).value is None

    def test_needs_no_judge(self):
        assert UncitedClaimRate().requires_judge is False


# ── The shared evaluator ──────────────────────────────────────────────────────


class TestSharedEvaluator:
    async def test_three_metrics_judge_a_question_once(self):
        # Three metrics × per-claim × per-link calls is a real bill. The evaluator
        # memoizes per question so the second and third metric pay nothing.
        judge = StubJudge()
        evaluator = _evaluator(judge)
        question, response = _question(), _response(
            "The reranker runs after hybrid search [1].",
            ["Reranking is applied to the fused set."],
        )

        await ClaimGroundedness(evaluator).compute(question, response)
        after_first = len(judge.calls)
        await CitationEntailment(evaluator).compute(question, response)
        await ClaimCitationSupport(evaluator).compute(question, response)

        assert after_first == 2  # one context call, one link call
        assert len(judge.calls) == after_first

    async def test_concurrent_metrics_share_one_analysis(self):
        judge = StubJudge()
        evaluator = _evaluator(judge)
        question, response = _question(), _response(
            "The reranker runs after hybrid search [1].",
            ["Reranking is applied to the fused set."],
        )

        await asyncio.gather(
            ClaimGroundedness(evaluator).compute(question, response),
            CitationEntailment(evaluator).compute(question, response),
            ClaimCitationSupport(evaluator).compute(question, response),
        )

        assert len(judge.calls) == 2

    async def test_a_failed_judge_call_drops_the_pair_rather_than_scoring_zero(self):
        class FlakyJudge(StubJudge):
            async def evaluate_entailment(self, claim: str, passage: str) -> JudgeResult:
                if "moon" in claim:
                    raise RuntimeError("judge timed out")
                return await super().evaluate_entailment(claim, passage)

        metric = ClaimGroundedness(_evaluator(FlakyJudge(default=1.0)))
        response = _response(
            "Reranking runs after hybrid search. The index is stored on the moon.",
            ["Reranking is applied to the fused set."],
        )

        result = await metric.compute(_question(), response)

        assert result.value == 1.0  # the surviving claim, not 0.5
        assert result.details["judged_claims"] == 1


# ── Framework wiring ──────────────────────────────────────────────────────────


class TestWiring:
    def test_group_is_registered(self):
        from evals.metrics import METRIC_GROUPS
        from evals.schemas import MetricGroup

        assert MetricGroup.GROUNDEDNESS in METRIC_GROUPS
        assert len(METRIC_GROUPS[MetricGroup.GROUNDEDNESS]) == 4

    def test_off_by_default(self):
        from evals.config import MetricConfig

        # Enabling it multiplies the judge bill; it has to be a decision.
        assert MetricConfig().groundedness is False

    def test_uncited_claim_rate_is_inverted_in_the_weighted_score(self):
        import inspect

        from evals.runner import EvaluationRunner

        source = inspect.getsource(EvaluationRunner._compute_weighted_score)
        assert '"uncited_claim_rate",' in source

    def test_groundedness_objective_defaults_to_zero_weight(self):
        from evals.config import DEFAULT_WEIGHTS

        # Reported, not scored: a non-zero default would silently change every
        # run's headline number relative to runs made before this group existed.
        assert DEFAULT_WEIGHTS["groundedness"] == 0.0


class TestClaimDataclass:
    def test_is_cited(self):
        assert Claim(index=0, text="x", source_indices=(1,)).is_cited
        assert not Claim(index=0, text="x").is_cited
