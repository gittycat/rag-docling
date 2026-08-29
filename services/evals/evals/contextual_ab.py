"""Paired contextual-retrieval A/B: one question set, one corpus, both settings.

Phase 4 shipped only half of its delta protocols. `--retrieval-only` with
`--retrieval-source` covers per-source attribution; there was no paired
contextual-on/off runner and no automatic delta computation, so the cost of
contextual retrieval could not be weighed against what it buys.

This runs the same questions twice — contextual retrieval on, then off — over a
freshly ingested corpus each time, and reports the retrieval deltas alongside
the ingestion cost and wall-clock deltas per document. Significance reuses the
existing paired-bootstrap path in `evals.stats`; there is no second statistics
implementation here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from evals.config import EvalConfig, EvalTier
from evals.stats import DEFAULT_ALPHA, DEFAULT_BOOTSTRAP_SAMPLES, compare_runs

logger = logging.getLogger(__name__)

# Ingestion is the whole point of the comparison: contextual retrieval costs an
# LLM call per chunk at ingest time, and that is what the retrieval gain has to
# be weighed against.
INGESTION_METRICS = (
    "ingestion_cost_per_document",
    "ingestion_latency_per_document",
)


@dataclass
class ContextualDelta:
    """One metric's before/after and the difference, `on` minus `off`."""

    name: str
    contextual_on: float | None
    contextual_off: float | None

    @property
    def delta(self) -> float | None:
        if self.contextual_on is None or self.contextual_off is None:
            return None
        return self.contextual_on - self.contextual_off


@dataclass
class ContextualABReport:
    run_on_id: str
    run_off_id: str
    retrieval_deltas: list[ContextualDelta] = field(default_factory=list)
    ingestion_deltas: list[ContextualDelta] = field(default_factory=list)
    significance: Any = None
    notes: list[str] = field(default_factory=list)


def _metric_values(run: dict[str, Any]) -> dict[str, float | None]:
    scorecard = run.get("scorecard") or {}
    return {metric["name"]: metric.get("value") for metric in scorecard.get("metrics", [])}


def _retrieval_metric_names(run: dict[str, Any]) -> set[str]:
    scorecard = run.get("scorecard") or {}
    return {
        metric["name"]
        for metric in scorecard.get("metrics", [])
        if metric.get("group") == "retrieval"
    }


def build_report(
    run_on: dict[str, Any],
    run_off: dict[str, Any],
    *,
    alpha: float = DEFAULT_ALPHA,
    n_resamples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> ContextualABReport:
    """Compose the delta report from two completed runs.

    Separated from the orchestration below so it can be tested without a server.
    """
    on_values = _metric_values(run_on)
    off_values = _metric_values(run_off)

    report = ContextualABReport(
        run_on_id=run_on.get("id", "?"),
        run_off_id=run_off.get("id", "?"),
    )

    for name in sorted(_retrieval_metric_names(run_on) | _retrieval_metric_names(run_off)):
        report.retrieval_deltas.append(
            ContextualDelta(name, on_values.get(name), off_values.get(name))
        )

    for name in INGESTION_METRICS:
        if name in on_values or name in off_values:
            report.ingestion_deltas.append(
                ContextualDelta(name, on_values.get(name), off_values.get(name))
            )

    if not report.ingestion_deltas:
        # Saying so is the point: without them the retrieval gain has no price
        # tag, and the comparison cannot answer the question it exists to answer.
        report.notes.append(
            "No ingestion cost/latency metrics in either run — the retrieval "
            "delta cannot be weighed against what contextual retrieval costs. "
            "Run at the end_to_end tier so ingestion is measured."
        )

    undefined = [d.name for d in report.retrieval_deltas if d.delta is None]
    if undefined:
        report.notes.append(
            "Undefined in at least one run (no delta computed): "
            + ", ".join(undefined)
        )

    # One statistics implementation, not two.
    report.significance = compare_runs(
        run_off, run_on, alpha=alpha, n_resamples=n_resamples
    )
    return report


async def run_contextual_ab(
    config: EvalConfig,
    *,
    progress_callback: Any | None = None,
    alpha: float = DEFAULT_ALPHA,
    n_resamples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> ContextualABReport:
    """Run the same evaluation with contextual retrieval on and off.

    The server setting is restored afterwards even if a run raises: leaving a
    benchmark toggle flipped would silently change every later run.
    """
    from evals.runner import EvaluationRunner, RAGClient

    if config.tier != EvalTier.END_TO_END:
        raise ValueError(
            "Contextual A/B requires the end_to_end tier: the comparison is "
            "about ingestion behaviour, which no other tier exercises."
        )

    probe = RAGClient(config.rag_server_url)
    try:
        original = (await probe.get_settings()).get("contextual_retrieval_enabled")
    finally:
        await probe.close()

    runs: dict[bool, dict[str, Any]] = {}
    try:
        for enabled in (True, False):
            client = RAGClient(config.rag_server_url)
            try:
                await client.set_contextual_retrieval(enabled)
            finally:
                await client.close()
            logger.info("[CONTEXTUAL_AB] contextual_retrieval_enabled=%s", enabled)

            runner = EvaluationRunner(config)
            try:
                run = await runner.run(progress_callback=progress_callback)
                # Same serialization the saved run files use, so the comparison
                # reads exactly what `evals compare` would read off disk.
                runs[enabled] = runner._run_to_dict(run)
            finally:
                await runner.close()
    finally:
        if original is not None:
            client = RAGClient(config.rag_server_url)
            try:
                await client.set_contextual_retrieval(bool(original))
                logger.info("[CONTEXTUAL_AB] restored contextual_retrieval_enabled=%s", original)
            except Exception as exc:  # pragma: no cover - best effort restore
                logger.error("[CONTEXTUAL_AB] Could not restore the original setting: %s", exc)
            finally:
                await client.close()

    return build_report(runs[True], runs[False], alpha=alpha, n_resamples=n_resamples)
