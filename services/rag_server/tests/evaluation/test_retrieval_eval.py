import pytest
from evaluation.retrieval_eval import calculate_hit_rate, calculate_mrr
from evaluation.data_models import EvaluationSample


@pytest.fixture
def samples_with_hits():
    return [
        EvaluationSample(
            user_input="What is Python?",
            retrieved_contexts=[
                "Python is a programming language",
                "Python was created by Guido van Rossum",
                "Python is used for web development",
            ],
            reference="Python is a programming language",
        ),
        EvaluationSample(
            user_input="What is Java?",
            retrieved_contexts=[
                "Java is an island",
                "Java is a programming language",
                "Java is object-oriented",
            ],
            reference="Java is a programming language",
        ),
    ]


@pytest.fixture
def samples_with_misses():
    return [
        EvaluationSample(
            user_input="What is Rust?",
            retrieved_contexts=[
                "Rust is a metal oxide",
                "Rust forms when iron oxidizes",
            ],
            reference="Rust is a programming language",
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
            user_input="Test",
            retrieved_contexts=["This is the correct answer", "This is wrong"],
            reference="correct answer",
        )
    ]

    samples_pos2 = [
        EvaluationSample(
            user_input="Test",
            retrieved_contexts=["This is wrong", "This is the correct answer"],
            reference="correct answer",
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
            user_input="Test",
            retrieved_contexts=["context"],
            reference=None,
        )
    ]

    hit_rate = calculate_hit_rate(samples, k=10)
    assert hit_rate == 0.0
