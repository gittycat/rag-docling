"""Phase-5 judged completeness and contextual-prefix factuality metrics."""

import asyncio

import pytest

from evals.datasets.registry import _dataset_from_dict, _dataset_to_dict, _derive_answer_nuggets
from evals.judges.llm_judge import JudgeResult
from evals.metrics.generation import AnswerCompleteness, ContextualPrefixFactuality
from evals.schemas import EvalDataset, EvalQuestion, EvalResponse, IngestionStage


class StubJudge:
    def __init__(self, scores: dict[tuple[str, str], float] | None = None, default: float = 1.0):
        self.scores = scores or {}
        self.default = default
        self.calls: list[tuple[str, str]] = []

    async def evaluate_entailment(self, claim: str, passage: str) -> JudgeResult:
        self.calls.append((claim, passage))
        score = next(
            (value for (claim_part, passage_part), value in self.scores.items()
             if claim_part in claim and passage_part in passage),
            self.default,
        )
        return JudgeResult(metric_name="entailment", score=score, reasoning="stub verdict")


def _question(nuggets: list[str]) -> EvalQuestion:
    return EvalQuestion(
        id="q1",
        question="What changed?",
        expected_answer="The first change happened. The second change happened.",
        answer_nuggets=nuggets,
    )


class TestAnswerCompleteness:
    def test_truncated_answer_can_be_correct_but_incomplete(self):
        judge = StubJudge({("second change", "first change"): 0.0})
        metric = AnswerCompleteness(judge)
        question = _question(["The first change happened.", "The second change happened."])
        response = EvalResponse(question_id="q1", answer="The first change happened.")

        result = asyncio.run(metric.compute(question, response))

        assert result.value == 0.5
        assert result.details["missing_nuggets"] == ["The second change happened."]
        assert len(result.details["nuggets"]) == 2

    def test_no_nuggets_is_undefined_not_zero(self):
        result = asyncio.run(
            AnswerCompleteness(StubJudge()).compute(_question([]), EvalResponse(question_id="q1", answer="x"))
        )

        assert result.value is None
        assert result.sample_size == 0

    def test_batch_keeps_each_nugget_verdict_for_audit(self):
        metric = AnswerCompleteness(StubJudge())
        question = _question(["One fact.", "Another fact."])
        result = asyncio.run(metric.compute_batch([question], [EvalResponse(question_id="q1", answer="Both.")]))

        assert len(result.details["per_question_details"]["q1"]["nuggets"]) == 2


class TestCachedNuggets:
    def test_missing_nuggets_are_derived_before_serializing_the_dataset_cache(self):
        dataset = EvalDataset(
            name="test",
            version="1",
            questions=[EvalQuestion(id="q1", question="q", expected_answer="One fact. Another fact.")],
        )

        cached = _dataset_from_dict(_dataset_to_dict(_derive_answer_nuggets(dataset)))

        assert cached.questions[0].answer_nuggets == ["One fact.", "Another fact."]


class TestContextualPrefixFactuality:
    def test_prefix_is_judged_against_its_own_source_chunk(self):
        judge = StubJudge({("Incorrect", "source chunk"): 0.0})
        stages = [
            IngestionStage(
                document_id="doc-1",
                name="contextual_enrich",
                duration_ms=1,
                contextual_prefixes=[
                    {"prefix": "Correct prefix.", "source_text": "source chunk supports it"},
                    {"prefix": "Incorrect prefix.", "source_text": "source chunk says something else"},
                ],
            )
        ]

        result = asyncio.run(ContextualPrefixFactuality(judge, stages).compute_batch([], []))

        assert result.value == 0.5
        assert len(result.details["prefixes"]) == 2

    def test_no_persisted_prefixes_is_undefined(self):
        result = asyncio.run(
            ContextualPrefixFactuality(StubJudge(), []).compute_batch([], [])
        )

        assert result.value is None
