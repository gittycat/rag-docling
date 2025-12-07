import pytest
from evaluation.reranking_eval import calculate_hit_rate, calculate_mrr
from evaluation.data_models import EvaluationSample


@pytest.fixture
def samples_with_hits():
    return [
        EvaluationSample(
            input="What is Python?",
            retrieval_context=[
                "Python is a programming language",
                "Python was created by Guido van Rossum",
                "Python is used for web development",
            ],
            expected_output="Python is a programming language",
        ),
        EvaluationSample(
            input="What is Java?",
            retrieval_context=[
                "Java is an island",
                "Java is a programming language",
                "Java is object-oriented",
            ],
            expected_output="Java is a programming language",
        ),
    ]


@pytest.fixture
def samples_with_misses():
    return [
        EvaluationSample(
            input="What is Rust?",
            retrieval_context=[
                "Rust is a metal oxide",
                "Rust forms when iron oxidizes",
            ],
            expected_output="Rust is a programming language",
        ),
    ]


def test_calculate_hit_rate_with_hits(samples_with_hits):
    hit_rate = calculate_hit_rate(samples_with_hits, k=10)

    assert 0.0 <= hit_rate <= 1.0
    assert hit_rate > 0.5


def test_calculate_hit_rate_with_misses(samples_with_misses):
    hit_rate = calculate_hit_rate(samples_with_misses, k=10)

    assert hit_rate == 0.0


def test_calculate_hit_rate_k_limit(samples_with_hits):
    hit_rate_k3 = calculate_hit_rate(samples_with_hits, k=3)
    hit_rate_k1 = calculate_hit_rate(samples_with_hits, k=1)

    assert hit_rate_k3 >= hit_rate_k1


def test_calculate_hit_rate_empty_samples():
    hit_rate = calculate_hit_rate([], k=10)
    assert hit_rate == 0.0


def test_calculate_mrr_with_hits(samples_with_hits):
    mrr = calculate_mrr(samples_with_hits)

    assert 0.0 <= mrr <= 1.0
    assert mrr > 0.0


def test_calculate_mrr_with_misses(samples_with_misses):
    mrr = calculate_mrr(samples_with_misses)

    assert mrr == 0.0


def test_calculate_mrr_position_matters():
    samples_pos1 = [
        EvaluationSample(
            input="Test",
            retrieval_context=["This is the correct answer", "This is wrong"],
            expected_output="correct answer",
        )
    ]

    samples_pos2 = [
        EvaluationSample(
            input="Test",
            retrieval_context=["This is wrong", "This is the correct answer"],
            expected_output="correct answer",
        )
    ]

    mrr_pos1 = calculate_mrr(samples_pos1)
    mrr_pos2 = calculate_mrr(samples_pos2)

    assert mrr_pos1 > mrr_pos2
    assert mrr_pos1 == 1.0
    assert mrr_pos2 == 0.5


def test_calculate_mrr_empty_samples():
    mrr = calculate_mrr([])
    assert mrr == 0.0


def test_calculate_hit_rate_no_reference():
    samples = [
        EvaluationSample(
            input="Test",
            retrieval_context=["context"],
            expected_output=None,
        )
    ]

    hit_rate = calculate_hit_rate(samples, k=10)
    assert hit_rate == 0.0
