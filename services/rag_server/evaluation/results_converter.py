"""Convert DeepEval results to metrics API format.

Converts DeepEval evaluation results to the EvaluationRun format
used by the metrics API for historical tracking and comparison.
"""

import os
import uuid
from datetime import datetime
from typing import Any, Optional

from schemas.metrics import (
    EvaluationRun,
    MetricResult,
    TestCaseResult,
)
from services.metrics import (
    get_retrieval_config,
    save_evaluation_run,
)


def convert_deepeval_results(
    results: Any,
    eval_model: str = "claude-sonnet-4-20250514",
    notes: Optional[str] = None,
    save: bool = True,
) -> EvaluationRun:
    """Convert DeepEval results to EvaluationRun format.

    Args:
        results: DeepEval evaluation results dict from run_live_evaluation
                 Expected structure: {"results": DeepEvalResults, "config_snapshot": ..., ...}
        eval_model: Model used for evaluation
        notes: Optional notes about this run

    Returns:
        EvaluationRun object with converted results
    """
    run_id = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow()

    # Handle dict wrapper from run_live_evaluation
    deepeval_results = results.get("results") if isinstance(results, dict) else results
    config_snapshot = results.get("config_snapshot") if isinstance(results, dict) else None
    latency_metrics = results.get("latency_metrics") if isinstance(results, dict) else None
    cost_metrics = results.get("cost_metrics") if isinstance(results, dict) else None

    # Get test results
    test_results = getattr(deepeval_results, "test_results", [])
    total_tests = len(test_results)
    passed_tests = sum(1 for tr in test_results if getattr(tr, "success", False))
    pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

    # Calculate per-metric averages and pass rates
    metric_scores: dict[str, list[float]] = {}
    metric_passes: dict[str, list[bool]] = {}

    # Convert test cases
    test_cases = []

    for tr in test_results:
        # Get test case info
        test_case = getattr(tr, "input", None)
        test_name = getattr(tr, "name", None) or (
            getattr(test_case, "name", None) if test_case else None
        ) or "unknown"

        question = ""
        expected_answer = None
        actual_answer = ""
        retrieval_context_count = 0

        if test_case:
            question = getattr(test_case, "input", "")
            expected_answer = getattr(test_case, "expected_output", None)
            actual_answer = getattr(test_case, "actual_output", "")
            retrieval_context = getattr(test_case, "retrieval_context", [])
            retrieval_context_count = len(retrieval_context) if retrieval_context else 0

        # Get metrics for this test case
        metrics_data = getattr(tr, "metrics_data", [])
        metric_results = []

        for md in metrics_data:
            metric_name = getattr(md, "name", "unknown")
            # Normalize metric name
            normalized_name = metric_name.lower().replace(" ", "_")

            score = getattr(md, "score", 0.0)
            threshold = getattr(md, "threshold", 0.7)
            passed = getattr(md, "success", False)
            reason = getattr(md, "reason", None)

            metric_results.append(MetricResult(
                metric_name=normalized_name,
                score=score if score is not None else 0.0,
                passed=passed,
                threshold=threshold,
                reason=reason,
            ))

            # Accumulate for averages
            if normalized_name not in metric_scores:
                metric_scores[normalized_name] = []
                metric_passes[normalized_name] = []

            if score is not None:
                metric_scores[normalized_name].append(score)
                metric_passes[normalized_name].append(passed)

        test_cases.append(TestCaseResult(
            test_id=test_name,
            question=question,
            expected_answer=expected_answer,
            actual_answer=actual_answer,
            metrics=metric_results,
            passed=getattr(tr, "success", False),
            retrieval_context_count=retrieval_context_count,
        ))

    # Calculate averages
    metric_averages = {}
    metric_pass_rates = {}

    for metric_name, scores in metric_scores.items():
        if scores:
            metric_averages[metric_name] = sum(scores) / len(scores)
            passes = metric_passes.get(metric_name, [])
            metric_pass_rates[metric_name] = sum(passes) / len(passes) * 100 if passes else 0

    # Get current retrieval config
    retrieval_config = None
    try:
        config = get_retrieval_config()
        retrieval_config = {
            "retrieval_top_k": config.retrieval_top_k,
            "final_top_n": config.final_top_n,
            "hybrid_search_enabled": config.hybrid_search.enabled,
            "rrf_k": config.hybrid_search.rrf_k,
            "contextual_retrieval_enabled": config.contextual_retrieval.enabled,
            "reranker_enabled": config.reranker.enabled,
            "reranker_model": config.reranker.model,
        }
    except Exception:
        pass

    eval_run = EvaluationRun(
        run_id=run_id,
        timestamp=timestamp,
        framework="DeepEval",
        eval_model=eval_model,
        total_tests=total_tests,
        passed_tests=passed_tests,
        pass_rate=pass_rate,
        metric_averages=metric_averages,
        metric_pass_rates=metric_pass_rates,
        retrieval_config=retrieval_config,
        config_snapshot=config_snapshot,
        latency=latency_metrics,
        cost=cost_metrics,
        test_cases=test_cases,
        notes=notes,
    )

    # Save to disk
    if save:
        save_evaluation_run(eval_run)

    return eval_run


def print_evaluation_summary(eval_run: EvaluationRun) -> None:
    """Print a summary of evaluation results."""
    print("\n" + "=" * 70)
    print("EVALUATION RESULTS SUMMARY")
    print("=" * 70)
    print(f"Run ID:      {eval_run.run_id}")
    print(f"Timestamp:   {eval_run.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Framework:   {eval_run.framework}")
    print(f"Eval Model:  {eval_run.eval_model}")
    print()

    print("OVERALL RESULTS")
    print("-" * 70)
    print(f"Total Tests: {eval_run.total_tests}")
    print(f"Passed:      {eval_run.passed_tests} ({eval_run.pass_rate:.1f}%)")
    print(f"Failed:      {eval_run.total_tests - eval_run.passed_tests}")
    print()

    print("METRIC AVERAGES")
    print("-" * 70)

    # Define order and formatting
    metric_order = [
        "contextual_precision",
        "contextual_recall",
        "faithfulness",
        "answer_relevancy",
        "hallucination",
    ]

    for metric in metric_order:
        if metric in eval_run.metric_averages:
            score = eval_run.metric_averages[metric]
            pass_rate = eval_run.metric_pass_rates.get(metric, 0)

            # Status indicator
            if metric == "hallucination":
                status = "✓" if score < 0.5 else "✗"
            else:
                status = "✓" if score >= 0.7 else "✗"

            print(f"  {metric:25s}: {score:.3f}  (pass rate: {pass_rate:.1f}%)  {status}")

    # Print any additional metrics
    for metric, score in eval_run.metric_averages.items():
        if metric not in metric_order:
            pass_rate = eval_run.metric_pass_rates.get(metric, 0)
            print(f"  {metric:25s}: {score:.3f}  (pass rate: {pass_rate:.1f}%)")

    if eval_run.retrieval_config:
        print()
        print("CONFIGURATION")
        print("-" * 70)
        cfg = eval_run.retrieval_config
        print(f"  Hybrid Search:          {'enabled' if cfg.get('hybrid_search_enabled') else 'disabled'}")
        print(f"  Contextual Retrieval:   {'enabled' if cfg.get('contextual_retrieval_enabled') else 'disabled'}")
        print(f"  Reranker:               {'enabled' if cfg.get('reranker_enabled') else 'disabled'}")
        if cfg.get('reranker_enabled'):
            print(f"  Reranker Model:         {cfg.get('reranker_model')}")
        print(f"  Top-K:                  {cfg.get('retrieval_top_k')}")
        print(f"  Final Top-N:            {cfg.get('final_top_n')}")

    print("=" * 70)
