"""Statistical significance testing for run comparison.

A raw delta between two runs says nothing about whether the change is real. This
module turns per-question scores into interval estimates so a comparison reports
*how confident* it is, not just which number is bigger:

- Paired bootstrap confidence intervals over per-question deltas (works for both
  continuous judge scores and binary hit/miss metrics).
- McNemar's exact test for binary metrics, reporting the discordant pairs so the
  user sees how many questions actually flipped and in which direction.
- An underpowered flag below `UNDERPOWERED_N`, because normal-approximation-scale
  intervals substantially understate uncertainty on small question sets.
- Benjamini-Hochberg correction, because scanning ~20 metrics uncorrected gives
  roughly a 64% chance of at least one spurious "significant" mover.

Per-question scores come from `MetricResult.details["per_question"]`, written by
`BaseMetric.compute_batch`. Runs produced before that existed have no per-question
data; comparisons involving them return no statistics rather than fabricating any.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Resamples for the paired bootstrap. 10k gives ~±0.005 Monte-Carlo error on a
# 95% interval bound, well below the sampling error it is estimating.
DEFAULT_BOOTSTRAP_SAMPLES = 10_000

# Below this many paired questions a comparison is labelled indicative only.
UNDERPOWERED_N = 100

# Family-wise error rate / false-discovery rate target.
DEFAULT_ALPHA = 0.05

# Fixed so the same two runs always compare identically. A comparison whose
# verdict changes between two invocations on unchanged inputs is worse than no
# comparison at all.
BOOTSTRAP_SEED = 20260802


@dataclass
class MetricComparison:
    """Paired comparison of one metric between two runs."""

    metric: str
    n_paired: int
    mean_a: float
    mean_b: float
    delta: float                    # b - a
    ci_low: float
    ci_high: float
    p_value: float                  # bootstrap two-sided, or McNemar exact for binary
    test: str                       # "paired_bootstrap" | "mcnemar_exact"
    significant: bool               # CI excludes zero (uncorrected)
    underpowered: bool
    significant_corrected: bool | None = None   # after Benjamini-Hochberg
    # Binary metrics only: how many questions flipped, and which way
    discordant_b_better: int | None = None
    discordant_a_better: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "n_paired": self.n_paired,
            "mean_a": self.mean_a,
            "mean_b": self.mean_b,
            "delta": self.delta,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "p_value": self.p_value,
            "test": self.test,
            "significant": self.significant,
            "significant_corrected": self.significant_corrected,
            "underpowered": self.underpowered,
            "discordant_b_better": self.discordant_b_better,
            "discordant_a_better": self.discordant_a_better,
        }


@dataclass
class ComparisonReport:
    """All per-metric comparisons between two runs, plus the family-level context."""

    run_a: str
    run_b: str
    metrics: list[MetricComparison] = field(default_factory=list)
    alpha: float = DEFAULT_ALPHA
    # Metrics present in both runs but with no per-question data to pair on
    skipped: list[str] = field(default_factory=list)

    @property
    def family_size(self) -> int:
        return len(self.metrics)

    @property
    def expected_false_positives(self) -> float:
        """Uncorrected: how many "significant" movers pure noise would produce."""
        return self.family_size * self.alpha

    @property
    def any_spurious_probability(self) -> float:
        """P(at least one uncorrected false positive) if nothing really changed."""
        if not self.metrics:
            return 0.0
        return 1.0 - (1.0 - self.alpha) ** self.family_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_a": self.run_a,
            "run_b": self.run_b,
            "alpha": self.alpha,
            "family_size": self.family_size,
            "expected_false_positives": round(self.expected_false_positives, 2),
            "any_spurious_probability": round(self.any_spurious_probability, 4),
            "underpowered_threshold": UNDERPOWERED_N,
            "metrics": [m.to_dict() for m in self.metrics],
            "skipped": self.skipped,
        }


def paired_bootstrap(
    deltas: list[float] | np.ndarray,
    n_resamples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    alpha: float = DEFAULT_ALPHA,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, float]:
    """Percentile bootstrap CI and two-sided p-value for a mean paired delta.

    Returns (ci_low, ci_high, p_value). The p-value is the standard bootstrap
    two-sided tail: twice the smaller mass on either side of zero.
    """
    arr = np.asarray(deltas, dtype=float)
    n = arr.size
    if n == 0:
        return (0.0, 0.0, 1.0)
    if n == 1:
        return (float(arr[0]), float(arr[0]), 1.0)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_resamples, n))
    means = arr[idx].mean(axis=1)

    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))

    # Two-sided tail probability around zero, floored at 1/n_resamples so a p of
    # exactly 0 (which the bootstrap cannot establish) is never reported.
    frac_below = float((means <= 0).mean())
    frac_above = float((means >= 0).mean())
    p = min(1.0, 2 * min(frac_below, frac_above))
    p = max(p, 1.0 / n_resamples)

    return (lo, hi, p)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for discordant counts b and c.

    b and c are the two kinds of disagreement (a improved, b improved). Under the
    null the split is Binomial(b + c, 0.5). Exact rather than chi-square because
    discordant counts on a 100-question eval are routinely below 25.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # P(X <= k) for X ~ Binom(n, 0.5)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def benjamini_hochberg(p_values: list[float], alpha: float = DEFAULT_ALPHA) -> list[bool]:
    """Benjamini-Hochberg step-up procedure. Returns per-input rejection flags."""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    rejected = [False] * m
    max_rank = 0
    for rank, i in enumerate(order, start=1):
        if p_values[i] <= alpha * rank / m:
            max_rank = rank
    for rank, i in enumerate(order, start=1):
        if rank <= max_rank:
            rejected[i] = True
    return rejected


def _is_binary(values: list[float]) -> bool:
    return all(v in (0.0, 1.0) for v in values)


def extract_per_question(run: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Pull {metric_name: {question_id: score}} out of a saved run dict."""
    scorecard = run.get("scorecard") or {}
    out: dict[str, dict[str, float]] = {}
    for metric in scorecard.get("metrics", []):
        details = metric.get("details") or {}
        per_q = details.get("per_question")
        if isinstance(per_q, dict) and per_q:
            out[metric["name"]] = {
                qid: float(v) for qid, v in per_q.items() if v is not None
            }
    return out


def compare_runs(
    run_a: dict[str, Any],
    run_b: dict[str, Any],
    alpha: float = DEFAULT_ALPHA,
    n_resamples: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> ComparisonReport:
    """Paired significance comparison of run_b against run_a.

    Only questions present in both runs for a given metric are paired; a question
    that errored in one run is dropped from that metric rather than scored zero.
    """
    per_q_a = extract_per_question(run_a)
    per_q_b = extract_per_question(run_b)

    report = ComparisonReport(
        run_a=run_a.get("id", "?"),
        run_b=run_b.get("id", "?"),
        alpha=alpha,
    )

    shared_metrics = sorted(set(per_q_a) & set(per_q_b))
    # Metrics in both scorecards but lacking per-question data (e.g. performance
    # aggregates, or runs saved before per-question capture existed)
    scorecard_names_a = {m["name"] for m in (run_a.get("scorecard") or {}).get("metrics", [])}
    scorecard_names_b = {m["name"] for m in (run_b.get("scorecard") or {}).get("metrics", [])}
    report.skipped = sorted((scorecard_names_a & scorecard_names_b) - set(shared_metrics))

    for name in shared_metrics:
        a_scores = per_q_a[name]
        b_scores = per_q_b[name]
        shared_qids = sorted(set(a_scores) & set(b_scores))
        if len(shared_qids) < 2:
            report.skipped.append(name)
            continue

        a_vals = [a_scores[q] for q in shared_qids]
        b_vals = [b_scores[q] for q in shared_qids]
        deltas = [b - a for a, b in zip(a_vals, b_vals)]

        ci_low, ci_high, p_boot = paired_bootstrap(
            deltas, n_resamples=n_resamples, alpha=alpha
        )

        binary = _is_binary(a_vals) and _is_binary(b_vals)
        disc_b_better = disc_a_better = None
        if binary:
            disc_b_better = sum(1 for a, b in zip(a_vals, b_vals) if b > a)
            disc_a_better = sum(1 for a, b in zip(a_vals, b_vals) if a > b)
            p_value = mcnemar_exact(disc_b_better, disc_a_better)
            test = "mcnemar_exact"
        else:
            p_value = p_boot
            test = "paired_bootstrap"

        n = len(shared_qids)
        report.metrics.append(
            MetricComparison(
                metric=name,
                n_paired=n,
                mean_a=sum(a_vals) / n,
                mean_b=sum(b_vals) / n,
                delta=sum(deltas) / n,
                ci_low=ci_low,
                ci_high=ci_high,
                p_value=p_value,
                test=test,
                significant=(ci_low > 0 or ci_high < 0),
                underpowered=n < UNDERPOWERED_N,
                discordant_b_better=disc_b_better,
                discordant_a_better=disc_a_better,
            )
        )

    corrected = benjamini_hochberg([m.p_value for m in report.metrics], alpha=alpha)
    for metric, flag in zip(report.metrics, corrected):
        metric.significant_corrected = flag

    report.skipped = sorted(set(report.skipped))
    return report
