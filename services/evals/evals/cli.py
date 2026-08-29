"""Command-line interface for evals.

Usage:
    # Run evaluation with defaults
    python -m evals.cli eval

    # Run with specific datasets
    python -m evals.cli eval --datasets ragbench,squad_v2

    # Run with limited samples
    python -m evals.cli eval --samples 10

    # Show dataset stats
    python -m evals.cli stats

    # List available datasets
    python -m evals.cli datasets

    # Export results for manual review
    python -m evals.cli export --run-id abc123

    # Compare multiple runs
    python -m evals.cli compare run1 run2 run3
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
)

from evals.cache import (
    DEFAULT_CACHE_DIR,
    CacheConfig,
    clear_cache as clear_response_cache,
)
from evals.config import EvalConfig, DatasetName, EvalTier, DATASET_TIER_SUPPORT, MetricConfig, resolve_judge_config
from evals.datasets.registry import list_datasets, get_dataset, clear_cache, CACHE_DIR
from evals.export import export_for_review, export_run_report, export_scorecard
from evals.experiment_store import ExperimentStore
from evals.judges.llm_judge import warn_if_judge_not_independent
from evals.runner import EvaluationRunner, run_evaluation, compute_pareto_frontier
from evals.samples import SAMPLES_SUFFIX, load_samples, samples_path_for
from evals.schemas import (
    ConfigSnapshot,
    EvalRun,
    MetricGroup,
    MetricResult,
    Scorecard,
    WeightedScore,
)
from evals.stats import DEFAULT_BOOTSTRAP_SAMPLES, UNDERPOWERED_N, compare_runs
from infrastructure.config.display import print_config_banner
from infrastructure.settings import init_settings


def main():
    """Main CLI entry point."""
    init_settings()
    parser = argparse.ArgumentParser(
        description="RAG Evaluation Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # eval command
    eval_parser = subparsers.add_parser("eval", help="Run evaluation")
    eval_parser.add_argument(
        "--datasets",
        type=str,
        help="Comma-separated list of datasets (ragbench,squad_v2,qasper,hotpotqa,msmarco)",
        default="ragbench",
    )
    eval_parser.add_argument(
        "--samples",
        type=int,
        help="Number of samples per dataset (default: 100)",
        default=100,
    )
    eval_parser.add_argument(
        "--seed",
        type=int,
        help="Random seed for reproducibility",
        default=42,
    )
    eval_parser.add_argument(
        "--name",
        type=str,
        help="Name for this evaluation run",
    )
    eval_parser.add_argument(
        "--rag-url",
        type=str,
        help="RAG server URL (default: RAG_SERVER_URL env or http://localhost:8001)",
        default=os.environ.get("RAG_SERVER_URL", "http://localhost:8001"),
    )
    eval_parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Disable LLM-as-judge metrics (faster but less comprehensive)",
    )
    eval_parser.add_argument(
        "--groundedness",
        action="store_true",
        help=(
            "Deprecated: claim groundedness now runs by default."
        ),
    )
    eval_parser.add_argument(
        "--output",
        type=str,
        help="Output directory for results",
        default="data/eval_runs",
    )
    eval_parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML configuration file",
    )
    eval_parser.add_argument(
        "--tier",
        type=str,
        choices=["generation", "end_to_end"],
        default="end_to_end",
        help="Evaluation tier: generation (inject context, no ingestion) or end_to_end (full pipeline)",
    )
    eval_parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Use POST /search only: no generation or judge calls",
    )
    eval_parser.add_argument(
        "--retrieval-source",
        choices=["bm25", "vector", "fusion", "rerank"],
        default="rerank",
        help="Stage treated as the final ranking in retrieval-only mode",
    )
    eval_parser.add_argument(
        "--search-top-k",
        type=int,
        default=10,
        help="Candidate depth requested from POST /search in retrieval-only mode",
    )
    eval_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Bypass dataset cache (re-download from source)",
    )
    eval_parser.add_argument(
        "--no-judge-cache",
        action="store_true",
        help="Re-run every judge call instead of reusing identical cached ones",
    )
    eval_parser.add_argument(
        "--cache-queries",
        action="store_true",
        help=(
            "Reuse RAG answers cached from a previous run with the same server "
            "configuration. The key does NOT cover the indexed corpus — do not use "
            "this after re-ingesting documents."
        ),
    )

    # calibrate command — judge vs RAGBench TRACe ground-truth labels
    calibrate_parser = subparsers.add_parser(
        "calibrate",
        help="Calibrate the LLM judge against RAGBench TRACe annotations",
    )
    calibrate_parser.add_argument(
        "--samples",
        type=int,
        default=20,
        help="Total number of RAGBench items to judge (default: 20)",
    )
    calibrate_parser.add_argument(
        "--subsets",
        type=str,
        help="Comma-separated RAGBench subsets (default: curated mix)",
    )
    calibrate_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for sampling",
    )
    calibrate_parser.add_argument(
        "--output",
        type=str,
        default="data/calibration",
        help="Output directory for calibration results",
    )

    # cache command
    cache_parser = subparsers.add_parser("cache", help="Manage dataset and response caches")
    cache_sub = cache_parser.add_subparsers(dest="cache_action")
    clear_sub = cache_sub.add_parser("clear", help="Clear cached datasets and/or responses")
    clear_sub.add_argument(
        "--what",
        choices=["datasets", "responses", "all"],
        default="datasets",
        help="Which cache to clear (default: datasets)",
    )
    cache_sub.add_parser("status", help="Show cache status")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show dataset statistics")
    stats_parser.add_argument(
        "--dataset",
        type=str,
        help="Specific dataset to show stats for",
    )

    # datasets command
    subparsers.add_parser("datasets", help="List available datasets")

    # export command
    export_parser = subparsers.add_parser("export", help="Export results for manual review")
    export_parser.add_argument(
        "--run-id",
        type=str,
        required=True,
        help="Run ID to export",
    )
    export_parser.add_argument(
        "--format",
        type=str,
        choices=[
            "json",
            "csv",
            "review-json",
            "review-csv",
            "review-md",
            "scorecard-csv",
            "scorecard-md",
            "report",
        ],
        default="json",
        help=(
            "json/csv: run metrics. review-*: per-question sheet with blank reviewer "
            "columns (needs the run's samples sidecar). scorecard-*: metrics only. "
            "report: full Markdown run report."
        ),
    )
    export_parser.add_argument(
        "--output",
        type=str,
        help="Output file path",
    )
    export_parser.add_argument(
        "--runs-dir",
        type=str,
        help=f"Directory holding run files (default: {RUNS_DIR})",
    )

    # compare command
    compare_parser = subparsers.add_parser("compare", help="Compare multiple evaluation runs")
    compare_parser.add_argument(
        "run_ids",
        nargs="+",
        help="Run IDs to compare",
    )
    compare_parser.add_argument(
        "--pareto",
        action="store_true",
        help="Show Pareto frontier analysis",
    )
    compare_parser.add_argument(
        "--no-significance",
        action="store_true",
        help="Skip paired bootstrap / McNemar significance testing",
    )
    compare_parser.add_argument(
        "--bootstrap-samples",
        type=int,
        default=None,
        help=f"Bootstrap resamples (default {DEFAULT_BOOTSTRAP_SAMPLES})",
    )
    compare_parser.add_argument(
        "--runs-dir",
        type=str,
        help=f"Directory holding run files (default: {RUNS_DIR})",
    )

    contextual_parser = subparsers.add_parser(
        "contextual-ab",
        help="Paired A/B: run the same questions with contextual retrieval on and off",
    )
    contextual_parser.add_argument(
        "--datasets", type=str, default="golden",
        help="Comma-separated dataset names (default: golden)",
    )
    contextual_parser.add_argument("--samples", type=int, default=None, help="Samples per dataset")
    contextual_parser.add_argument("--seed", type=int, default=42, help="Random seed")
    contextual_parser.add_argument(
        "--rag-url", type=str, default="http://localhost:8001", help="RAG server URL"
    )
    contextual_parser.add_argument(
        "--output", type=str, default=str(RUNS_DIR), help="Directory for run files"
    )
    contextual_parser.add_argument("--no-judge", action="store_true", help="Disable the LLM judge")
    contextual_parser.add_argument(
        "--bootstrap-samples", type=int, default=None,
        help=f"Bootstrap resamples (default {DEFAULT_BOOTSTRAP_SAMPLES})",
    )

    failures_parser = subparsers.add_parser(
        "failures", help="Query per-question failure attribution from Postgres"
    )
    failures_parser.add_argument(
        "label",
        choices=[
            "retrieval_miss", "fusion_miss", "rerank_drop", "context_truncated",
            "generation_drift", "citation_error", "wrong_abstention",
            "missed_abstention", "correct",
        ],
        help="Failure label to query",
    )
    failures_parser.add_argument(
        "--limit", type=int, default=50, help="Maximum questions to return (default: 50)"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "eval":
        cmd_eval(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "datasets":
        cmd_datasets(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "contextual-ab":
        cmd_contextual_ab(args)
    elif args.command == "failures":
        cmd_failures(args)
    elif args.command == "cache":
        cmd_cache(args)
    elif args.command == "calibrate":
        cmd_calibrate(args)
    else:
        parser.print_help()
        sys.exit(1)


def cmd_eval(args):
    """Run evaluation."""
    # Print config banner
    print_config_banner(compact=True)
    print()

    # Load config from file or build from args
    tier = EvalTier(args.tier)

    if args.config:
        config = EvalConfig.from_yaml(args.config)
        # CLI --tier overrides YAML tier
        config.tier = tier
        print(f"Loaded config from: {args.config}")
        if args.no_judge_cache:
            config.cache.judge = False
        if args.cache_queries:
            config.cache.query = True
        if args.groundedness:
            config.metrics.groundedness = True
        if args.retrieval_only:
            config.retrieval_only = True
            config.retrieval_source = args.retrieval_source
            config.search_top_k = args.search_top_k
    else:
        # Parse datasets
        dataset_names = [
            DatasetName(ds.strip())
            for ds in args.datasets.split(",")
        ]

        # Validate dataset+tier combinations before building config
        incompatible = []
        for ds in dataset_names:
            supported = DATASET_TIER_SUPPORT.get(ds, list(EvalTier))
            if tier not in supported:
                incompatible.append((ds.value, [t.value for t in supported]))

        if incompatible:
            print(f"\nERROR: Incompatible dataset/tier combinations for tier '{tier.value}':")
            for ds_name, supported_tiers in incompatible:
                print(f"  - {ds_name}: supports {supported_tiers}")
            sys.exit(1)

        # Build config
        try:
            config = EvalConfig(
                datasets=dataset_names,
                samples_per_dataset=args.samples,
                seed=args.seed,
                rag_server_url=args.rag_url,
                runs_dir=Path(args.output),
                judge=resolve_judge_config(
                    enabled=not args.no_judge, datasets=dataset_names, tier=tier
                ),
                metrics=MetricConfig(),
                tier=tier,
                retrieval_only=args.retrieval_only,
                retrieval_source=args.retrieval_source,
                search_top_k=args.search_top_k,
                cache=CacheConfig(
                    judge=not args.no_judge_cache,
                    query=args.cache_queries,
                ),
            )
        except ValueError as e:
            print(f"\nERROR: {e}")
            sys.exit(1)

    # For END_TO_END, verify the RAG server's upload endpoint is reachable
    if config.tier == EvalTier.END_TO_END:
        import httpx
        try:
            resp = httpx.get(f"{config.rag_server_url}/health", timeout=5.0)
            if resp.status_code != 200:
                print(f"\nERROR: RAG server at {config.rag_server_url} returned status {resp.status_code}")
                print("For END_TO_END tier, the full RAG stack (rag-server + task-worker) must be running.")
                sys.exit(1)
        except Exception as e:
            print(f"\nERROR: Cannot reach RAG server at {config.rag_server_url}: {e}")
            print("For END_TO_END tier, the full RAG stack (rag-server + task-worker) must be running.")
            sys.exit(1)

    console = Console()
    console.print(f"Tier: {config.tier.value}")
    console.print(f"Datasets: {[ds.value for ds in config.datasets]}")
    console.print(f"Samples per dataset: {config.samples_per_dataset}")
    console.print(f"RAG server: {config.rag_server_url}")
    console.print(f"Judge enabled: {config.judge.enabled}")
    if config.metrics.groundedness:
        console.print(
            f"Groundedness: on (up to {config.metrics.max_claims_per_answer} claims/answer, "
            f"{config.metrics.max_citations_per_claim} citations/claim judged)"
        )
    if config.judge.enabled:
        judge_warning = warn_if_judge_not_independent()
        if judge_warning:
            console.print(f"[yellow]WARNING:[/yellow] {judge_warning}")
    console.rule()

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )

    # Create all steps upfront so the user sees the full pipeline
    step_load = progress.add_task("Load datasets", total=1, visible=True)
    step_query = progress.add_task("Query RAG server", total=None, visible=True)
    step_judge = progress.add_task("Judge metrics", total=None, visible=True)
    step_save = progress.add_task("Save results", total=1, visible=True)

    def progress_callback(info: dict) -> None:
        phase = info.get("phase")

        if phase == "loading_datasets":
            progress.start_task(step_load)

        elif phase == "datasets_loaded":
            progress.update(step_load, completed=1)
            total_q = info.get("total_questions", 0)
            progress.update(step_query, total=total_q)
            # Judge total = questions × judge_metrics
            judge_count = info.get("judge_metric_count", 0)
            if judge_count > 0:
                progress.update(step_judge, total=total_q * judge_count)
            else:
                # No judge metrics — mark as done immediately
                progress.update(step_judge, total=1, completed=1, description="Judge metrics (skipped)")

        elif phase == "querying":
            current = info.get("current_question", 0)
            dataset = info.get("current_dataset", "")
            desc = f"Query RAG server [dim]\\[{dataset}][/dim]" if dataset else "Query RAG server"
            progress.update(step_query, completed=current, description=desc)

        elif phase == "computing_metrics":
            # Querying done — ensure bar is full
            total_q = info.get("total_questions", 0)
            progress.update(step_query, completed=total_q)

        elif phase == "judging_item":
            metric_name = info.get("metric_name", "")
            current = info.get("current_item", 0)
            progress.update(
                step_judge,
                advance=1,
                description=f"Judge metrics [dim]\\[{metric_name}][/dim]",
            )

        elif phase == "saving":
            progress.update(step_save, completed=0)
            progress.start_task(step_save)

        elif phase == "complete":
            progress.update(step_save, completed=1)

    try:
        with progress:
            result = asyncio.run(run_evaluation(
                config,
                name=args.name,
                progress_callback=progress_callback,
                use_cache=not args.no_cache,
            ))
        console.print()
        print_run_summary(result)
    except ConnectionError as e:
        progress.stop()
        console.print(f"\n[red]ERROR:[/red] {e}")
        console.print("Make sure the RAG server is running.")
        sys.exit(1)
    except Exception as e:
        progress.stop()
        console.print(f"\n[red]ERROR:[/red] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def cmd_stats(args):
    """Show dataset statistics."""
    # Print config banner
    print_config_banner(compact=True)
    print()

    if args.dataset:
        datasets = [args.dataset]
    else:
        datasets = [ds["name"] for ds in list_datasets()]

    print("=" * 60)
    print("Dataset Statistics")
    print("=" * 60)

    for ds_name in datasets:
        try:
            # Load full dataset to get stats
            dataset = get_dataset(ds_name, max_samples=None)
            print(f"\n{ds_name.upper()}")
            print("-" * 40)
            print(f"  Total questions: {len(dataset)}")
            print(f"  Version: {dataset.version}")
            print(f"  Description: {dataset.description[:80]}...")

            # Count by query type
            query_types = {}
            domains = {}
            for q in dataset.questions:
                qt = q.query_type.value
                query_types[qt] = query_types.get(qt, 0) + 1
                domains[q.domain] = domains.get(q.domain, 0) + 1

            if query_types:
                print(f"  Query types:")
                for qt, count in sorted(query_types.items()):
                    print(f"    - {qt}: {count}")

            if len(domains) <= 10:
                print(f"  Domains:")
                for domain, count in sorted(domains.items()):
                    print(f"    - {domain}: {count}")
            else:
                print(f"  Domains: {len(domains)} unique")

        except Exception as e:
            print(f"\n{ds_name}: ERROR - {e}")


def cmd_datasets(args):
    """List available datasets."""
    # Print config banner
    print_config_banner(compact=True)
    print()

    print("=" * 60)
    print("Available Datasets")
    print("=" * 60)

    for ds in list_datasets():
        print(f"\n{ds['name']}")
        print(f"  {ds.get('description', 'No description')[:70]}...")
        print(f"  URL: {ds.get('source_url', 'N/A')}")


RUNS_DIR = Path(os.environ.get("EVAL_RUNS_DIR", "data/eval_runs"))


def _runs_dir(args) -> Path:
    return Path(getattr(args, "runs_dir", None) or RUNS_DIR)


def _find_run_file(run_id: str, runs_dir: Path = RUNS_DIR) -> Path | None:
    """Locate a run file by id prefix, ignoring its samples sidecar."""
    for f in sorted(runs_dir.glob(f"{run_id}*.json")):
        if f.name.endswith(SAMPLES_SUFFIX):
            continue
        return f
    return None


def _load_run(run_id: str, runs_dir: Path) -> tuple[Path, dict]:
    run_file = _find_run_file(run_id, runs_dir)
    if not run_file:
        print(f"ERROR: Run {run_id} not found in {runs_dir}")
        sys.exit(1)
    with open(run_file) as f:
        return run_file, json.load(f)


def _run_from_dict(data: dict) -> EvalRun:
    """Rebuild enough of an EvalRun for the Markdown report exporter."""
    cfg = data.get("config", {})
    scorecard = Scorecard()
    # Notes explain why a group is missing; dropping them on reload would make the
    # exported report look like the metrics simply were not there.
    scorecard.notes = list((data.get("scorecard") or {}).get("notes", []))
    for m in (data.get("scorecard") or {}).get("metrics", []):
        scorecard.add_metric(
            MetricResult(
                name=m["name"],
                value=m["value"],
                group=MetricGroup(m["group"]),
                sample_size=m.get("sample_size", 0),
                details=m.get("details", {}),
            )
        )
    ws = data.get("weighted_score") or {}
    return EvalRun(
        id=data["id"],
        name=data.get("name", ""),
        created_at=datetime.fromisoformat(data["created_at"]),
        completed_at=(
            datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None
        ),
        config=ConfigSnapshot(
            llm_model=cfg.get("llm_model", "unknown"),
            llm_provider=cfg.get("llm_provider", "unknown"),
            embedding_model=cfg.get("embedding_model", "unknown"),
            reranker_model=cfg.get("reranker_model"),
            retrieval_top_k=cfg.get("retrieval_top_k"),
            hybrid_search_enabled=cfg.get("hybrid_search_enabled"),
            contextual_retrieval_enabled=cfg.get("contextual_retrieval_enabled"),
            chunk_size=cfg.get("chunk_size"),
            chunk_overlap=cfg.get("chunk_overlap"),
            chunker=cfg.get("chunker"),
            prompt_fingerprint=cfg.get("prompt_fingerprint"),
            additional=cfg.get("additional", {}),
        ),
        datasets=data.get("datasets", []),
        scorecard=scorecard,
        weighted_score=WeightedScore(
            score=ws.get("score", 0.0),
            weights=ws.get("weights", {}),
            contributions=ws.get("contributions", {}),
            objectives=ws.get("objectives", {}),
        ) if ws else None,
        question_count=data.get("question_count", 0),
        error_count=data.get("error_count", 0),
        metadata=data.get("metadata", {}),
    )


def cmd_export(args):
    """Export results for manual review."""
    run_file, run_data = _load_run(args.run_id, _runs_dir(args))
    fmt = args.format

    if fmt == "json":
        output_path = args.output or f"export_{args.run_id}.json"
        with open(output_path, "w") as f:
            json.dump(run_data, f, indent=2)
        print(f"Exported to: {output_path}")
        return

    if fmt == "csv":
        import csv
        output_path = args.output or f"export_{args.run_id}.csv"

        # Flatten metrics for CSV
        rows = []
        if run_data.get("scorecard"):
            for metric in run_data["scorecard"]["metrics"]:
                rows.append({
                    "run_id": run_data["id"],
                    "run_name": run_data["name"],
                    "metric_name": metric["name"],
                    "metric_group": metric["group"],
                    # Undefined metrics export blank, never 0
                    "value": "" if metric["value"] is None else metric["value"],
                    "sample_size": metric.get("sample_size", ""),
                })

        with open(output_path, "w", newline="") as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

        print(f"Exported to: {output_path}")
        return

    if fmt.startswith("review-"):
        questions, responses = load_samples(run_file)
        if not questions:
            print(
                f"ERROR: No samples sidecar for run {args.run_id}. "
                f"Expected {samples_path_for(run_file).name} — runs completed before "
                "per-question samples were persisted cannot be exported for review."
            )
            sys.exit(1)
        sub_format = {"review-json": "json", "review-csv": "csv", "review-md": "markdown"}[fmt]
        ext = {"json": "json", "csv": "csv", "markdown": "md"}[sub_format]
        output_path = Path(args.output or f"review_{args.run_id}.{ext}")
        export_for_review(questions, responses, output_path, format=sub_format)
        print(f"Exported {len(questions)} questions for review to: {output_path}")
        return

    run = _run_from_dict(run_data)

    if fmt in ("scorecard-csv", "scorecard-md"):
        sub_format = "csv" if fmt == "scorecard-csv" else "markdown"
        ext = "csv" if fmt == "scorecard-csv" else "md"
        output_path = Path(args.output or f"scorecard_{args.run_id}.{ext}")
        export_scorecard(run.scorecard, output_path, format=sub_format)
        print(f"Exported to: {output_path}")
        return

    if fmt == "report":
        output_path = Path(args.output or f"report_{args.run_id}.md")
        export_run_report(run, output_path)
        print(f"Exported to: {output_path}")


def cmd_compare(args):
    """Compare multiple evaluation runs."""
    runs = []
    runs_dir = _runs_dir(args)

    for run_id in args.run_ids:
        run_file = _find_run_file(run_id, runs_dir)
        if run_file is None:
            print(f"WARNING: Run {run_id} not found")
            continue
        with open(run_file) as fh:
            runs.append(json.load(fh))

    if not runs:
        print("ERROR: No runs found")
        sys.exit(1)

    print("=" * 80)
    print("Run Comparison")
    print("=" * 80)

    # Metric names get their own width: at 15 chars the two abstention rates
    # truncate to the same string and become indistinguishable.
    name_width = 30
    col_width = 15
    header = ["Metric".ljust(name_width)] + [r["name"][:col_width].ljust(col_width) for r in runs]
    rule = "-" * (name_width + col_width * len(runs) + 3 * len(runs))
    print(" | ".join(header))
    print(rule)

    # Collect all metric names
    all_metrics = set()
    for run in runs:
        if run.get("scorecard"):
            for m in run["scorecard"]["metrics"]:
                all_metrics.add(m["name"])

    # Print each metric. "n/a" is a metric that was undefined for the dataset;
    # "-" is a metric the run does not have at all.
    for metric_name in sorted(all_metrics):
        row = [metric_name[:name_width].ljust(name_width)]
        for run in runs:
            value = "-"
            if run.get("scorecard"):
                for m in run["scorecard"]["metrics"]:
                    if m["name"] == metric_name:
                        value = "n/a" if m["value"] is None else f"{m['value']:.3f}"
                        break
            row.append(str(value).ljust(col_width))
        print(" | ".join(row))

    # Weighted scores + duration
    print(rule)
    row = ["WEIGHTED SCORE".ljust(name_width)]
    for run in runs:
        ws = run.get("weighted_score", {})
        score = ws.get("score", 0)
        row.append(f"{score:.3f}".ljust(col_width))
    print(" | ".join(row))

    row = ["DURATION".ljust(name_width)]
    for run in runs:
        dur = run.get("duration_seconds")
        row.append((f"{dur:.1f}s" if dur is not None else "-").ljust(col_width))
    print(" | ".join(row))

    # Significance: first run is the baseline, every later run is tested against it
    if not args.no_significance and len(runs) > 1:
        for run in runs[1:]:
            report = compare_runs(
                runs[0],
                run,
                n_resamples=args.bootstrap_samples or DEFAULT_BOOTSTRAP_SAMPLES,
            )
            _print_significance(report, runs[0]["name"], run["name"])

    # Pareto analysis
    if args.pareto and len(runs) > 1:
        print("\n" + "=" * 80)
        print("Pareto Analysis")
        print("=" * 80)
        pareto_points = _compute_pareto_from_dicts(runs)
        _print_pareto_analysis(pareto_points)


def cmd_contextual_ab(args):
    """Run the paired contextual-retrieval A/B and print the deltas."""
    import asyncio

    from evals.contextual_ab import run_contextual_ab

    dataset_names = [DatasetName(ds.strip()) for ds in args.datasets.split(",")]
    tier = EvalTier.END_TO_END
    config = EvalConfig(
        datasets=dataset_names,
        samples_per_dataset=args.samples,
        seed=args.seed,
        rag_server_url=args.rag_url,
        runs_dir=Path(args.output),
        judge=resolve_judge_config(
            enabled=not args.no_judge, datasets=dataset_names, tier=tier
        ),
        metrics=MetricConfig(),
        tier=tier,
    )

    console = Console()
    console.print("[bold]Contextual retrieval A/B[/bold]")
    console.print(f"Datasets: {[ds.value for ds in dataset_names]}")
    console.print("Ingesting the corpus twice — once with contextual retrieval on, once off.")
    console.rule()

    try:
        report = asyncio.run(
            run_contextual_ab(
                config,
                n_resamples=args.bootstrap_samples or DEFAULT_BOOTSTRAP_SAMPLES,
            )
        )
    except ValueError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

    def _row(delta):
        def fmt(value):
            return "n/a" if value is None else f"{value:.4f}"
        arrow = ""
        if delta.delta is not None:
            arrow = "+" if delta.delta > 0 else ""
        change = "n/a" if delta.delta is None else f"{arrow}{delta.delta:.4f}"
        return f"  {delta.name:<34} {fmt(delta.contextual_on):>12} {fmt(delta.contextual_off):>12} {change:>12}"

    header = f"  {'Metric':<34} {'contextual on':>12} {'off':>12} {'delta':>12}"
    print()
    print("Retrieval")
    print(header)
    for delta in report.retrieval_deltas:
        print(_row(delta))

    print()
    print("Ingestion cost / wall-clock per document")
    print(header)
    for delta in report.ingestion_deltas:
        print(_row(delta))

    for note in report.notes:
        print(f"\nNOTE: {note}")

    if report.significance is not None:
        print()
        _print_significance(report.significance, "contextual off", "contextual on")

    print(f"\nRuns: contextual-on={report.run_on_id}  contextual-off={report.run_off_id}")


def cmd_failures(args):
    """Read attributed questions directly from the experiment store."""
    store = ExperimentStore.from_environment()
    if store is None:
        print("ERROR: Experiment store is not configured (set EVAL_DATABASE_URL or mount database secrets).")
        sys.exit(1)
    rows = asyncio.run(store.questions_with_failure_label(args.label, args.limit))
    if not rows:
        print(f"No questions with supported label '{args.label}'.")
        return
    for row in rows:
        question = row["question"]
        labels = row.get("failure_labels") or []
        primary = row["primary_failure_stage"]
        # A queried label can be a genuinely-supported non-primary failure
        # (e.g. citation_error alongside a primary generation_drift), so show
        # the full label set, not just the primary one.
        label_display = primary if labels in ([], [primary]) else f"{primary} + {', '.join(l for l in labels if l != primary)}"
        print(f"{row['run_id']} {row['question_id']} [{label_display}]")
        print(f"  {question.get('question', '')}")
        print(f"  evidence: {json.dumps(row['evidence'], sort_keys=True)}")


def _print_significance(report, name_a: str, name_b: str) -> None:
    """Print paired significance results for one baseline/candidate pair."""
    print("\n" + "=" * 96)
    print(f"Significance: {name_b} vs {name_a}")
    print(f"Baseline is {name_a}; a positive delta means {name_b} scored higher.")
    print("=" * 96)

    if not report.metrics:
        print(
            "No paired per-question data available. Both runs must have been produced "
            "by a version that records per-question scores, and must share question IDs."
        )
        if report.skipped:
            print(f"Skipped: {', '.join(report.skipped)}")
        return

    header = f"{'Metric':<28}{'n':>5}  {'delta':>9}  {'95% CI':>21}  {'p':>8}  verdict"
    print(header)
    print("-" * 96)

    for m in sorted(report.metrics, key=lambda x: x.p_value):
        ci = f"[{m.ci_low:+.4f}, {m.ci_high:+.4f}]"
        if m.significant_corrected:
            verdict = "significant"
        elif m.significant:
            verdict = "nominal (fails BH)"
        else:
            verdict = "not significant"
        if m.underpowered:
            verdict += " · underpowered"
        print(
            f"{m.metric[:28]:<28}{m.n_paired:>5}  {m.delta:>+9.4f}  {ci:>21}  "
            f"{m.p_value:>8.4f}  {verdict}"
        )
        if m.discordant_b_better is not None:
            print(
                f"{'':<28}{'':>5}  McNemar: {m.discordant_b_better} questions improved, "
                f"{m.discordant_a_better} regressed, "
                f"{m.n_paired - m.discordant_b_better - m.discordant_a_better} unchanged"
            )

    print("-" * 96)
    print(
        f"{report.family_size} metrics tested at alpha={report.alpha}. Uncorrected, "
        f"pure noise would produce {report.expected_false_positives:.1f} 'significant' "
        f"movers on average ({report.any_spurious_probability:.0%} chance of at least one). "
        f"'significant' below survives Benjamini-Hochberg at the same alpha."
    )
    underpowered = [m for m in report.metrics if m.underpowered]
    if underpowered:
        print(
            f"{len(underpowered)} metric(s) below {UNDERPOWERED_N} paired questions — "
            "indicative only; intervals at this size understate true uncertainty."
        )
    if report.skipped:
        print(f"No per-question data (not tested): {', '.join(report.skipped)}")


def _compute_pareto_from_dicts(runs: list[dict]) -> list[dict]:
    """Compute Pareto frontier from run dictionaries.

    A run is Pareto-optimal if no other run dominates it
    (better in at least one objective without being worse in any).
    """
    points = []

    for run in runs:
        ws = run.get("weighted_score", {})
        objectives = ws.get("objectives", {})
        if not objectives:
            continue

        point = {
            "run_id": run["id"],
            "config_name": run["name"],
            "objectives": objectives.copy(),
            "is_dominated": False,
            "dominates": [],
        }
        points.append(point)

    # Determine dominance
    for i, p1 in enumerate(points):
        for j, p2 in enumerate(points):
            if i == j:
                continue

            # Check if p2 dominates p1
            better_in_one = False
            worse_in_one = False

            for obj in p1["objectives"]:
                v1 = p1["objectives"].get(obj, 0)
                v2 = p2["objectives"].get(obj, 0)

                if v2 > v1:
                    better_in_one = True
                elif v2 < v1:
                    worse_in_one = True

            if better_in_one and not worse_in_one:
                p1["is_dominated"] = True
                p2["dominates"].append(p1["run_id"])

    return points


def _print_pareto_analysis(points: list[dict]) -> None:
    """Print Pareto frontier analysis results."""
    if not points:
        print("No runs with objective data found.")
        return

    # Separate frontier from dominated points
    frontier = [p for p in points if not p["is_dominated"]]
    dominated = [p for p in points if p["is_dominated"]]

    print(f"\nPareto Frontier ({len(frontier)} runs):")
    print("-" * 40)

    for p in frontier:
        print(f"\n  {p['config_name']} [{p['run_id']}]")
        for obj, val in sorted(p["objectives"].items()):
            print(f"    {obj}: {val:.3f}")
        if p["dominates"]:
            print(f"    Dominates: {', '.join(p['dominates'])}")

    if dominated:
        print(f"\nDominated Runs ({len(dominated)}):")
        print("-" * 40)
        for p in dominated:
            print(f"  {p['config_name']} [{p['run_id']}] - dominated")

    # Recommendations
    if frontier:
        print("\nRecommendations:")
        print("-" * 40)

        # Find best for each objective
        all_objectives = set()
        for p in points:
            all_objectives.update(p["objectives"].keys())

        for obj in sorted(all_objectives):
            best_point = max(
                [p for p in points if obj in p["objectives"]],
                key=lambda p: p["objectives"].get(obj, 0),
                default=None,
            )
            if best_point:
                print(f"  Best {obj}: {best_point['config_name']} ({best_point['objectives'][obj]:.3f})")


def cmd_calibrate(args):
    """Calibrate the LLM judge against RAGBench TRACe ground-truth labels."""
    from evals.calibration import calibrate_judge, save_calibration
    from evals.datasets.ragbench import RAGBenchLoader, DEFAULT_SUBSETS

    print_config_banner(compact=True)
    print()

    subsets = (
        [s.strip() for s in args.subsets.split(",")] if args.subsets else DEFAULT_SUBSETS
    )
    console = Console()
    console.print(f"Judge calibration on RAGBench subsets: {subsets}")
    console.print(f"Samples: {args.samples}")
    console.rule()

    loader = RAGBenchLoader()
    items = loader.load_raw_items(
        subsets=subsets, split="test", max_samples=args.samples, seed=args.seed
    )
    if not items:
        console.print("[red]ERROR:[/red] No RAGBench items loaded.")
        sys.exit(1)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
    task = progress.add_task("Judging reference responses", total=len(items))

    def _on_progress(completed: int) -> None:
        progress.update(task, completed=completed)

    with progress:
        result = asyncio.run(calibrate_judge(items, progress_callback=_on_progress))

    path = save_calibration(result, Path(args.output))

    console.print()
    console.rule("Judge Calibration Results")
    console.print(f"Judge model: {result.judge_model}")
    console.print(f"Samples judged: {result.sample_count}")
    if result.adherence_accuracy is not None:
        console.print(
            f"Adherence agreement (judge faithfulness >= 0.5 vs ground truth): "
            f"{result.adherence_accuracy:.1%}"
        )
        console.print(f"Adherence RMSE: {result.adherence_rmse:.3f}")
    if result.relevance_rmse is not None:
        console.print(f"Context relevance RMSE: {result.relevance_rmse:.3f}")

    for label, disc in (
        ("answer_correctness", result.correctness_discrimination),
        ("answer_relevancy", result.relevancy_discrimination),
    ):
        if disc and disc.pair_count:
            console.print(
                f"{label} discrimination: {disc.accuracy:.1%} of {disc.pair_count} pairs "
                f"ranked correctly (matched {disc.mean_matched:.2f} vs "
                f"mismatched {disc.mean_mismatched:.2f}, separation {disc.separation:+.2f})"
            )

    console.print(f"Saved: {path}")
    console.print(
        "\n[dim]Lower RMSE / higher agreement = eval judge scores are more trustworthy. "
        "RAGBench paper baselines: RAGAS/TruLens RMSE ~0.25-0.35.\n"
        "Discrimination is a floor check, not a calibration: RAGBench has no ground "
        "truth for answer correctness or relevancy, so those two prompts are scored on "
        "whether they can separate a correct pairing from a deliberately wrong one. "
        "Accuracy well below 100% means the prompt is unreliable; near 100% only means "
        "it is not broken.[/dim]"
    )


def cmd_cache(args):
    """Manage dataset cache."""
    action = getattr(args, "cache_action", None)
    if action == "clear":
        what = getattr(args, "what", "datasets")
        if what in ("datasets", "all"):
            print(f"Cleared {clear_cache()} cached dataset(s).")
        if what in ("responses", "all"):
            print(f"Cleared {clear_response_cache(DEFAULT_CACHE_DIR)} cached response(s).")
    elif action == "status":
        if CACHE_DIR.exists():
            files = list(CACHE_DIR.glob("*.json"))
            total_bytes = sum(f.stat().st_size for f in files)
            print(f"Dataset cache: {CACHE_DIR}")
            print(f"  Files: {len(files)}")
            print(f"  Size:  {total_bytes / 1024:.0f} KB")
        else:
            print("Dataset cache: none")

        if DEFAULT_CACHE_DIR.exists():
            print(f"Response cache: {DEFAULT_CACHE_DIR}")
            for namespace in sorted(p for p in DEFAULT_CACHE_DIR.iterdir() if p.is_dir()):
                entries = list(namespace.glob("*.json"))
                size = sum(f.stat().st_size for f in entries)
                print(f"  {namespace.name}: {len(entries)} entries, {size / 1024:.0f} KB")
        else:
            print("Response cache: none")
    else:
        print("Usage: cache {clear,status}")
        sys.exit(1)


def print_run_summary(run: EvalRun):
    """Print a summary of an evaluation run."""
    print("\n" + "=" * 60)
    print(f"Evaluation Complete: {run.name}")
    print("=" * 60)
    print(f"Run ID: {run.id}")
    print(f"Duration: {run.duration_seconds:.1f}s" if run.duration_seconds else "")
    print(f"Questions: {run.question_count} ({run.error_count} errors)")
    print(f"Success rate: {run.success_rate:.1%}")

    warning = run.metadata.get("judge_independence_warning")
    if warning:
        print(f"\nWARNING: {warning}")

    cache_stats = run.metadata.get("cache")
    if cache_stats and cache_stats.get("hits"):
        print(
            f"Cache: {cache_stats['hits']} hits, {cache_stats['misses']} misses "
            f"(judge={cache_stats['judge']}, query={cache_stats['query']})"
        )

    if run.scorecard and run.scorecard.notes:
        print("\n" + "-" * 40)
        for note in run.scorecard.notes:
            print(f"NOTE: {note}")

    if run.scorecard:
        print("\n" + "-" * 40)
        print("Metrics by Group:")
        for group, metrics in run.scorecard.by_group.items():
            print(f"\n  {group.value.upper()}:")
            for metric in metrics:
                if metric.value is None:
                    note = metric.details.get("note", "not applicable")
                    print(f"    {metric.name}: n/a ({note})")
                else:
                    print(f"    {metric.name}: {metric.value:.3f}")

    if run.weighted_score:
        print("\n" + "-" * 40)
        print(f"WEIGHTED SCORE: {run.weighted_score.score:.3f}")
        print("\nObjective contributions:")
        for obj, contrib in sorted(
            run.weighted_score.contributions.items(),
            key=lambda x: -x[1]
        ):
            weight = run.weighted_score.weights.get(obj, 0)
            value = run.weighted_score.objectives.get(obj, 0)
            print(f"  {obj}: {value:.3f} * {weight:.2f} = {contrib:.3f}")


if __name__ == "__main__":
    main()
