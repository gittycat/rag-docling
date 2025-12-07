import pytest
from evaluation.data_models import EvaluationSample, RetrievalEvaluationResult, GenerationEvaluationResult, EndToEndEvaluationResult


def test_evaluation_sample_creation():
    sample = EvaluationSample(
        input="What is Python?",
        retrieval_context=["Python is a programming language", "Created by Guido van Rossum"],
        actual_output="Python is a high-level programming language",
        expected_output="Python is a programming language created by Guido van Rossum"
    )

    assert sample.input == "What is Python?"
    assert len(sample.retrieval_context) == 2
    assert sample.actual_output != ""
    assert sample.expected_output is not None


def test_evaluation_sample_to_eval_dict():
    sample = EvaluationSample(
        input="Test question",
        retrieval_context=["context1", "context2"],
        actual_output="test response",
        expected_output="test reference"
    )

    eval_dict = sample.to_eval_dict()

    assert eval_dict["input"] == "Test question"
    assert eval_dict["retrieval_context"] == ["context1", "context2"]
    assert eval_dict["actual_output"] == "test response"
    assert eval_dict["expected_output"] == "test reference"


def test_evaluation_sample_without_reference():
    sample = EvaluationSample(
        input="Test question",
        retrieval_context=["context1"],
    )

    assert sample.expected_output is None
    assert sample.actual_output == ""


def test_retrieval_evaluation_result():
    result = RetrievalEvaluationResult(
        context_precision=0.85,
        context_recall=0.90,
        sample_count=10
    )

    assert result.context_precision == 0.85
    assert result.context_recall == 0.90
    assert result.sample_count == 10


def test_generation_evaluation_result():
    result = GenerationEvaluationResult(
        faithfulness=0.92,
        answer_relevancy=0.88,
        sample_count=10
    )

    assert result.faithfulness == 0.92
    assert result.answer_relevancy == 0.88
    assert result.sample_count == 10


def test_end_to_end_evaluation_result():
    retrieval = RetrievalEvaluationResult(
        context_precision=0.85,
        context_recall=0.90,
        sample_count=10
    )
    generation = GenerationEvaluationResult(
        faithfulness=0.92,
        answer_relevancy=0.88,
        sample_count=10
    )

    result = EndToEndEvaluationResult(
        retrieval=retrieval,
        generation=generation,
        overall_score=0.89,
        sample_count=10
    )

    assert result.retrieval.context_precision == 0.85
    assert result.generation.faithfulness == 0.92
    assert result.overall_score == 0.89
