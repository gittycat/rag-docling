"""Judge calibration against RAGBench TRACe ground-truth annotations.

RAGBench ships human-verified (GPT-4-annotated) labels for each
(question, documents, response) triple:
- adherence_score (bool): is the response fully grounded in the documents
- relevance_score (float 0-1): fraction of context relevant to the question

This module runs our LLM judge on the *reference* responses and compares its
scores to those labels, following the paper's methodology (RMSE for continuous
scores, accuracy/AUROC-style agreement for adherence). It answers: "how much
can we trust the judge scores reported by our eval runs?"
"""

import asyncio
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from evals.config import JudgeConfig, resolve_judge_config
from evals.judges.llm_judge import LLMJudge

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/calibration")


@dataclass
class DiscriminationResult:
    """How well a judge prompt separates a known-good pairing from a known-bad one.

    RAGBench carries no ground truth for answer correctness or answer relevancy, so
    those two prompts had no evidence of agreeing with anything. What *is* known for
    free is that an item's reference response is correct for its own question and
    wrong for a different item's question. A judge that cannot separate those two
    cases is not measuring what its name claims.

    This is a floor, not a calibration: passing it says the prompt is not broken,
    not that its mid-range scores track human judgement.
    """

    pair_count: int
    mean_matched: float | None
    mean_mismatched: float | None
    accuracy: float | None       # fraction of pairs scored matched > mismatched
    separation: float | None     # mean_matched - mean_mismatched

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_count": self.pair_count,
            "mean_matched": self.mean_matched,
            "mean_mismatched": self.mean_mismatched,
            "accuracy": self.accuracy,
            "separation": self.separation,
        }


@dataclass
class CalibrationResult:
    """Aggregated judge-vs-ground-truth agreement."""

    sample_count: int
    adherence_accuracy: float | None
    adherence_rmse: float | None
    relevance_rmse: float | None
    judge_model: str
    correctness_discrimination: DiscriminationResult | None = None
    relevancy_discrimination: DiscriminationResult | None = None
    per_item: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _rmse(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    return math.sqrt(sum((a - b) ** 2 for a, b in pairs) / len(pairs))


def _summarize_discrimination(
    scores: list[tuple[float, float]],
) -> DiscriminationResult:
    """Aggregate (matched_score, mismatched_score) pairs."""
    if not scores:
        return DiscriminationResult(0, None, None, None, None)
    matched = [m for m, _ in scores]
    mismatched = [x for _, x in scores]
    mean_m = sum(matched) / len(matched)
    mean_x = sum(mismatched) / len(mismatched)
    correct = sum(1 for m, x in scores if m > x)
    return DiscriminationResult(
        pair_count=len(scores),
        mean_matched=mean_m,
        mean_mismatched=mean_x,
        accuracy=correct / len(scores),
        separation=mean_m - mean_x,
    )


async def calibrate_judge(
    items: list[dict[str, Any]],
    judge_config: JudgeConfig | None = None,
    concurrency: int = 10,
    progress_callback: Any | None = None,
) -> CalibrationResult:
    """Score RAGBench reference responses with the judge and compare to labels.

    Args:
        items: Raw RAGBench items (from RAGBenchLoader.load_raw_items)
        judge_config: Judge configuration (default from models config)
        concurrency: Max concurrent judge calls
        progress_callback: Called with (completed_count) after each item
    """
    judge = LLMJudge(judge_config or resolve_judge_config())
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    dropped_judge_failures = 0

    async def _judge_one(item: dict[str, Any]) -> dict[str, Any] | None:
        nonlocal completed, dropped_judge_failures
        async with sem:
            try:
                question = item.get("question", "")
                response = item.get("response", "")
                documents = item.get("documents") or []
                context = "\n\n".join(
                    d if isinstance(d, str) else str(d) for d in documents
                )
                if not (question and response and context):
                    return None

                faith_task = judge.evaluate_faithfulness(answer=response, context=context)
                rel_task = judge.evaluate_context_relevance(question=question, context=context)
                # return_exceptions so a failing judge call doesn't orphan its sibling
                # task; either failure drops the whole item rather than scoring it 0.0,
                # which would make the judge look wrong about ground truth it never saw.
                faith, rel = await asyncio.gather(faith_task, rel_task, return_exceptions=True)
                for outcome in (faith, rel):
                    if isinstance(outcome, BaseException):
                        dropped_judge_failures += 1
                        logger.warning(
                            f"[CALIBRATION] Judge failed for item {item.get('id')}: {outcome}"
                        )
                        return None

                return {
                    "id": item.get("id"),
                    "subset": item.get("subset"),
                    "judge_faithfulness": faith.score,
                    "judge_context_relevance": rel.score,
                    "gt_adherence": item.get("adherence_score"),
                    "gt_relevance": item.get("relevance_score"),
                    "gt_utilization": item.get("utilization_score"),
                    "gt_completeness": item.get("completeness_score"),
                }
            except Exception as e:
                logger.warning(f"[CALIBRATION] Failed for item {item.get('id')}: {e}")
                return None
            finally:
                completed += 1
                if progress_callback:
                    progress_callback(completed)

    results = [r for r in await asyncio.gather(*(_judge_one(i) for i in items)) if r]

    # Adherence: ground truth is boolean; judge faithfulness thresholded at 0.5
    adherence_pairs = [
        (r["judge_faithfulness"], 1.0 if r["gt_adherence"] else 0.0)
        for r in results
        if r["gt_adherence"] is not None
    ]
    adherence_accuracy = None
    if adherence_pairs:
        correct = sum(1 for judged, gt in adherence_pairs if (judged >= 0.5) == (gt >= 0.5))
        adherence_accuracy = correct / len(adherence_pairs)

    relevance_pairs = [
        (r["judge_context_relevance"], r["gt_relevance"])
        for r in results
        if r["gt_relevance"] is not None
    ]

    correctness, relevancy, discrimination_dropped = await _discrimination_checks(
        judge, items, concurrency=concurrency
    )

    return CalibrationResult(
        sample_count=len(results),
        adherence_accuracy=adherence_accuracy,
        adherence_rmse=_rmse(adherence_pairs),
        relevance_rmse=_rmse(relevance_pairs),
        judge_model=judge.config.model,
        correctness_discrimination=correctness,
        relevancy_discrimination=relevancy,
        per_item=results,
        metadata={
            "adherence_sample_count": len(adherence_pairs),
            "relevance_sample_count": len(relevance_pairs),
            # Surfaced so a calibration run over a flaky judge is visibly thin
            # rather than quietly computed over whatever happened to succeed.
            "items_requested": len(items),
            "dropped_judge_failures": dropped_judge_failures,
            "discrimination_dropped": discrimination_dropped,
        },
    )


async def _discrimination_checks(
    judge: LLMJudge,
    items: list[dict[str, Any]],
    concurrency: int = 10,
) -> tuple[DiscriminationResult, DiscriminationResult, int]:
    """Run the matched-vs-mismatched checks for correctness and relevancy.

    Item i is paired with item i+1 (wrapping), giving each item one known-correct
    and one known-incorrect comparison drawn from the same corpus, so the two
    conditions differ only in whether the pairing is right.
    """
    usable = [
        i for i in items
        if i.get("question") and i.get("response")
    ]
    if len(usable) < 2:
        empty = DiscriminationResult(0, None, None, None, None)
        return (empty, empty, 0)

    sem = asyncio.Semaphore(concurrency)
    dropped = 0

    async def _score_pair(idx: int) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
        nonlocal dropped
        item = usable[idx]
        other = usable[(idx + 1) % len(usable)]
        async with sem:
            try:
                results = await asyncio.gather(
                    # Correctness: the response against its own reference, then
                    # against an unrelated one
                    judge.evaluate_correctness(
                        answer=item["response"],
                        expected_answer=item["response"],
                        question=item["question"],
                    ),
                    judge.evaluate_correctness(
                        answer=other["response"],
                        expected_answer=item["response"],
                        question=item["question"],
                    ),
                    # Relevancy: the response against its own question, then
                    # against an unrelated question
                    judge.evaluate_relevancy(
                        answer=item["response"], question=item["question"]
                    ),
                    judge.evaluate_relevancy(
                        answer=item["response"], question=other["question"]
                    ),
                    return_exceptions=True,
                )
            except Exception as e:
                logger.warning(f"[CALIBRATION] Discrimination check failed: {e}")
                dropped += 1
                return (None, None)

        if any(isinstance(r, BaseException) for r in results):
            dropped += 1
            return (None, None)

        c_match, c_mismatch, r_match, r_mismatch = results
        return (
            (c_match.score, c_mismatch.score),
            (r_match.score, r_mismatch.score),
        )

    pair_results = await asyncio.gather(*(_score_pair(i) for i in range(len(usable))))
    correctness_pairs = [c for c, _ in pair_results if c is not None]
    relevancy_pairs = [r for _, r in pair_results if r is not None]

    return (
        _summarize_discrimination(correctness_pairs),
        _summarize_discrimination(relevancy_pairs),
        dropped,
    )


def save_calibration(result: CalibrationResult, output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(path, "w") as f:
        json.dump(
            {
                "sample_count": result.sample_count,
                "judge_model": result.judge_model,
                "adherence_accuracy": result.adherence_accuracy,
                "adherence_rmse": result.adherence_rmse,
                "relevance_rmse": result.relevance_rmse,
                "correctness_discrimination": (
                    result.correctness_discrimination.to_dict()
                    if result.correctness_discrimination
                    else None
                ),
                "relevancy_discrimination": (
                    result.relevancy_discrimination.to_dict()
                    if result.relevancy_discrimination
                    else None
                ),
                "metadata": result.metadata,
                "per_item": result.per_item,
            },
            f,
            indent=2,
        )
    logger.info(f"[CALIBRATION] Saved to {path}")
    return path
