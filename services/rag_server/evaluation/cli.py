"""Unified CLI for RAG evaluation tasks.

This module provides a command-line interface for running evaluations,
generating Q&A pairs, managing baselines, comparing runs, and getting
configuration recommendations.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from evaluation.live_eval import run_live_evaluation_sync, check_rag_server_health
from evaluation.dataset_loader import (
    load_golden_dataset,
    get_dataset_stats,
)
from evaluation.generate_qa import (
    generate_qa_for_document,
    generate_qa_for_directory,
    merge_with_golden_dataset,
)
from services.baseline import get_baseline_service
from services.comparison import get_comparison_service
from services.recommendation import get_recommendation_service
from services.metrics import get_evaluation_run_by_id, load_evaluation_history


def cmd_run_evaluation(args):
    """Run live RAG evaluation."""
    print("🔍 Running RAG Evaluation...")
    print(f"   Server: {args.server_url}")
    print(f"   Limit: {args.samples or 'All test cases'}")
    print(f"   Save results: {args.save}")
    print()

    # Check server health
    is_healthy = asyncio.run(check_rag_server_health())
    if not is_healthy:
        print(f"❌ RAG server not responding at {args.server_url}")
        print("   Start the server: docker compose up -d")
        return 1

    print("✅ RAG server is healthy\n")

    # Run evaluation
    try:
        results = run_live_evaluation_sync(
            include_reason=not args.no_reason,
            verbose=args.verbose,
            limit=args.samples,
        )

        # Save results for metrics API
        if args.save:
            from evaluation.results_converter import (
                convert_deepeval_results,
                print_evaluation_summary,
            )
            import os

            eval_model = os.getenv("EVAL_MODEL", "claude-sonnet-4-20250514")
            notes = f"CLI evaluation with {args.samples or 'all'} samples"

            eval_run = convert_deepeval_results(
                results,
                eval_model=eval_model,
                notes=notes,
                save=True,
            )

            print_evaluation_summary(eval_run)
            print(f"\n📁 Results saved (run_id: {eval_run.run_id})")
            print("   View via API: GET /metrics/evaluation/history")
        else:
            print("\n" + "=" * 60)
            print("✅ Evaluation Complete")
            print("=" * 60)
            print("\n💡 Tip: Use --save to store results for comparison")

        return 0

    except Exception as e:
        print(f"\n❌ Evaluation failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


def cmd_dataset_stats(args):
    """Show statistics about the golden dataset."""
    try:
        dataset = load_golden_dataset()
        stats = get_dataset_stats(dataset)

        print("📊 Golden Dataset Statistics")
        print("=" * 60)
        print(f"Total Q&A pairs: {stats['total']}")
        print()

        if stats["by_type"]:
            print("By Query Type:")
            for qtype, count in sorted(stats["by_type"].items()):
                print(f"  {qtype:15s}: {count:3d} ({count/stats['total']*100:.1f}%)")
            print()

        if stats["by_difficulty"]:
            print("By Difficulty:")
            for diff, count in sorted(stats["by_difficulty"].items()):
                print(f"  {diff:15s}: {count:3d} ({count/stats['total']*100:.1f}%)")
            print()

        if stats["by_document"]:
            print("By Document:")
            for doc, count in sorted(stats["by_document"].items()):
                print(f"  {doc:25s}: {count:3d}")
            print()

        print(f"With tags: {stats['with_tags']} ({stats['with_tags']/stats['total']*100:.1f}%)")

        return 0

    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


def cmd_generate_qa(args):
    """Generate synthetic Q&A pairs."""
    print(f"🤖 Generating Q&A pairs from {args.input}")
    print(f"   Questions per document: {args.num_questions}")
    print(f"   Model: {args.model}")
    print()

    try:
        if args.input.is_file():
            qa_pairs = generate_qa_for_document(
                args.input, num_questions=args.num_questions, model=args.model
            )
            print(f"✅ Generated {len(qa_pairs)} Q&A pairs")

        elif args.input.is_dir():
            qa_pairs = generate_qa_for_directory(
                args.input,
                num_questions_per_doc=args.num_questions,
                file_pattern=args.pattern,
                model=args.model,
            )
            print(f"\n✅ Generated {len(qa_pairs)} Q&A pairs total")

        else:
            print(f"❌ {args.input} is not a file or directory")
            return 1

        # Save or merge
        if args.merge:
            golden_path = Path(__file__).parent.parent / "eval_data" / "golden_qa.json"
            output_path = args.output or (golden_path.parent / "golden_qa_expanded.json")

            merge_with_golden_dataset(qa_pairs, golden_path, output_path)
            print(f"✅ Merged with golden dataset → {output_path}")

        elif args.output:
            import json

            with open(args.output, "w") as f:
                json.dump(qa_pairs, f, indent=2)
            print(f"✅ Saved to {args.output}")

        else:
            import json

            print(json.dumps(qa_pairs, indent=2))

        return 0

    except Exception as e:
        print(f"❌ Error: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


# ============================================================================
# Baseline Commands
# ============================================================================


def cmd_baseline(args):
    """Manage the golden baseline."""
    baseline_service = get_baseline_service()

    if args.baseline_cmd == "show":
        baseline = baseline_service.get_baseline()
        if baseline:
            print("🎯 Golden Baseline")
            print("=" * 60)
            print(f"Run ID:  {baseline.run_id}")
            print(f"Set at:  {baseline.set_at}")
            print(f"Set by:  {baseline.set_by or 'Unknown'}")
            print()
            print("Configuration:")
            print(f"  LLM:        {baseline.config_snapshot.llm_model}")
            print(f"  Hybrid:     {'enabled' if baseline.config_snapshot.hybrid_search_enabled else 'disabled'}")
            print(f"  Reranker:   {'enabled' if baseline.config_snapshot.reranker_enabled else 'disabled'}")
            print()
            print("Target Thresholds:")
            for metric, threshold in baseline.target_metrics.items():
                print(f"  {metric:25s}: {threshold:.3f}")
        else:
            print("No baseline set. Use 'baseline set <run_id>' to set one.")
        return 0

    elif args.baseline_cmd == "set":
        run = get_evaluation_run_by_id(args.run_id)
        if not run:
            print(f"❌ Evaluation run '{args.run_id}' not found")
            return 1

        baseline = baseline_service.set_baseline(run, set_by="CLI")
        print(f"✅ Baseline set to run {baseline.run_id}")
        print(f"   LLM: {baseline.config_snapshot.llm_model}")
        return 0

    elif args.baseline_cmd == "clear":
        if baseline_service.clear_baseline():
            print("✅ Baseline cleared")
        else:
            print("No baseline was set")
        return 0

    elif args.baseline_cmd == "check":
        baseline = baseline_service.get_baseline()
        if not baseline:
            print("❌ No baseline set")
            return 1

        # Get latest run
        history = load_evaluation_history(limit=1)
        if not history.runs:
            print("❌ No evaluation runs found")
            return 1

        latest_run = history.runs[0]
        result = baseline_service.check_against_baseline(latest_run)

        print(f"Comparing {latest_run.run_id} to baseline {baseline.run_id}")
        print("=" * 60)

        for metric in result.metrics_pass:
            delta = result.metric_deltas.get(metric, 0)
            print(f"  ✅ {metric:25s}: PASS ({delta:+.1%})")

        for metric in result.metrics_fail:
            delta = result.metric_deltas.get(metric, 0)
            print(f"  ❌ {metric:25s}: FAIL ({delta:+.1%})")

        print()
        if result.overall_pass:
            print("🎉 Result: BASELINE PASSED")
        else:
            print(f"⚠️  Result: BASELINE FAILED ({len(result.metrics_fail)} metrics)")

        return 0 if result.overall_pass else 1

    elif args.baseline_cmd == "list":
        history = load_evaluation_history(limit=10)
        if not history.runs:
            print("No evaluation runs found")
            return 0

        print("Recent Evaluation Runs (use run_id to set baseline)")
        print("=" * 60)
        for run in history.runs:
            model = run.config_snapshot.llm_model if run.config_snapshot else "Unknown"
            print(f"  {run.run_id:20s}  {model:20s}  {run.timestamp}")

        return 0

    else:
        print("Unknown baseline command. Use: show, set, clear, check, list")
        return 1


# ============================================================================
# Compare Command
# ============================================================================


def cmd_compare(args):
    """Compare two evaluation runs."""
    run_a = get_evaluation_run_by_id(args.run_a)
    run_b = get_evaluation_run_by_id(args.run_b)

    if not run_a:
        print(f"❌ Run '{args.run_a}' not found")
        return 1
    if not run_b:
        print(f"❌ Run '{args.run_b}' not found")
        return 1

    comparison_service = get_comparison_service()
    result = comparison_service.compare_runs(run_a, run_b)

    if args.json:
        import json
        print(json.dumps(result.model_dump(), indent=2, default=str))
        return 0

    # Print comparison
    model_a = run_a.config_snapshot.llm_model if run_a.config_snapshot else run_a.run_id
    model_b = run_b.config_snapshot.llm_model if run_b.config_snapshot else run_b.run_id

    print(f"Comparison: {model_a} vs {model_b}")
    print("=" * 60)
    print()

    print(f"{'Metric':<25s} {'Run A':>12s} {'Run B':>12s} {'Delta':>12s}")
    print("-" * 60)

    for metric, delta in result.metric_deltas.items():
        val_a = run_a.metric_averages.get(metric, 0)
        val_b = run_b.metric_averages.get(metric, 0)
        sign = "+" if delta > 0 else ""
        print(f"{metric:<25s} {val_a:>11.1%} {val_b:>11.1%} {sign}{delta:>10.1%}")

    print()

    if result.latency_delta_ms is not None:
        print(f"Latency (P95):  {result.latency_delta_ms:+.0f}ms ({result.latency_improvement_pct:+.1f}%)")

    if result.cost_delta_usd is not None:
        print(f"Cost/query:     ${result.cost_delta_usd:+.4f} ({result.cost_improvement_pct:+.1f}%)")

    print()
    if result.winner == "run_a":
        print(f"🏆 Winner: {model_a}")
    elif result.winner == "run_b":
        print(f"🏆 Winner: {model_b}")
    else:
        print("🤝 Tie")

    print(f"   Reason: {result.winner_reason}")

    return 0


# ============================================================================
# Recommend Command
# ============================================================================


def cmd_recommend(args):
    """Get configuration recommendation."""
    recommendation_service = get_recommendation_service()

    result = recommendation_service.get_recommendation(
        accuracy_weight=args.accuracy,
        speed_weight=args.speed,
        cost_weight=args.cost,
        limit_to_runs=args.limit,
    )

    if result is None:
        print("❌ Insufficient evaluation data for recommendations")
        print("   Run at least one evaluation with --save first")
        return 1

    if args.json:
        import json
        print(json.dumps(result.model_dump(), indent=2, default=str))
        return 0

    print("🎯 Configuration Recommendation")
    print("=" * 60)
    print()

    config = result.recommended_config
    print(f"Recommended Configuration:")
    print(f"  LLM Model:    {config.llm_model} ({config.llm_provider})")
    print(f"  Embedding:    {config.embedding_model}")
    print(f"  Hybrid:       {'enabled' if config.hybrid_search_enabled else 'disabled'}")
    print(f"  Reranker:     {'enabled' if config.reranker_enabled else 'disabled'}")
    print()

    print(f"Scores (based on weights: accuracy={args.accuracy}, speed={args.speed}, cost={args.cost}):")
    print(f"  Accuracy:   {result.accuracy_score:.0%}")
    print(f"  Speed:      {result.speed_score:.0%}")
    print(f"  Cost:       {result.cost_score:.0%}")
    print(f"  Composite:  {result.composite_score:.0%}")
    print()

    print(f"Reasoning: {result.reasoning}")
    print()

    if result.alternatives:
        print("Alternatives:")
        for alt in result.alternatives:
            print(f"  - {alt['model']}: {alt['reason']}")

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="RAG Evaluation CLI - Evaluate, generate, compare, and manage baselines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run evaluation on all test cases
  python -m evaluation.cli eval

  # Run evaluation on first 5 test cases (quick test)
  python -m evaluation.cli eval --samples 5 --save

  # Show dataset statistics
  python -m evaluation.cli stats

  # Baseline management
  python -m evaluation.cli baseline list
  python -m evaluation.cli baseline set <run_id>
  python -m evaluation.cli baseline check

  # Compare two evaluation runs
  python -m evaluation.cli compare <run_a_id> <run_b_id>

  # Get configuration recommendation
  python -m evaluation.cli recommend --accuracy=0.6 --speed=0.2 --cost=0.2

  # Generate Q&A pairs from a document
  python -m evaluation.cli generate document.txt -n 10 -o generated.json
        """,
    )

    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Evaluation command
    eval_parser = subparsers.add_parser(
        "eval", aliases=["evaluate", "run"], help="Run live RAG evaluation"
    )
    eval_parser.add_argument(
        "-n",
        "--samples",
        type=int,
        help="Number of samples to evaluate (default: all)",
    )
    eval_parser.add_argument(
        "--no-reason",
        action="store_true",
        help="Skip metric explanations (faster)",
    )
    eval_parser.add_argument(
        "--server-url",
        default="http://localhost:8001",
        help="RAG server URL",
    )
    eval_parser.add_argument(
        "-s",
        "--save",
        action="store_true",
        help="Save results for metrics API (enables historical comparison)",
    )
    eval_parser.set_defaults(func=cmd_run_evaluation)

    # Dataset stats command
    stats_parser = subparsers.add_parser(
        "stats", aliases=["info"], help="Show golden dataset statistics"
    )
    stats_parser.set_defaults(func=cmd_dataset_stats)

    # Generate Q&A command
    gen_parser = subparsers.add_parser(
        "generate", aliases=["gen"], help="Generate synthetic Q&A pairs"
    )
    gen_parser.add_argument(
        "input", type=Path, help="Document file or directory"
    )
    gen_parser.add_argument(
        "-n",
        "--num-questions",
        type=int,
        default=10,
        help="Questions per document (default: 10)",
    )
    gen_parser.add_argument(
        "-o", "--output", type=Path, help="Output file (default: stdout)"
    )
    gen_parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge with existing golden dataset",
    )
    gen_parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Claude model (default: claude-sonnet-4-20250514)",
    )
    gen_parser.add_argument(
        "--pattern",
        default="*.txt",
        help="File pattern for directory (default: *.txt)",
    )
    gen_parser.set_defaults(func=cmd_generate_qa)

    # Baseline management command
    baseline_parser = subparsers.add_parser(
        "baseline", help="Manage golden baseline"
    )
    baseline_sub = baseline_parser.add_subparsers(dest="baseline_cmd")

    baseline_sub.add_parser("show", help="Show current baseline")
    baseline_sub.add_parser("list", help="List recent evaluation runs")
    baseline_sub.add_parser("clear", help="Clear current baseline")
    baseline_sub.add_parser("check", help="Check latest run against baseline")

    set_parser = baseline_sub.add_parser("set", help="Set run as baseline")
    set_parser.add_argument("run_id", help="Evaluation run ID to set as baseline")

    baseline_parser.set_defaults(func=cmd_baseline)

    # Compare command
    compare_parser = subparsers.add_parser(
        "compare", help="Compare two evaluation runs"
    )
    compare_parser.add_argument("run_a", help="First evaluation run ID")
    compare_parser.add_argument("run_b", help="Second evaluation run ID")
    compare_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    compare_parser.set_defaults(func=cmd_compare)

    # Recommend command
    recommend_parser = subparsers.add_parser(
        "recommend", aliases=["rec"], help="Get configuration recommendation"
    )
    recommend_parser.add_argument(
        "--accuracy", type=float, default=0.5,
        help="Weight for accuracy (0-1, default: 0.5)"
    )
    recommend_parser.add_argument(
        "--speed", type=float, default=0.3,
        help="Weight for speed (0-1, default: 0.3)"
    )
    recommend_parser.add_argument(
        "--cost", type=float, default=0.2,
        help="Weight for cost efficiency (0-1, default: 0.2)"
    )
    recommend_parser.add_argument(
        "--limit", type=int, default=10,
        help="Max runs to consider (default: 10)"
    )
    recommend_parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    recommend_parser.set_defaults(func=cmd_recommend)

    return parser


def main():
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Show help if no command
    if not args.command:
        parser.print_help()
        return 0

    # Run command
    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
