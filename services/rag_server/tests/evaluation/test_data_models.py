import pytest
from evaluation.data_models import EvaluationSample, RetrievalEvaluationResult, GenerationEvaluationResult, EndToEndEvaluationResult


def test_evaluation_sample_creation():
    sample = EvaluationSample(
        user_input="What is Python?",
        retrieved_contexts=["Python is a programming language", "Created by Guido van Rossum"],
        response="Python is a high-level programming language",
        reference="Python is a programming language created by Guido van Rossum"
    )

    assert sample.user_input == "What is Python?"
    assert len(sample.retrieved_contexts) == 2
    assert sample.response != ""
    assert sample.reference is not None


def test_evaluation_sample_to_ragas_dict():
    sample = EvaluationSample(
        user_input="Test question",
        retrieved_contexts=["context1", "context2"],
        response="test response",
        reference="test reference"
    )

    ragas_dict = sample.to_ragas_dict()

    assert ragas_dict["user_input"] == "Test question"
    assert ragas_dict["retrieved_contexts"] == ["context1", "context2"]
    assert ragas_dict["response"] == "test response"
    assert ragas_dict["reference"] == "test reference"


def test_evaluation_sample_without_reference():
    sample = EvaluationSample(
        user_input="Test question",
        retrieved_contexts=["context1"],
    )

    assert sample.reference is None
    assert sample.response == ""


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
