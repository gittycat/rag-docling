"""Judge-free retrieval, stage-attribution, and chunk-lineage metrics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import ir_measures
from ir_measures import R, RR, nDCG

from evals.evidence import derive_relevant_chunk_ids
from evals.metrics.base import BaseMetric
from evals.metrics.text_match import _token_overlap, match_retrieved_to_gold
from evals.schemas import EvalQuestion, EvalResponse, MetricGroup, MetricResult, RetrievedChunk


RETRIEVAL_STAGES = ("bm25", "vector", "fusion", "rerank")


def _undefined_result(metric: BaseMetric, note: str, *, lineage_failure: bool = False) -> MetricResult:
    details: dict[str, Any] = {"note": note}
    if lineage_failure:
        details["lineage_failure"] = note
        details["ground_truth"] = "source_coordinate"
    return MetricResult(metric.name, None, metric.group, details, sample_size=0)


def _stage_chunks(response: EvalResponse, stage: str) -> list[RetrievedChunk] | None:
    """Materialize a ranked stage list with its source lineage intact."""
    if response.metrics is None:
        return None
    trace = next((item for item in response.metrics.stages if item.name == stage), None)
    if trace is None or trace.items is None:
        return None
    return [
        RetrievedChunk(
            doc_id=item.doc_id,
            chunk_id=item.chunk_id,
            text="",
            score=item.score,
            rank=item.rank,
            metadata=dict(item.metadata),
        )
        for item in trace.items
    ]


def _relevance(
    question: EvalQuestion, chunks: list[RetrievedChunk]
) -> tuple[dict[str, int], set[int], str | None]:
    """Produce ir-measures qrels and matched result positions for one ranking."""
    if question.evidence:
        resolution = derive_relevant_chunk_ids(question.evidence, chunks)
        if resolution.lineage_failure:
            return {}, set(), resolution.lineage_failure
        return {chunk_id: 1 for chunk_id in resolution.chunk_ids}, resolution.matched_indices, None

    if not question.gold_passages:
        return {}, set(), "No gold passages or source-coordinate evidence defined"

    matched = match_retrieved_to_gold(chunks, question.gold_passages)
    qrels: dict[str, int] = {}
    for passage in question.gold_passages:
        if passage.chunk_id:
            # ir-measures qrels use integer graded relevance. Scaling preserves
            # labelled ordering without treating a positive label as zero.
            qrels[passage.chunk_id] = max(1, round(passage.relevance_score * 1000))

    # Public benchmarks may supply text-only gold. Keep their existing matching
    # behaviour, but assign every matched current chunk a qrel for this run.
    for index in matched:
        chunk = chunks[index]
        if chunk.chunk_id not in qrels:
            score = 1.0
            for passage in question.gold_passages:
                if passage.text and _token_overlap(chunk.text, passage.text) >= 0.3:
                    score = passage.relevance_score
                    break
            qrels[chunk.chunk_id] = max(1, round(score * 1000))
    return qrels, matched, None


def _run(chunks: list[RetrievedChunk], k: int | None = None) -> dict[str, dict[str, float]]:
    selected = chunks[:k] if k is not None else chunks
    ranked: dict[str, float] = {}
    for index, chunk in enumerate(selected):
        # Retrieval scores are not cross-leg comparable; this preserves only order.
        ranked.setdefault(chunk.chunk_id, float(len(selected) - index))
    return {"q": ranked}


def _measure(measure: Any, qrels: dict[str, int], chunks: list[RetrievedChunk], k: int | None = None) -> float:
    return float(ir_measures.calc_aggregate([measure], {"q": qrels}, _run(chunks, k))[measure])


class _RankingMetric(BaseMetric):
    """Standard ranking metric plus aggregate scores per retrieval leg."""

    stage_measure: Any
    stage_k: int | None = None

    @property
    def group(self) -> MetricGroup:
        return MetricGroup.RETRIEVAL

    @property
    def requires_gold(self) -> bool:
        return True

    @property
    def requires_judge(self) -> bool:
        return False

    def _compute_chunks(self, question: EvalQuestion, chunks: list[RetrievedChunk]) -> MetricResult:
        qrels, matched, failure = _relevance(question, chunks)
        if failure:
            return _undefined_result(self, failure, lineage_failure=bool(question.evidence))
        if not qrels:
            return _undefined_result(self, "No resolvable relevant chunks")
        value = _measure(self.stage_measure, qrels, chunks, self.stage_k)
        details: dict[str, Any] = {
            "hits": len(matched),
            "gold_count": len(qrels),
            "retrieved_count": len(chunks[: self.stage_k]),
            "ground_truth": "source_coordinate" if question.evidence else "chunk_id",
        }
        if not chunks:
            details["note"] = "No chunks retrieved"
        return MetricResult(
            name=self.name,
            value=value,
            group=self.group,
            sample_size=1,
            details=details,
        )

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        return self._compute_chunks(question, response.retrieved_chunks)

    async def compute_batch(
        self, questions: list[EvalQuestion], responses: list[EvalResponse], **kwargs: Any
    ) -> MetricResult:
        result = await super().compute_batch(questions, responses, **kwargs)
        stage_scores: dict[str, list[float]] = defaultdict(list)
        stage_per_question: dict[str, dict[str, float]] = defaultdict(dict)
        stage_not_applicable: dict[str, int] = defaultdict(int)
        for question, response in zip(questions, responses):
            for stage in RETRIEVAL_STAGES:
                chunks = _stage_chunks(response, stage)
                if chunks is None:
                    continue
                stage_result = self._compute_chunks(question, chunks)
                if stage_result.value is None:
                    stage_not_applicable[stage] += 1
                    continue
                stage_scores[stage].append(stage_result.value)
                stage_per_question[stage][question.id] = stage_result.value
        if stage_scores:
            result.details["stage_scores"] = {
                f"{self.name}{{leg={stage}}}": sum(values) / len(values)
                for stage, values in stage_scores.items()
            }
            result.details["stage_per_question"] = dict(stage_per_question)
        if stage_not_applicable:
            result.details["stage_not_applicable_count"] = dict(stage_not_applicable)
        return result


class RecallAtK(_RankingMetric):
    def __init__(self, k: int = 5):
        self.k = k
        self.stage_measure = R @ k
        self.stage_k = k

    @property
    def name(self) -> str:
        return f"recall_at_{self.k}"

    @property
    def description(self) -> str:
        return f"Fraction of relevant documents retrieved in top {self.k}"


class PrecisionAtK(_RankingMetric):
    """Retained headline precision metric; ir-measures performs its math."""

    def __init__(self, k: int = 5):
        from ir_measures import P

        self.k = k
        self.stage_measure = P @ k
        self.stage_k = k

    @property
    def name(self) -> str:
        return f"precision_at_{self.k}"

    @property
    def description(self) -> str:
        return f"Fraction of top {self.k} retrieved documents that are relevant"


class MRR(_RankingMetric):
    stage_measure = RR
    stage_k = None

    @property
    def name(self) -> str:
        return "mrr"

    @property
    def description(self) -> str:
        return "Reciprocal of the rank of the first relevant result"

    def _compute_chunks(self, question: EvalQuestion, chunks: list[RetrievedChunk]) -> MetricResult:
        result = super()._compute_chunks(question, chunks)
        if result.value is not None:
            qrels, _, _ = _relevance(question, chunks)
            result.details["first_relevant_rank"] = next(
                (index + 1 for index, chunk in enumerate(chunks) if chunk.chunk_id in qrels), None
            )
        return result


class NDCG(_RankingMetric):
    def __init__(self, k: int = 10):
        self.k = k
        self.stage_measure = nDCG @ k
        self.stage_k = k

    @property
    def name(self) -> str:
        return f"ndcg_at_{self.k}"

    @property
    def description(self) -> str:
        return f"Normalized discounted cumulative gain at {self.k}"


class _AttributionMetric(BaseMetric):
    @property
    def group(self) -> MetricGroup:
        return MetricGroup.RETRIEVAL

    @property
    def requires_gold(self) -> bool:
        return True

    @property
    def requires_judge(self) -> bool:
        return False


class FusionLift(_AttributionMetric):
    @property
    def name(self) -> str:
        return "fusion_lift"

    @property
    def description(self) -> str:
        return "Fused nDCG@10 minus the better individual retrieval leg"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        lists = {stage: _stage_chunks(response, stage) for stage in ("bm25", "vector", "fusion")}
        if any(chunks is None for chunks in lists.values()):
            return _undefined_result(self, "BM25, vector, and fusion stage rankings are required")
        scores: dict[str, float] = {}
        for stage, chunks in lists.items():
            metric = NDCG(10)._compute_chunks(question, chunks or [])
            if metric.value is None:
                return _undefined_result(self, metric.details["note"], lineage_failure="lineage_failure" in metric.details)
            scores[stage] = metric.value
        best_leg = max(scores["bm25"], scores["vector"])
        return MetricResult(self.name, scores["fusion"] - best_leg, self.group, {
            "fusion_ndcg_at_10": scores["fusion"], "best_leg_ndcg_at_10": best_leg,
        }, 1)


class CandidateRecallCeiling(_AttributionMetric):
    def __init__(self, k: int = 5):
        self.k = k

    @property
    def name(self) -> str:
        return "candidate_recall_ceiling"

    @property
    def description(self) -> str:
        return "Recall@K of the candidate ranking before reranking"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        stage = "fusion" if _stage_chunks(response, "fusion") is not None else "vector"
        chunks = _stage_chunks(response, stage)
        if chunks is None:
            return _undefined_result(self, "A pre-rerank candidate ranking is required")
        result = RecallAtK(self.k)._compute_chunks(question, chunks)
        result.name = self.name
        result.details["candidate_stage"] = stage
        return result


class _RerankMovement(_AttributionMetric):
    direction: str

    def __init__(self, k: int = 5):
        self.k = k

    @property
    def description(self) -> str:
        return f"Relevant chunks the reranker moved {self.direction} the final top {self.k}"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        pre = _stage_chunks(response, "fusion") or _stage_chunks(response, "vector")
        post = _stage_chunks(response, "rerank")
        if pre is None or post is None:
            return _undefined_result(self, "Pre-rerank and rerank stage rankings are required")
        existing_ids = {chunk.chunk_id for chunk in pre}
        combined = pre + [chunk for chunk in post if chunk.chunk_id not in existing_ids]
        qrels, _, failure = _relevance(question, combined)
        if failure:
            return _undefined_result(self, failure, lineage_failure=bool(question.evidence))
        if not qrels:
            return _undefined_result(self, "No resolvable relevant chunks")
        pre_ids = {chunk.chunk_id for chunk in pre[: self.k] if chunk.chunk_id in qrels}
        post_ids = {chunk.chunk_id for chunk in post[: self.k] if chunk.chunk_id in qrels}
        moved = post_ids - pre_ids if self.direction == "into" else pre_ids - post_ids
        return MetricResult(self.name, float(len(moved)), self.group, {
            "chunk_ids": sorted(moved), "top_k": self.k,
        }, 1)


class RerankPromotions(_RerankMovement):
    direction = "into"

    @property
    def name(self) -> str:
        return "rerank_promotions"


class RerankDemotions(_RerankMovement):
    direction = "out of"

    @property
    def name(self) -> str:
        return "rerank_demotions"


def _chunk_catalog(response: EvalResponse, kwargs: dict[str, Any]) -> list[RetrievedChunk] | None:
    catalog = kwargs.get("chunks") or kwargs.get("chunk_catalog")
    if catalog is None and response.raw_response:
        catalog = response.raw_response.get("chunk_catalog")
    return list(catalog) if catalog is not None else None


def _wholly_contained(evidence: Any, chunk: RetrievedChunk) -> bool:
    source = chunk.metadata.get("source_locator")
    if not isinstance(source, dict) or source.get("document_hash") != evidence.document_hash:
        return False
    if source.get("source_format", "").lower() != evidence.source_format.lower():
        return False
    locator = source.get("locator")
    if not isinstance(locator, dict):
        return False
    if evidence.source_format.lower() in {"txt", "md", "html", "htm"}:
        return (
            locator.get("element_path") == evidence.locator.get("element_path")
            and isinstance(locator.get("start_char"), int)
            and isinstance(locator.get("end_char"), int)
            and locator["start_char"] <= evidence.locator.get("start_char", -1)
            and locator["end_char"] >= evidence.locator.get("end_char", -1)
        )
    # Element-based formats have no finer stable coordinate. A matching element
    # is the strongest containment statement their lineage model can make.
    return locator.get("element_id") == evidence.locator.get("element_id")


class _ChunkingMetric(_AttributionMetric):
    def _resolved(
        self, question: EvalQuestion, response: EvalResponse, kwargs: dict[str, Any]
    ) -> tuple[list[RetrievedChunk] | None, MetricResult | None]:
        if not question.evidence:
            return None, _undefined_result(self, "Source-coordinate evidence is required")
        catalog = _chunk_catalog(response, kwargs)
        if catalog is None:
            return None, _undefined_result(self, "A complete current chunk catalog is required")
        resolution = derive_relevant_chunk_ids(question.evidence, catalog)
        if resolution.lineage_failure:
            return None, _undefined_result(self, resolution.lineage_failure, lineage_failure=True)
        return catalog, None


class EvidenceContainment(_ChunkingMetric):
    @property
    def name(self) -> str:
        return "evidence_containment"

    @property
    def description(self) -> str:
        return "Fraction of evidence spans wholly contained in one current chunk"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        catalog, undefined = self._resolved(question, response, kwargs)
        if undefined:
            return undefined
        assert catalog is not None
        contained = sum(any(_wholly_contained(item, chunk) for chunk in catalog) for item in question.evidence)
        counts = [len(derive_relevant_chunk_ids([item], catalog).chunk_ids) for item in question.evidence]
        return MetricResult(self.name, contained / len(counts), self.group, {
            "contained_evidence": contained, "evidence_count": len(counts),
        }, 1)


class EvidenceFragmentation(_ChunkingMetric):
    @property
    def name(self) -> str:
        return "evidence_fragmentation"

    @property
    def description(self) -> str:
        return "Mean number of chunks covering one source-coordinate evidence span"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        catalog, undefined = self._resolved(question, response, kwargs)
        if undefined:
            return undefined
        assert catalog is not None
        counts = [len(derive_relevant_chunk_ids([item], catalog).chunk_ids) for item in question.evidence]
        return MetricResult(self.name, sum(counts) / len(counts), self.group, {"chunks_per_evidence": counts}, 1)


class OrphanedEvidenceRate(_ChunkingMetric):
    @property
    def name(self) -> str:
        return "orphaned_evidence_rate"

    @property
    def description(self) -> str:
        return "Fraction of source-coordinate evidence missing from all current chunks"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        catalog, undefined = self._resolved(question, response, kwargs)
        if undefined:
            return undefined
        assert catalog is not None
        counts = [len(derive_relevant_chunk_ids([item], catalog).chunk_ids) for item in question.evidence]
        orphaned = sum(count == 0 for count in counts)
        return MetricResult(self.name, orphaned / len(counts), self.group, {
            "orphaned_evidence": orphaned, "evidence_count": len(counts),
        }, 1)


class EvidenceSetRecall(_AttributionMetric):
    def __init__(self, k: int = 5):
        self.k = k

    @property
    def name(self) -> str:
        return "evidence_set_recall"

    @property
    def description(self) -> str:
        return "Fraction of source-coordinate evidence sets fully retrieved in top K"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        if not question.evidence:
            return _undefined_result(self, "Source-coordinate evidence is required")
        resolution = derive_relevant_chunk_ids(question.evidence, response.retrieved_chunks[: self.k])
        if resolution.lineage_failure:
            return _undefined_result(self, resolution.lineage_failure, lineage_failure=True)
        groups: dict[str, list[int]] = defaultdict(list)
        for index, evidence in enumerate(question.evidence):
            groups[evidence.evidence_set_id or f"evidence:{index}"].append(index)
        complete = sum(all(index in resolution.matched_evidence_indices for index in indices) for indices in groups.values())
        return MetricResult(self.name, complete / len(groups), self.group, {
            "complete_sets": complete, "evidence_set_count": len(groups),
        }, 1)
