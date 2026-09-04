"""The retrieval funnel: where in the pipeline the answer was lost.

Every ranking metric already scores each pipeline stage separately — the
per-leg scores are computed in `metrics/retrieval.py` and left in
`MetricResult.details["stage_scores"]`, keyed `recall_at_5{leg=bm25}`. This
module lifts them into the one artifact a tuning decision actually needs.

The funnel answers a single question: **of the questions whose evidence the
system failed to put in front of the model, where was it lost?** There are only
two answers, and they point at opposite halves of the system:

- *Never retrieved* — the evidence was not in the candidate list at all, so no
  reranker could have saved it. Work on ingestion: chunking, embeddings,
  the BM25/vector balance, query rewriting.
- *Retrieved, then dropped* — the candidate list contained the evidence and the
  reranker pushed it below the cutoff. Work on the reranker, or on `final_top_n`.

Everything else in this module is in service of splitting that one number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Ordered as the query pipeline runs them. bm25 and vector are the two retrieval
# legs, fused by RRF, then reranked by the cross-encoder.
FUNNEL_STAGES = ("bm25", "vector", "fusion", "rerank")

# The stage score whose loss the funnel is built around. Recall is the right
# headline for a funnel: it asks "is the evidence here at all", which is exactly
# the question each successive stage can only answer worse than the last (rank
# metrics like nDCG can legitimately improve at rerank while recall falls).
PRIMARY_MEASURE = "recall_at_5"

# Also carried per stage, for reading rank quality alongside presence.
SECONDARY_MEASURES = ("ndcg_at_10", "mrr")

_LEG_KEY = re.compile(r"^(?P<metric>[^{]+)\{leg=(?P<leg>[^}]+)\}$")


@dataclass
class FunnelStage:
    """One pipeline stage's scores, and what it cost relative to the previous."""

    name: str
    recall: float | None = None
    secondary: dict[str, float] = field(default_factory=dict)
    questions_scored: int = 0
    # Recall lost relative to the preceding stage in the funnel. Negative means
    # the stage recovered evidence — only possible where a stage introduces
    # candidates the previous one did not have (fusion over a single leg).
    delta: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "recall": self.recall,
            "secondary": self.secondary,
            "questions_scored": self.questions_scored,
            "delta": self.delta,
        }


@dataclass
class RetrievalFunnel:
    """Stage-by-stage recall, and the diagnosis that falls out of it."""

    stages: list[FunnelStage] = field(default_factory=list)
    # Recall of the pre-rerank candidate list: the ceiling the reranker works
    # under. Nothing downstream can exceed it.
    ceiling: float | None = None
    # Recall of what the model actually saw.
    final: float | None = None
    # The two halves of total loss. They sum to 1 - final.
    lost_before_candidates: float | None = None
    lost_in_rerank: float | None = None
    # "ingestion" | "rerank" | None when there is nothing to fix or nothing measured.
    bottleneck: str | None = None
    diagnosis: str | None = None
    # Per-leg comparison: what BM25 and vector each contribute, and whether
    # fusing them beat the better one on its own.
    leg_recall: dict[str, float] = field(default_factory=dict)
    fusion_lift: float | None = None
    note: str | None = None

    @property
    def measured(self) -> bool:
        return self.final is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": [s.to_dict() for s in self.stages],
            "ceiling": self.ceiling,
            "final": self.final,
            "lost_before_candidates": self.lost_before_candidates,
            "lost_in_rerank": self.lost_in_rerank,
            "bottleneck": self.bottleneck,
            "diagnosis": self.diagnosis,
            "leg_recall": self.leg_recall,
            "fusion_lift": self.fusion_lift,
            "note": self.note,
        }


def _metric_dicts(scorecard: Any) -> list[dict[str, Any]]:
    """Accept either a Scorecard dataclass or its serialized dict form."""
    if scorecard is None:
        return []
    metrics = scorecard.get("metrics", []) if isinstance(scorecard, dict) else scorecard.metrics
    out: list[dict[str, Any]] = []
    for m in metrics:
        if isinstance(m, dict):
            out.append(m)
        else:
            out.append({"name": m.name, "value": m.value, "details": m.details or {}})
    return out


def _stage_table(metrics: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Invert `details["stage_scores"]` into {stage: {metric: value}}."""
    table: dict[str, dict[str, float]] = {}
    for metric in metrics:
        stage_scores = (metric.get("details") or {}).get("stage_scores") or {}
        for key, value in stage_scores.items():
            match = _LEG_KEY.match(key)
            if not match or value is None:
                continue
            table.setdefault(match["leg"], {})[match["metric"]] = value
    return table


def _stage_counts(metrics: list[dict[str, Any]]) -> dict[str, int]:
    """How many questions each stage's primary measure was defined on."""
    counts: dict[str, int] = {}
    for metric in metrics:
        if metric.get("name") != PRIMARY_MEASURE:
            continue
        per_question = (metric.get("details") or {}).get("stage_per_question") or {}
        for stage, scores in per_question.items():
            counts[stage] = len(scores)
    return counts


def build_funnel(scorecard: Any) -> RetrievalFunnel:
    """Derive the retrieval funnel from a computed (or saved) scorecard."""
    metrics = _metric_dicts(scorecard)
    if not metrics:
        return RetrievalFunnel(note="No metrics in this run")

    table = _stage_table(metrics)
    if not table:
        return RetrievalFunnel(
            note=(
                "No per-stage retrieval scores. Either this was a generation-tier "
                "run, or the questions carry no resolvable gold evidence — see "
                "`ground_truth` in the retrieval metric details."
            )
        )

    counts = _stage_counts(metrics)
    funnel = RetrievalFunnel()

    for name in FUNNEL_STAGES:
        scores = table.get(name)
        if scores is None:
            continue
        funnel.stages.append(
            FunnelStage(
                name=name,
                recall=scores.get(PRIMARY_MEASURE),
                secondary={k: scores[k] for k in SECONDARY_MEASURES if k in scores},
                questions_scored=counts.get(name, 0),
            )
        )

    funnel.leg_recall = {
        leg: table[leg][PRIMARY_MEASURE]
        for leg in ("bm25", "vector")
        if leg in table and PRIMARY_MEASURE in table[leg]
    }

    # bm25 and vector run in parallel over the same query, so neither is the
    # other's predecessor and neither carries a delta. Fusion's predecessor is
    # the better leg (fusing can only be judged against the best thing it had to
    # work with); rerank's is the candidate list it was handed.
    by_name = {stage.name: stage for stage in funnel.stages}
    best_leg = max(funnel.leg_recall.values(), default=None)
    if (fusion := by_name.get("fusion")) and fusion.recall is not None and best_leg is not None:
        fusion.delta = fusion.recall - best_leg
    candidate_recall = by_name["fusion"].recall if "fusion" in by_name else best_leg
    if (rerank := by_name.get("rerank")) and rerank.recall is not None and candidate_recall is not None:
        rerank.delta = rerank.recall - candidate_recall

    lift = next((m.get("value") for m in metrics if m.get("name") == "fusion_lift"), None)
    funnel.fusion_lift = lift

    # The ceiling is the candidate list handed to the reranker: fusion where the
    # legs were fused, otherwise the better single leg. The final is the last
    # stage measured at all. With no reranker in the pipeline they are the same
    # number, and lost_in_rerank is correctly 0.
    ceiling_name = "fusion" if candidate_recall is not None and "fusion" in by_name else (
        max(funnel.leg_recall, key=funnel.leg_recall.__getitem__) if funnel.leg_recall else None
    )
    final_stage = next((s for s in reversed(funnel.stages) if s.recall is not None), None)

    if candidate_recall is None or final_stage is None:
        funnel.note = "No stage produced a defined recall score"
        return funnel

    funnel.ceiling = candidate_recall
    funnel.final = final_stage.recall
    funnel.lost_before_candidates = 1.0 - funnel.ceiling
    # Clamped at zero: reranking cannot add evidence the candidate list lacked,
    # so a negative here is sampling noise between stage populations, not a gain.
    funnel.lost_in_rerank = max(0.0, funnel.ceiling - funnel.final)

    funnel.bottleneck, funnel.diagnosis = _diagnose(
        funnel.lost_before_candidates, funnel.lost_in_rerank, ceiling_name or "candidates"
    )
    return funnel


# Below this, a loss is not worth sending someone to go and work on.
_ACTIONABLE_LOSS = 0.05


def _diagnose(lost_before: float, lost_in_rerank: float, ceiling_stage: str) -> tuple[str | None, str]:
    total = lost_before + lost_in_rerank
    if total < _ACTIONABLE_LOSS:
        return None, (
            f"Retrieval finds the evidence for {(1 - total) * 100:.0f}% of questions. "
            "No stage is losing enough to be worth tuning — move to generation quality, "
            "or make the question set harder."
        )
    if lost_in_rerank > lost_before:
        return "rerank", (
            f"The candidate list contains the evidence {(1 - lost_before) * 100:.0f}% of the "
            f"time, but only {(1 - lost_before - lost_in_rerank) * 100:.0f}% survives reranking. "
            f"The reranker is the bottleneck: it drops evidence it was handed "
            f"({lost_in_rerank * 100:.0f} points). Try a larger `final_top_n`, a different "
            "cross-encoder, or turn reranking off and compare."
        )
    return "ingestion", (
        f"{lost_before * 100:.0f}% of questions never get their evidence into the candidate "
        f"list ({ceiling_stage}), so reranking cannot help them. The loss is upstream: "
        "chunking, embeddings, the BM25/vector balance, or retrieval depth. Reranking "
        f"costs a further {lost_in_rerank * 100:.0f} points on top."
    )
