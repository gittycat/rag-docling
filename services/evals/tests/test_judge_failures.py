"""A failed judge call must be excluded from the average, never scored 0.0.

Scoring a timeout or a malformed response as 0.0 is indistinguishable from a
genuine "completely unfaithful" verdict: transient judge flakiness would silently
depress every reported score and corrupt calibration against the TRACe labels.
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.config import JudgeConfig
from evals.judges.llm_judge import JudgeError, JudgeParseError, LLMJudge, JudgeResult
from evals.metrics.generation import AnswerRelevancy
from evals.schemas import EvalQuestion, EvalResponse


class _StubCompletion:
    def __init__(self, text: str):
        self._text = text

    def __str__(self) -> str:
        return self._text


class _StubLLM:
    """Returns each queued response in turn; an Exception instance is raised."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    async def acomplete(self, prompt: str):
        self.calls += 1
        item = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return _StubCompletion(item)


def _judge(*responses, max_retries=3) -> LLMJudge:
    judge = LLMJudge(JudgeConfig(model="stub", max_retries=max_retries))
    judge._llm = _StubLLM(*responses)
    return judge


class TestParseResponse:
    def test_parses_score_and_reasoning(self):
        score, reasoning = _judge()._parse_response("SCORE: 0.8\nREASONING: grounded")
        assert score == 0.8
        assert reasoning == "grounded"

    @pytest.mark.parametrize(
        "raw,expected",
        [("SCORE: 0.8/1", 0.8), ("SCORE: 80%", 0.8), ("SCORE: 1.5", 1.0), ("SCORE: -2", 0.0)],
    )
    def test_score_formats_and_clamping(self, raw, expected):
        score, _ = _judge()._parse_response(raw)
        assert score == expected

    def test_missing_score_line_raises(self):
        with pytest.raises(JudgeParseError):
            _judge()._parse_response("I think the answer looks fine, honestly.")

    def test_unparseable_score_raises(self):
        with pytest.raises(JudgeParseError):
            _judge()._parse_response("SCORE: high\nREASONING: vibes")

    def test_empty_response_raises(self):
        with pytest.raises(JudgeParseError):
            _judge()._parse_response("")

    def test_zero_is_still_a_valid_score(self):
        score, _ = _judge()._parse_response("SCORE: 0.0\nREASONING: contradicts context")
        assert score == 0.0


class TestEvaluateRetries:
    def test_malformed_response_triggers_retry(self):
        # The whole point: a malformed response used to return 0.0 without retrying.
        judge = _judge("no score here", "SCORE: 0.7\nREASONING: ok")
        result = asyncio.run(judge.evaluate_relevancy(answer="a", question="q"))

        assert result.score == 0.7
        assert judge._llm.calls == 2

    def test_raises_after_retries_exhausted(self):
        judge = _judge("still no score", max_retries=3)

        with pytest.raises(JudgeError):
            asyncio.run(judge.evaluate_relevancy(answer="a", question="q"))
        assert judge._llm.calls == 3

    def test_transport_error_raises_not_zero(self):
        judge = _judge(TimeoutError("judge timed out"), max_retries=2)

        with pytest.raises(JudgeError):
            asyncio.run(judge.evaluate_faithfulness(answer="a", context="c"))
        assert judge._llm.calls == 2


class TestBatchExclusion:
    """A failing sample must shrink sample_size, not pull the average toward 0."""

    def _batch(self, scores):
        class _Judge:
            def __init__(self):
                self.remaining = list(scores)

            async def evaluate_relevancy(self, answer, question):
                value = self.remaining.pop(0)
                if value is None:
                    raise JudgeError("judge unavailable")
                return JudgeResult(metric_name="relevancy", score=value)

        metric = AnswerRelevancy(judge=_Judge())
        questions = [
            EvalQuestion(id=str(i), question="q", expected_answer=None)
            for i in range(len(scores))
        ]
        responses = [EvalResponse(question_id=str(i), answer="a") for i in range(len(scores))]
        return asyncio.run(metric.compute_batch(questions, responses, concurrency=1))

    def test_failed_sample_excluded_from_average(self):
        result = self._batch([1.0, None, 1.0])

        assert result.value == 1.0  # not 0.667
        assert result.sample_size == 2

    def test_all_failed_reports_zero_samples(self):
        result = self._batch([None, None])

        assert result.sample_size == 0
        assert result.details["error"] == "All computations failed"
