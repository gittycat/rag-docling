"""Live RAG pipeline evaluation using DeepEval.

This module evaluates the actual RAG pipeline by sending queries
to the running RAG server and evaluating responses with DeepEval metrics.
"""

import asyncio
import os
from typing import List, Optional
from pathlib import Path

import httpx
from deepeval.test_case import LLMTestCase
from deepeval import evaluate
from deepeval.models import AnthropicModel

from evaluation.metrics import get_rag_metrics
from evaluation.dataset_loader import load_golden_dataset, GoldenQA
from evaluation.test_cases import create_test_case


# RAG Server Configuration
RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:8001")
EVAL_SESSION_ID = "deepeval-session"


async def query_rag(
    question: str,
    session_id: str = EVAL_SESSION_ID,
    timeout: float = 30.0,
) -> dict:
    """Query the actual RAG server.

    Args:
        question: User question
        session_id: Session ID for conversation tracking
        timeout: Request timeout in seconds

    Returns:
        RAG response dictionary with structure:
            {
                "answer": "...",
                "sources": [{"excerpt": "...", ...}, ...],
                "query": "...",
                "session_id": "..."
            }

    Raises:
        httpx.HTTPError: If request fails
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{RAG_SERVER_URL}/query",
            json={"query": question, "session_id": session_id},
        )
        response.raise_for_status()
        return response.json()


async def create_live_test_cases(
    golden_dataset: List[GoldenQA],
    session_id: str = EVAL_SESSION_ID,
    verbose: bool = False,
) -> List[LLMTestCase]:
    """Generate test cases from live RAG queries.

    Args:
        golden_dataset: List of golden Q&A pairs
        session_id: Session ID for RAG queries
        verbose: Print progress messages

    Returns:
        List of LLMTestCase objects with actual RAG responses

    Example:
        >>> dataset = load_golden_dataset()
        >>> test_cases = await create_live_test_cases(dataset[:5])
        >>> print(f"Created {len(test_cases)} test cases")
    """
    test_cases = []

    for i, qa in enumerate(golden_dataset, 1):
        if verbose:
            print(f"[{i}/{len(golden_dataset)}] Querying: {qa.question[:50]}...")

        try:
            # Query RAG
            result = await query_rag(qa.question, session_id=session_id)

            # Extract source excerpts for retrieval context
            retrieval_context = [
                source.get("excerpt", source.get("full_text", ""))
                for source in result.get("sources", [])
            ]

            # Create test case
            test_case = create_test_case(
                question=qa.question,
                actual_output=result["answer"],
                expected_output=qa.answer,
                retrieval_context=retrieval_context,
                name=qa.id,
                tags=qa.tags,
            )

            test_cases.append(test_case)

            if verbose:
                print(f"  ✓ Got response with {len(retrieval_context)} sources")

        except Exception as e:
            if verbose:
                print(f"  ✗ Error: {e}")
            # Continue with other test cases

    return test_cases


async def clear_rag_session(session_id: str = EVAL_SESSION_ID) -> None:
    """Clear RAG chat history for the evaluation session.

    Args:
        session_id: Session ID to clear
    """
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{RAG_SERVER_URL}/chat/clear",
                json={"session_id": session_id},
            )
        except Exception:
            # Ignore errors (session might not exist)
            pass


async def run_live_evaluation(
    dataset: Optional[List[GoldenQA]] = None,
    model: Optional[AnthropicModel] = None,
    include_reason: bool = True,
    verbose: bool = True,
    limit: Optional[int] = None,
) -> dict:
    """Run evaluation against live RAG server.

    Args:
        dataset: Golden dataset (defaults to load_golden_dataset())
        model: Anthropic model for evaluation (defaults to configured model)
        include_reason: Include explanation for scores
        verbose: Print progress messages
        limit: Limit number of test cases (for quick testing)

    Returns:
        Evaluation results dictionary

    Example:
        >>> results = await run_live_evaluation(limit=5, verbose=True)
        >>> print(f"Overall score: {results['overall_score']}")
    """
    # Load dataset if not provided
    if dataset is None:
        dataset = load_golden_dataset()

    if limit:
        dataset = dataset[:limit]

    if verbose:
        print(f"🔍 Evaluating RAG with {len(dataset)} test cases...")
        print(f"   RAG Server: {RAG_SERVER_URL}")

    # Clear session before starting
    await clear_rag_session()

    # Create test cases from live queries
    test_cases = await create_live_test_cases(
        dataset, session_id=EVAL_SESSION_ID, verbose=verbose
    )

    if not test_cases:
        raise ValueError("No test cases were created. Check RAG server connectivity.")

    if verbose:
        print(f"\n📊 Running DeepEval metrics on {len(test_cases)} test cases...")

    # Get metrics
    metrics = get_rag_metrics(model=model, include_reason=include_reason)

    # Run evaluation
    results = evaluate(test_cases, metrics)

    if verbose:
        print("\n✅ Evaluation complete!")

    return results


def run_live_evaluation_sync(
    dataset: Optional[List[GoldenQA]] = None,
    model: Optional[AnthropicModel] = None,
    include_reason: bool = True,
    verbose: bool = True,
    limit: Optional[int] = None,
) -> dict:
    """Synchronous wrapper for run_live_evaluation.

    Args:
        dataset: Golden dataset
        model: Anthropic model for evaluation
        include_reason: Include explanation for scores
        verbose: Print progress messages
        limit: Limit number of test cases

    Returns:
        Evaluation results dictionary

    Example:
        >>> results = run_live_evaluation_sync(limit=5)
        >>> print(f"Overall score: {results['overall_score']}")
    """
    return asyncio.run(
        run_live_evaluation(
            dataset=dataset,
            model=model,
            include_reason=include_reason,
            verbose=verbose,
            limit=limit,
        )
    )


async def check_rag_server_health() -> bool:
    """Check if RAG server is running and healthy.

    Returns:
        True if server is healthy, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{RAG_SERVER_URL}/health")
            return response.status_code == 200
    except Exception:
        return False


def main():
    """CLI for running live evaluation."""
    import argparse

    # Declare global at the top
    global RAG_SERVER_URL

    parser = argparse.ArgumentParser(description="Run live RAG evaluation")
    parser.add_argument(
        "--limit", "-n", type=int, help="Limit number of test cases (for quick testing)"
    )
    parser.add_argument(
        "--no-reason", action="store_true", help="Skip metric explanations (faster)"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Minimal output"
    )
    parser.add_argument(
        "--server-url",
        default=RAG_SERVER_URL,
        help=f"RAG server URL (default: {RAG_SERVER_URL})",
    )
    args = parser.parse_args()

    # Update server URL
    RAG_SERVER_URL = args.server_url

    # Check server health
    print(f"Checking RAG server at {RAG_SERVER_URL}...")
    is_healthy = asyncio.run(check_rag_server_health())

    if not is_healthy:
        print(f"❌ RAG server is not responding at {RAG_SERVER_URL}")
        print("   Make sure the server is running: docker compose up -d")
        return

    print("✅ RAG server is healthy\n")

    # Run evaluation
    results = run_live_evaluation_sync(
        include_reason=not args.no_reason,
        verbose=not args.quiet,
        limit=args.limit,
    )

    # Print summary
    if not args.quiet:
        print("\n" + "=" * 60)
        print("EVALUATION SUMMARY")
        print("=" * 60)
        # DeepEval will have printed detailed results
        # We can add custom summary here if needed


if __name__ == "__main__":
    main()
