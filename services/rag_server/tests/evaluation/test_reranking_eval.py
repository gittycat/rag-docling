import pytest
from evaluation.reranking_eval import RerankingEvaluator
from evaluation.data_models import EvaluationSample


@pytest.fixture
def reranking_evaluator():
    return RerankingEvaluator()


@pytest.fixture
def samples_before_rerank():
    return [
        EvaluationSample(
            user_input="What is Python?",
            retrieved_contexts=[
                "Python is a snake",
                "Python is a programming language",
                "Python was created by Guido van Rossum",
            ],
            reference="Python is a programming language",
        ),
        EvaluationSample(
            user_input="What is Java?",
            retrieved_contexts=[
                "Java is an island",
                "Java is a coffee",
                "Java is a programming language",
            ],
            reference="Java is a programming language",
        ),
    ]


@pytest.fixture
def samples_after_rerank():
    return [
        EvaluationSample(
            user_input="What is Python?",
            retrieved_contexts=[
                "Python is a programming language",
                "Python was created by Guido van Rossum",
                "Python is a snake",
            ],
            reference="Python is a programming language",
        ),
        EvaluationSample(
            user_input="What is Java?",
            retrieved_contexts=[
                "Java is a programming language",
                "Java is a coffee",
                "Java is an island",
            ],
            reference="Java is a programming language",
        ),
    ]


def test_calculate_precision_at_1(reranking_evaluator, samples_before_rerank):
    precision = reranking_evaluator.calculate_precision_at_k(
        samples_before_rerank, k=1
    )

    assert 0.0 <= precision <= 1.0


def test_calculate_precision_at_3(reranking_evaluator, samples_after_rerank):
    precision = reranking_evaluator.calculate_precision_at_k(
        samples_after_rerank, k=3
    )

    assert 0.0 <= precision <= 1.0
    assert precision > 0.0


def test_calculate_ndcg(reranking_evaluator, samples_after_rerank):
    ndcg = reranking_evaluator.calculate_ndcg(samples_after_rerank, k=3)

    assert 0.0 <= ndcg <= 1.0


def test_compare_reranking(
    reranking_evaluator, samples_before_rerank, samples_after_rerank
):
    comparison = reranking_evaluator.compare_reranking(
        samples_before_rerank, samples_after_rerank
    )

    assert comparison.sample_count == 2
    assert 0.0 <= comparison.before_precision_at_1 <= 1.0
    assert 0.0 <= comparison.after_precision_at_1 <= 1.0
    assert comparison.after_precision_at_1 > comparison.before_precision_at_1


def test_compare_reranking_mismatched_lengths(
    reranking_evaluator, samples_before_rerank
):
    samples_after = samples_before_rerank[:1]

    with pytest.raises(ValueError, match="same length"):
        reranking_evaluator.compare_reranking(samples_before_rerank, samples_after)


def test_precision_empty_samples(reranking_evaluator):
    precision = reranking_evaluator.calculate_precision_at_k([], k=1)
    assert precision == 0.0


def test_ndcg_empty_samples(reranking_evaluator):
    ndcg = reranking_evaluator.calculate_ndcg([], k=10)
    assert ndcg == 0.0
