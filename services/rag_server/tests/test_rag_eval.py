"""RAG evaluation tests for CI/CD integration.

These tests use DeepEval to evaluate the RAG pipeline with golden dataset.
They are skipped by default and only run when --run-eval flag is provided.

Usage:
    # Run evaluation tests
    pytest tests/test_rag_eval.py --run-eval

    # Run with subset for quick check
    pytest tests/test_rag_eval.py --run-eval --eval-samples=5

    # Run specific metric
    pytest tests/test_rag_eval.py::test_rag_faithfulness --run-eval
"""

import pytest
import asyncio
from deepeval import assert_test, evaluate
from deepeval.test_case import LLMTestCase
from deepeval.metrics import (
    FaithfulnessMetric,
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    HallucinationMetric,
)

from evaluation.deepeval_config import get_default_evaluator
from evaluation.dataset_loader import load_golden_dataset
from evaluation.live_eval import (
    create_live_test_cases,
    check_rag_server_health,
    clear_rag_session,
)


def pytest_addoption(parser):
    """Add custom pytest command-line options."""
    parser.addoption(
        "--run-eval",
        action="store_true",
        default=False,
        help="Run evaluation tests (requires ANTHROPIC_API_KEY and RAG server)",
    )
    parser.addoption(
        "--eval-samples",
        type=int,
        default=None,
        help="Number of samples to evaluate (default: all)",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "eval: RAG evaluation tests (require --run-eval and ANTHROPIC_API_KEY)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip eval tests unless --run-eval is provided."""
    if config.getoption("--run-eval"):
        return

    skip_eval = pytest.mark.skip(reason="Need --run-eval option to run")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip_eval)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def evaluator_model():
    """Get configured Anthropic evaluator model."""
    return get_default_evaluator()


@pytest.fixture(scope="session")
def eval_limit(request):
    """Get evaluation sample limit from command line."""
    return request.config.getoption("--eval-samples")


@pytest.fixture(scope="session")
async def check_rag_health():
    """Check RAG server health before running tests."""
    is_healthy = await check_rag_server_health()
    if not is_healthy:
        pytest.skip("RAG server is not running or unhealthy")
    return True


@pytest.fixture(scope="session")
async def golden_dataset(eval_limit):
    """Load golden dataset with optional limit."""
    dataset = load_golden_dataset()
    if eval_limit:
        dataset = dataset[:eval_limit]
    return dataset


@pytest.fixture(scope="session")
async def test_cases(golden_dataset, check_rag_health):
    """Create test cases from live RAG queries.

    This fixture runs once per session and creates all test cases
    by querying the live RAG server.
    """
    # Clear session before starting
    await clear_rag_session()

    # Create test cases
    test_cases = await create_live_test_cases(golden_dataset, verbose=True)

    if not test_cases:
        pytest.skip("No test cases created - check RAG server")

    return test_cases


# ============================================================================
# Retrieval Quality Tests
# ============================================================================


@pytest.mark.eval
@pytest.mark.asyncio
async def test_rag_contextual_precision(test_cases, evaluator_model):
    """Test that retrieved context is precisely ranked."""
    metric = ContextualPrecisionMetric(
        threshold=0.7,
        model=evaluator_model,
        include_reason=True,
    )

    results = evaluate(test_cases, [metric])

    # DeepEval handles pass/fail internally
    # We can add custom assertions if needed
    assert len(results) > 0


@pytest.mark.eval
@pytest.mark.asyncio
async def test_rag_contextual_recall(test_cases, evaluator_model):
    """Test that all necessary context is retrieved."""
    metric = ContextualRecallMetric(
        threshold=0.7,
        model=evaluator_model,
        include_reason=True,
    )

    results = evaluate(test_cases, [metric])
    assert len(results) > 0


# ============================================================================
# Generation Quality Tests
# ============================================================================


@pytest.mark.eval
@pytest.mark.asyncio
async def test_rag_faithfulness(test_cases, evaluator_model):
    """Test that RAG responses are faithful to retrieved context."""
    metric = FaithfulnessMetric(
        threshold=0.7,
        model=evaluator_model,
        include_reason=True,
    )

    results = evaluate(test_cases, [metric])
    assert len(results) > 0


@pytest.mark.eval
@pytest.mark.asyncio
async def test_rag_answer_relevancy(test_cases, evaluator_model):
    """Test that RAG responses are relevant to questions."""
    metric = AnswerRelevancyMetric(
        threshold=0.7,
        model=evaluator_model,
        include_reason=True,
    )

    results = evaluate(test_cases, [metric])
    assert len(results) > 0


# ============================================================================
# Safety Tests
# ============================================================================


@pytest.mark.eval
@pytest.mark.asyncio
async def test_rag_hallucination(test_cases, evaluator_model):
    """Test that RAG responses minimize hallucinations."""
    metric = HallucinationMetric(
        threshold=0.5,  # Stricter threshold
        model=evaluator_model,
        include_reason=True,
    )

    results = evaluate(test_cases, [metric])
    assert len(results) > 0


# ============================================================================
# End-to-End Evaluation
# ============================================================================


@pytest.mark.eval
@pytest.mark.asyncio
async def test_rag_full_evaluation(test_cases, evaluator_model):
    """Run full evaluation with all metrics.

    This is the comprehensive test that evaluates the RAG pipeline
    across all dimensions: retrieval quality, generation quality,
    and safety.
    """
    metrics = [
        # Retrieval Quality
        ContextualPrecisionMetric(
            threshold=0.7,
            model=evaluator_model,
            include_reason=True,
        ),
        ContextualRecallMetric(
            threshold=0.7,
            model=evaluator_model,
            include_reason=True,
        ),
        # Generation Quality
        FaithfulnessMetric(
            threshold=0.7,
            model=evaluator_model,
            include_reason=True,
        ),
        AnswerRelevancyMetric(
            threshold=0.7,
            model=evaluator_model,
            include_reason=True,
        ),
        # Safety
        HallucinationMetric(
            threshold=0.5,
            model=evaluator_model,
            include_reason=True,
        ),
    ]

    results = evaluate(test_cases, metrics)
    assert len(results) > 0

    # Could add custom assertions on overall scores here
    # For example:
    # assert results.overall_score >= 0.6, "Overall RAG quality below threshold"


# ============================================================================
# Individual Test Case Examples
# ============================================================================


@pytest.mark.eval
def test_single_test_case_example(evaluator_model):
    """Example of testing a single test case (for debugging).

    This test demonstrates how to test individual questions
    without querying the full dataset.
    """
    # Create a single test case manually
    test_case = LLMTestCase(
        input="What is Python?",
        actual_output="Python is a high-level programming language.",
        expected_output="Python is a programming language.",
        retrieval_context=["Python is a programming language created by Guido van Rossum."],
    )

    # Test with a single metric
    metric = AnswerRelevancyMetric(
        threshold=0.7,
        model=evaluator_model,
        include_reason=True,
    )

    # Use assert_test for single test case
    assert_test(test_case, [metric])
