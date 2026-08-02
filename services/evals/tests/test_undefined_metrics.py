"""A metric with nothing to measure reports None, never a flattering constant.

Citation metrics used to return 1.0 without gold passages and retrieval metrics
0.0, so a golden-set run displayed perfect citation scores and a retrieval
regression that never happened.
"""

import pytest

from evals.metrics.abstention import FalseNegativeRate, FalsePositiveRate
from evals.metrics.citation import CitationPrecision, CitationRecall, SectionAccuracy
from evals.metrics.retrieval import MRR, NDCG, PrecisionAtK, RecallAtK
from evals.schemas import (
    Citation,
    EvalQuestion,
    EvalResponse,
    GoldPassage,
    RetrievedChunk,
)


def _question(**kwargs) -> EvalQuestion:
    return EvalQuestion(
        id=kwargs.pop("id", "q1"),
        question=kwargs.pop("question", "What is X?"),
        expected_answer=kwargs.pop("expected_answer", "Y"),
        **kwargs,
    )


def _response(**kwargs) -> EvalResponse:
    return EvalResponse(
        question_id=kwargs.pop("question_id", "q1"),
        answer=kwargs.pop("answer", "Y [1]"),
        **kwargs,
    )


CITATION_METRICS = [CitationPrecision(), CitationRecall(), SectionAccuracy()]
RETRIEVAL_METRICS = [RecallAtK(k=5), PrecisionAtK(k=5), MRR(), NDCG(k=10)]


@pytest.mark.parametrize("metric", CITATION_METRICS, ids=lambda m: m.name)
def test_citation_metrics_undefined_without_gold(metric):
    result = metric.compute(
        _question(gold_passages=[]),
        _response(citations=[Citation(source_index=1, doc_id="d", chunk_id="c")]),
    )
    assert result.value is None
    assert result.sample_size == 0


@pytest.mark.parametrize("metric", RETRIEVAL_METRICS, ids=lambda m: m.name)
def test_retrieval_metrics_undefined_without_gold(metric):
    result = metric.compute(
        _question(gold_passages=[]),
        _response(
            retrieved_chunks=[RetrievedChunk(doc_id="d", chunk_id="c", text="t", rank=1)]
        ),
    )
    assert result.value is None
    assert result.sample_size == 0


def test_abstention_rates_are_undefined_on_inapplicable_questions():
    # An unanswerable question is no evidence about the false-positive rate, and
    # scoring it 0.0 dragged the rate down by however many happened to be present.
    fpr = FalsePositiveRate(abstention_phrases=["i don't know"])
    assert fpr.compute(_question(is_unanswerable=True), _response()).value is None

    fnr = FalseNegativeRate(abstention_phrases=["i don't know"])
    assert fnr.compute(_question(is_unanswerable=False), _response()).value is None


class TestBatchAggregation:
    @pytest.mark.asyncio
    async def test_all_undefined_yields_undefined_not_zero(self):
        metric = CitationRecall()
        questions = [_question(id=f"q{i}", gold_passages=[]) for i in range(3)]
        responses = [_response(question_id=f"q{i}") for i in range(3)]

        result = await metric.compute_batch(questions, responses)

        assert result.value is None
        assert result.sample_size == 0
        assert result.details["not_applicable_count"] == 3

    @pytest.mark.asyncio
    async def test_undefined_samples_are_excluded_from_the_average(self):
        metric = FalsePositiveRate(abstention_phrases=["i don't know"])
        questions = [
            _question(id="answerable-abstained", is_unanswerable=False),
            _question(id="unanswerable", is_unanswerable=True),
        ]
        responses = [
            _response(question_id="answerable-abstained", answer="I don't know"),
            _response(question_id="unanswerable", answer="I don't know"),
        ]

        result = await metric.compute_batch(questions, responses)

        # 1/1 answerable questions falsely abstained. Counting the unanswerable
        # one as 0.0 would report 0.5.
        assert result.value == 1.0
        assert result.sample_size == 1
        assert result.details["not_applicable_count"] == 1

    @pytest.mark.asyncio
    async def test_per_question_scores_are_keyed_by_question_id(self):
        metric = RecallAtK(k=5)
        gold = GoldPassage(doc_id="d1", chunk_id="c1", text="the answer text")
        questions = [
            _question(id="hit", gold_passages=[gold]),
            _question(id="miss", gold_passages=[gold]),
        ]
        responses = [
            _response(
                question_id="hit",
                retrieved_chunks=[
                    RetrievedChunk(doc_id="d1", chunk_id="c1", text="the answer text", rank=1)
                ],
            ),
            _response(
                question_id="miss",
                retrieved_chunks=[
                    RetrievedChunk(doc_id="d9", chunk_id="c9", text="unrelated", rank=1)
                ],
            ),
        ]

        result = await metric.compute_batch(questions, responses)

        assert result.details["per_question"] == {"hit": 1.0, "miss": 0.0}
        assert result.details["std_dev"] == pytest.approx(0.5)


def test_doc_level_gold_is_matched_by_document():
    # `gold_doc_ids` produces text-less gold passages; without doc-level matching
    # they could never be hit and would score a spurious 0.
    question = _question(
        gold_passages=[GoldPassage(doc_id="report.pdf", chunk_id="report.pdf:doc", text="")]
    )
    response = _response(
        citations=[Citation(source_index=1, doc_id="report.pdf", chunk_id="chunk-7")],
        retrieved_chunks=[
            RetrievedChunk(doc_id="report.pdf", chunk_id="chunk-7", text="body", rank=1)
        ],
    )

    assert CitationPrecision().compute(question, response).value == 1.0
    assert CitationRecall().compute(question, response).value == 1.0
