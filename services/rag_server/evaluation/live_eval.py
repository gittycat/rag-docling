"""Live RAG pipeline evaluation using DeepEval.

This module evaluates the actual RAG pipeline by sending queries
to the running RAG server and evaluating responses with DeepEval metrics.
Includes latency and cost tracking for comprehensive analysis.
"""

import asyncio
import os
import time
from typing import List, Optional
from pathlib import Path

import httpx
from deepeval.test_case import LLMTestCase
from deepeval import evaluate
from deepeval.models import AnthropicModel

from evaluation.metrics import get_rag_metrics
from evaluation.dataset_loader import load_golden_dataset, GoldenQA
from evaluation.test_cases import create_test_case
from services.latency_tracker import LatencyTracker
from services.cost_tracker import CostTracker
from schemas.metrics import ConfigSnapshot


# RAG Server Configuration
RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://localhost:8001")
EVAL_SESSION_ID = "deepeval-session"


def get_current_config_snapshot() -> Optional[ConfigSnapshot]:
    """Get a snapshot of the current RAG configuration.

    Returns:
        ConfigSnapshot of current settings, or None if config unavailable
    """
    try:
        from infrastructure.config.models_config import get_models_config
        from pipelines.inference import get_inference_config
        from pipelines.ingestion import get_ingestion_config

        models_config = get_models_config()
        inference_config = get_inference_config()
        ingestion_config = get_ingestion_config()

        return ConfigSnapshot(
            llm_provider=models_config.llm.provider,
            llm_model=models_config.llm.model,
            llm_base_url=models_config.llm.base_url,
            embedding_provider=models_config.embedding.provider,
            embedding_model=models_config.embedding.model,
            retrieval_top_k=inference_config["retrieval_top_k"],
            hybrid_search_enabled=inference_config["hybrid_search_enabled"],
            rrf_k=inference_config["rrf_k"],
            contextual_retrieval_enabled=ingestion_config["contextual_retrieval_enabled"],
            reranker_enabled=inference_config["reranker_enabled"],
            reranker_model=inference_config["reranker_model"],
            reranker_top_n=inference_config.get("reranker_top_n", 5),
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to get config snapshot: {e}")
        return None


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
    latency_tracker: Optional[LatencyTracker] = None,
    cost_tracker: Optional[CostTracker] = None,
) -> List[LLMTestCase]:
    """Generate test cases from live RAG queries.

    Args:
        golden_dataset: List of golden Q&A pairs
        session_id: Session ID for RAG queries
        verbose: Print progress messages
        latency_tracker: Optional tracker for query latencies
        cost_tracker: Optional tracker for token usage

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
            # Track latency
            start_time = time.perf_counter()

            # Query RAG
            result = await query_rag(qa.question, session_id=session_id)

            # Record latency
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if latency_tracker:
                latency_tracker.record(elapsed_ms)

            # Track cost (if token counts are available in response)
            if cost_tracker:
                input_tokens = result.get("input_tokens", 0)
                output_tokens = result.get("output_tokens", 0)
                # Estimate if not provided (rough estimate based on text length)
                if not input_tokens:
                    input_tokens = len(qa.question.split()) * 2  # ~2 tokens per word
                if not output_tokens:
                    output_tokens = len(result.get("answer", "").split()) * 2
                cost_tracker.track_query(input_tokens, output_tokens)

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
                print(f"  ✓ Got response with {len(retrieval_context)} sources ({elapsed_ms:.0f}ms)")

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
    track_performance: bool = True,
) -> dict:
    """Run evaluation against live RAG server.

    Args:
        dataset: Golden dataset (defaults to load_golden_dataset())
        model: Anthropic model for evaluation (defaults to configured model)
        include_reason: Include explanation for scores
        verbose: Print progress messages
        limit: Limit number of test cases (for quick testing)
        track_performance: Track latency and cost metrics

    Returns:
        Evaluation results dictionary with optional performance metrics:
            {
                "results": DeepEval results,
                "config_snapshot": ConfigSnapshot (if available),
                "latency_metrics": LatencyMetrics (if track_performance),
                "cost_metrics": CostMetrics (if track_performance),
            }

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

    # Get config snapshot
    config_snapshot = get_current_config_snapshot()
    if verbose and config_snapshot:
        print(f"   LLM Model: {config_snapshot.llm_model}")
        print(f"   Hybrid Search: {'enabled' if config_snapshot.hybrid_search_enabled else 'disabled'}")

    # Initialize trackers
    latency_tracker = LatencyTracker() if track_performance else None
    cost_tracker = CostTracker() if track_performance else None

    # Clear session before starting
    await clear_rag_session()

    # Create test cases from live queries
    test_cases = await create_live_test_cases(
        dataset,
        session_id=EVAL_SESSION_ID,
        verbose=verbose,
        latency_tracker=latency_tracker,
        cost_tracker=cost_tracker,
    )

    if not test_cases:
        raise ValueError("No test cases were created. Check RAG server connectivity.")

    if verbose:
        print(f"\n📊 Running DeepEval metrics on {len(test_cases)} test cases...")

    # Get metrics
    metrics = get_rag_metrics(model=model, include_reason=include_reason)

    # Run evaluation
    eval_results = evaluate(test_cases, metrics)

    if verbose:
        print("\n✅ Evaluation complete!")

        # Print performance summary
        if latency_tracker and latency_tracker.count > 0:
            latency_metrics = latency_tracker.get_metrics()
            print(f"\n⏱️  Latency: avg={latency_metrics.avg_query_time_ms:.0f}ms, "
                  f"P50={latency_metrics.p50_query_time_ms:.0f}ms, "
                  f"P95={latency_metrics.p95_query_time_ms:.0f}ms")

        if cost_tracker and cost_tracker.query_count > 0 and config_snapshot:
            cost_metrics = cost_tracker.get_metrics(config_snapshot.llm_model)
            print(f"💰 Cost: ${cost_metrics.estimated_cost_usd:.4f} total, "
                  f"${cost_metrics.cost_per_query_usd:.4f}/query")

    # Build result with performance metrics
    result = {
        "results": eval_results,
        "config_snapshot": config_snapshot,
    }

    if track_performance:
        if latency_tracker:
            result["latency_metrics"] = latency_tracker.get_metrics()
        if cost_tracker and config_snapshot:
            result["cost_metrics"] = cost_tracker.get_metrics(config_snapshot.llm_model)

    return result


def run_live_evaluation_sync(
    dataset: Optional[List[GoldenQA]] = None,
    model: Optional[AnthropicModel] = None,
    include_reason: bool = True,
    verbose: bool = True,
    limit: Optional[int] = None,
    track_performance: bool = True,
) -> dict:
    """Synchronous wrapper for run_live_evaluation.

    Args:
        dataset: Golden dataset
        model: Anthropic model for evaluation
        include_reason: Include explanation for scores
        verbose: Print progress messages
        limit: Limit number of test cases
        track_performance: Track latency and cost metrics

    Returns:
        Evaluation results dictionary with optional performance metrics

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
            track_performance=track_performance,
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
