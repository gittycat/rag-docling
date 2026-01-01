"""CLI for running benchmarks.

Usage:
    python -m evaluation.benchmark_cli run squad --samples 100
    python -m evaluation.benchmark_cli list
    python -m evaluation.benchmark_cli history squad
    python -m evaluation.benchmark_cli dashboard
"""

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from evaluation.benchmark import run_benchmark, BenchmarkConfig, BenchmarkRunner
from evaluation.results_store import BenchmarkResultsStore
from evaluation.datasets import list_datasets, get_dataset


def cmd_run(args):
    """Run a benchmark."""
    print(f"Running benchmark: {args.dataset}")
    print(f"  Sample size: {args.samples or 'all'}")
    print(f"  Server: {args.server}")
    print()

    try:
        config = BenchmarkConfig(
            dataset_name=args.dataset,
            sample_size=args.samples,
            rag_server_url=args.server,
            run_notes=args.notes or "",
        )

        async def run():
            async with BenchmarkRunner(config) as runner:
                return await runner.run()

        result = asyncio.run(run())

        print("\n" + "=" * 60)
        print("BENCHMARK COMPLETE")
        print("=" * 60)
        print(f"Run ID: {result.run_id}")
        print(f"Dataset: {result.dataset_name}")
        print(f"Samples: {result.sample_size}")
        print(f"Total time: {result.total_time_seconds:.1f}s")
        print()
        print("Metrics:")
        for metric in result.metrics:
            if "latency" in metric.name:
                print(f"  {metric.name}: {metric.score:.0f}ms")
            else:
                print(f"  {metric.name}: {metric.score:.3f}")

        return 0

    except Exception as e:
        print(f"\nError: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_list_datasets(args):
    """List available datasets."""
    print("Available datasets:")
    print()

    for name in list_datasets():
        dataset = get_dataset(name, sample_size=1)
        try:
            dataset.load()
            info = dataset.info
            print(f"  {name:15s} - {info.description[:50]}...")
        except Exception:
            print(f"  {name:15s} - (info unavailable)")

    print()
    print("Usage: python -m evaluation.benchmark_cli run <dataset> [--samples N]")
    return 0


def cmd_history(args):
    """Show benchmark history."""
    store = BenchmarkResultsStore()
    runs = store.list_runs(dataset_name=args.dataset, limit=args.limit)

    if not runs:
        print("No benchmark runs found.")
        return 0

    print(f"{'Run ID':<25} {'Dataset':<15} {'Samples':>8} {'Recall@K':>10} {'MRR':>8} {'Time':>8}")
    print("-" * 80)

    for run in runs:
        recall = run.get_metric("recall@k")
        mrr = run.get_metric("mrr")
        print(
            f"{run.run_id:<25} "
            f"{run.dataset_name:<15} "
            f"{run.sample_size:>8} "
            f"{recall:>9.1%} " if recall else f"{'N/A':>10} "
            f"{mrr:>7.1%} " if mrr else f"{'N/A':>8} "
            f"{run.total_time_seconds:>7.1f}s"
        )

    return 0


def cmd_stats(args):
    """Show summary statistics."""
    store = BenchmarkResultsStore()
    stats = store.get_summary_stats(dataset_name=args.dataset)

    if not stats:
        print("No benchmark data available.")
        return 0

    print(f"Total runs: {stats['total_runs']}")
    print(f"Datasets: {', '.join(stats['datasets'])}")
    print()
    print("Metrics Summary:")
    print(f"{'Metric':<20} {'Mean':>10} {'Min':>10} {'Max':>10} {'Latest':>10}")
    print("-" * 62)

    for name, values in stats["metrics"].items():
        if "latency" in name:
            print(
                f"{name:<20} "
                f"{values['mean']:>9.0f}ms "
                f"{values['min']:>9.0f}ms "
                f"{values['max']:>9.0f}ms "
                f"{values['latest']:>9.0f}ms"
            )
        else:
            print(
                f"{name:<20} "
                f"{values['mean']:>10.3f} "
                f"{values['min']:>10.3f} "
                f"{values['max']:>10.3f} "
                f"{values['latest']:>10.3f}"
            )

    return 0


def cmd_dashboard(args):
    """Launch the Streamlit dashboard."""
    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"

    print(f"Launching dashboard at http://localhost:{args.port}")
    print("Press Ctrl+C to stop")
    print()

    try:
        subprocess.run(
            ["streamlit", "run", str(dashboard_path), "--server.port", str(args.port)],
            cwd=Path(__file__).parent.parent,
        )
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    except FileNotFoundError:
        print("Error: streamlit not found. Install with: uv add streamlit")
        return 1

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="RAG Benchmark CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available datasets
  python -m evaluation.benchmark_cli datasets

  # Run benchmark on SQuAD with 100 samples
  python -m evaluation.benchmark_cli run squad --samples 100

  # Run full RAGBench benchmark
  python -m evaluation.benchmark_cli run ragbench

  # View history
  python -m evaluation.benchmark_cli history

  # View stats
  python -m evaluation.benchmark_cli stats

  # Launch dashboard
  python -m evaluation.benchmark_cli dashboard
        """,
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a benchmark")
    run_parser.add_argument("dataset", help="Dataset name (squad, ragbench, hotpotqa)")
    run_parser.add_argument(
        "-n", "--samples", type=int, help="Number of samples (default: all)"
    )
    run_parser.add_argument(
        "--server",
        default="http://localhost:8003",
        help="RAG server URL (default: benchmark server)",
    )
    run_parser.add_argument("--notes", help="Notes for this run")
    run_parser.set_defaults(func=cmd_run)

    # Datasets command
    datasets_parser = subparsers.add_parser("datasets", help="List available datasets")
    datasets_parser.set_defaults(func=cmd_list_datasets)

    # History command
    history_parser = subparsers.add_parser("history", help="Show benchmark history")
    history_parser.add_argument("dataset", nargs="?", help="Filter by dataset")
    history_parser.add_argument(
        "-n", "--limit", type=int, default=20, help="Number of runs to show"
    )
    history_parser.set_defaults(func=cmd_history)

    # Stats command
    stats_parser = subparsers.add_parser("stats", help="Show summary statistics")
    stats_parser.add_argument("dataset", nargs="?", help="Filter by dataset")
    stats_parser.set_defaults(func=cmd_stats)

    # Dashboard command
    dashboard_parser = subparsers.add_parser("dashboard", help="Launch dashboard")
    dashboard_parser.add_argument(
        "-p", "--port", type=int, default=8501, help="Port (default: 8501)"
    )
    dashboard_parser.set_defaults(func=cmd_dashboard)

    return parser


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if hasattr(args, "func"):
        return args.func(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
