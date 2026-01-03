"""CLI for evaluation v2."""

import argparse

from evaluation_v2.datasets import list_datasets, get_dataset
from evaluation_v2.runner import EvalRunnerConfig, run_evaluation_sync
from services.metrics import load_evaluation_history


def cmd_datasets(_args) -> int:
    print("Available datasets:")
    for name in list_datasets():
        try:
            dataset = get_dataset(name, sample_size=1)
            dataset.load()
            info = dataset.info
            print(f"  {name:12s} - {info.description}")
        except Exception as exc:
            print(f"  {name:12s} - (info unavailable: {exc})")
    return 0


def cmd_run(args) -> int:
    config = EvalRunnerConfig(
        dataset_name=args.dataset,
        sample_size=args.samples,
        server_url=args.server,
        include_reason=not args.no_reason,
        retrieval_k=args.k,
        citation_scope=args.citation_scope,
        export_review_path=args.export_review,
        export_review_format=args.export_review_format,
        run_notes=args.notes or "",
    )
    result = run_evaluation_sync(config)
    print(f"Run complete: {result.run_id}")
    print(f"Samples: {result.total_tests}")
    print(f"Pass rate: {result.pass_rate:.1f}%")
    return 0


def cmd_history(args) -> int:
    history = load_evaluation_history(limit=args.limit)
    if not history.runs:
        print("No evaluation runs found.")
        return 0
    for run in history.runs:
        print(f"{run.run_id}  {run.timestamp}  {run.total_tests} tests  pass={run.pass_rate:.1f}%")
    return 0


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluation v2 CLI")
    subparsers = parser.add_subparsers(dest="command")

    datasets_parser = subparsers.add_parser("datasets", help="List datasets")
    datasets_parser.set_defaults(func=cmd_datasets)

    run_parser = subparsers.add_parser("run", help="Run evaluation")
    run_parser.add_argument("dataset", help="Dataset name")
    run_parser.add_argument("-n", "--samples", type=int, help="Number of samples")
    run_parser.add_argument("--server", default="http://localhost:8001", help="RAG server URL")
    run_parser.add_argument("--notes", help="Run notes")
    run_parser.add_argument("-k", type=int, default=10, help="Retrieval top-K")
    run_parser.add_argument("--no-reason", action="store_true", help="Skip metric explanations")
    run_parser.add_argument(
        "--citation-scope",
        choices=["retrieved", "explicit"],
        help="Use retrieved chunks or explicit citations for citation metrics",
    )
    run_parser.add_argument(
        "--export-review",
        help="Path to export manual review data (json or csv)",
    )
    run_parser.add_argument(
        "--export-review-format",
        choices=["json", "csv"],
        default="json",
        help="Manual review export format",
    )
    run_parser.set_defaults(func=cmd_run)

    history_parser = subparsers.add_parser("history", help="Show evaluation history")
    history_parser.add_argument("-n", "--limit", type=int, default=10)
    history_parser.set_defaults(func=cmd_history)

    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
