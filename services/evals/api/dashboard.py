"""Map a saved run to the handful of numbers the dashboard leads with.

Retrieval is reported as the funnel — the recall of the candidate list and the
recall of what the model actually saw — rather than as a single "relevance"
score. The previous composite averaged `recall_at_5` with `mrr`: a set metric
and a rank metric, in different units, whose mean is not a quantity. It could
not go up or down for a reason anyone could act on, which is the only thing a
headline retrieval number is for.
"""

from api.schemas import DashboardMetrics
from evals.funnel import build_funnel


def compute_dashboard_metrics(
    scorecard: dict | None, tier: str = "", funnel: dict | None = None
) -> DashboardMetrics | None:
    """Derive dashboard metrics from a raw scorecard dict.

    Args:
        scorecard: The "scorecard" dict as stored in the JSON run file.
        tier: "generation" or "end_to_end". Generation-tier runs retrieve
            nothing, so the funnel is absent rather than zero.
        funnel: The run's saved "retrieval_funnel" dict, when it has one. Runs
            saved before the funnel existed are re-derived from the scorecard.

    Returns:
        DashboardMetrics or None if no scorecard data.
    """
    if not scorecard:
        return None

    metrics_list = scorecard.get("metrics", [])
    if not metrics_list:
        return None

    lookup: dict[str, float] = {m["name"]: m["value"] for m in metrics_list}

    retrieval_ceiling = retrieval_final = None
    bottleneck = None
    if tier != "generation":
        # Re-deriving is cheap and keeps runs saved before the funnel existed
        # readable, rather than showing them as having no retrieval at all.
        resolved = funnel if funnel is not None else build_funnel(scorecard).to_dict()
        retrieval_ceiling = resolved.get("ceiling")
        retrieval_final = resolved.get("final")
        bottleneck = resolved.get("bottleneck")

    latency_p50 = lookup.get("latency_p50_ms")
    latency_p95 = lookup.get("latency_p95_ms")
    latency_avg = lookup.get("latency_avg_ms")

    cost_details: dict = {}
    for m in metrics_list:
        if m["name"] == "cost_per_query":
            cost_details = m.get("details") or {}
            break

    return DashboardMetrics(
        retrieval_ceiling=retrieval_ceiling,
        retrieval_final=retrieval_final,
        retrieval_bottleneck=bottleneck,
        faithfulness=lookup.get("faithfulness"),
        claim_groundedness=lookup.get("claim_groundedness"),
        answer_correctness=lookup.get("answer_correctness"),
        answer_completeness=lookup.get("answer_completeness"),
        answer_relevance=lookup.get("answer_relevancy"),
        latency_p50_seconds=latency_p50 / 1000 if latency_p50 is not None else None,
        latency_p95_seconds=latency_p95 / 1000 if latency_p95 is not None else None,
        latency_avg_seconds=latency_avg / 1000 if latency_avg is not None else None,
        avg_cost_usd=cost_details.get("avg_cost_usd"),
        total_cost_usd=cost_details.get("total_cost_usd"),
        total_prompt_tokens=cost_details.get("total_prompt_tokens"),
        total_completion_tokens=cost_details.get("total_completion_tokens"),
        cost_model=cost_details.get("model"),
    )
