"""Unified CLI for RAG evaluation tasks.

This module provides a command-line interface for running evaluations,
generating Q&A pairs, and managing the golden dataset.
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


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="RAG Evaluation CLI - Evaluate, generate, and manage test data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run evaluation on all test cases
  python -m evaluation.cli eval

  # Run evaluation on first 5 test cases (quick test)
  python -m evaluation.cli eval --samples 5

  # Show dataset statistics
  python -m evaluation.cli stats

  # Generate Q&A pairs from a document
  python -m evaluation.cli generate document.txt -n 10 -o generated.json

  # Generate Q&A pairs and merge with golden dataset
  python -m evaluation.cli generate documents/ --merge
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
