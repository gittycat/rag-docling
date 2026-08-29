"""Judge-free retrieval, stage-attribution, and chunk-lineage metrics."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import ir_measures
from ir_measures import R, RR, nDCG

from evals.evidence import _locator_contains, _normalized_text_disagrees, derive_relevant_chunk_ids
from evals.metrics.base import BaseMetric
from evals.schemas import EvalQuestion, EvalResponse, MetricGroup, MetricResult, RetrievedChunk


RETRIEVAL_STAGES = ("bm25", "vector", "fusion", "rerank")


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalized_text_hash(text: str) -> str:
    # Mirrors pipelines/ingestion.py's `_normalized_text`/hash so a gold
    # passage's text can be resolved to a current catalog chunk without the
    # `/documents/{id}/chunks` endpoint exposing chunk content — only the hash
    # travels over the wire, carried in each chunk's `source_locator`.
    return hashlib.sha256(_normalize_text(text).encode()).hexdigest()


def _undefined_result(
    metric: BaseMetric,
    note: str,
    *,
    lineage_failure: bool = False,
    catalog_unavailable: bool = False,
    ground_truth: str | None = None,
) -> MetricResult:
    details: dict[str, Any] = {"note": note}
    if catalog_unavailable:
        details["catalog_unavailable"] = True
    if lineage_failure:
        details["lineage_failure"] = note
        details["ground_truth"] = ground_truth or "source_coordinate"
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


@dataclass(frozen=True)
class _Relevance:
    """Result of resolving a question's ground truth against a chunk catalog."""

    qrels: dict[str, int]
    matched: set[int]
    note: str | None = None
    lineage_failure: bool = False
    catalog_unavailable: bool = False
    unresolved_gold_passages: tuple[str, ...] = field(default_factory=tuple)


def _catalog_index(catalog: list[RetrievedChunk]) -> tuple[set[str], dict[str, list[str]]]:
    ids: set[str] = set()
    hash_index: dict[str, list[str]] = defaultdict(list)
    for chunk in catalog:
        ids.add(chunk.chunk_id)
        source_locator = chunk.metadata.get("source_locator")
        if isinstance(source_locator, dict):
            text_hash = source_locator.get("normalized_text_hash")
            if isinstance(text_hash, str):
                hash_index[text_hash].append(chunk.chunk_id)
    return ids, hash_index


def _relevance(
    question: EvalQuestion, chunks: list[RetrievedChunk], catalog: list[RetrievedChunk] | None
) -> _Relevance:
    """Resolve a question's relevant-set against the full current chunk catalog.

    The relevant set must never be resolved against `chunks` — the ranking being
    scored — because a total miss would then produce an empty relevant set and
    read as unassessable instead of as a 0.0. `chunks` is used only to find the
    positions of relevant chunks within the ranking being scored (`matched`).
    """
    if not question.evidence and not question.gold_passages:
        return _Relevance({}, set(), "No gold passages or source-coordinate evidence defined")

    if not catalog:
        # `None` (never fetched, e.g. a generation-tier run) and `[]`
        # (fetched but empty — nothing can be resolved either way) are both
        # "unavailable", not a real zero: no gold ever resolves to nothing to
        # measure against.
        return _Relevance({}, set(), "chunk catalog unavailable", catalog_unavailable=True)

    if question.evidence:
        resolution = derive_relevant_chunk_ids(question.evidence, catalog)
        if resolution.lineage_failure:
            return _Relevance({}, set(), resolution.lineage_failure, lineage_failure=True)
        if not resolution.chunk_ids:
            # Evidence coordinates do not resolve to any chunk anywhere in the
            # current catalog — the corpus no longer carries this evidence at
            # all. Distinct from a retrieval miss (relevant chunk exists but
            # wasn't retrieved, which scores 0.0 below via ir-measures).
            return _Relevance(
                {}, set(), "evidence not present in current chunk catalog", lineage_failure=True
            )
        qrels = {chunk_id: 1 for chunk_id in resolution.chunk_ids}
        matched = {index for index, chunk in enumerate(chunks) if chunk.chunk_id in qrels}
        return _Relevance(qrels, matched)

    # Legacy chunk_id path: gold passages carry a stale id from dataset
    # construction (`{content_doc_id}:chunk:{n}`) that never matches a
    # retriever-issued id. Resolve each gold passage to the *current* catalog
    # (by unified id when it already matches, else by normalized-text-hash) so
    # a stale anchor never inflates the qrels denominator as a phantom.
    catalog_ids, hash_index = _catalog_index(catalog)
    qrels: dict[str, int] = {}
    unresolved: list[str] = []
    for passage in question.gold_passages:
        resolved_ids: list[str] = []
        if passage.chunk_id and passage.chunk_id in catalog_ids:
            resolved_ids = [passage.chunk_id]
        elif passage.text:
            resolved_ids = hash_index.get(_normalized_text_hash(passage.text), [])
        if not resolved_ids:
            unresolved.append(passage.chunk_id or passage.doc_id)
            continue
        weight = max(1, round(passage.relevance_score * 1000))
        for resolved_id in resolved_ids:
            qrels[resolved_id] = max(qrels.get(resolved_id, 0), weight)

    if not qrels:
        return _Relevance(
            {},
            set(),
            "No gold passage resolves to the current chunk catalog",
            lineage_failure=True,
            unresolved_gold_passages=tuple(unresolved),
        )
    matched = {index for index, chunk in enumerate(chunks) if chunk.chunk_id in qrels}
    return _Relevance(qrels, matched, unresolved_gold_passages=tuple(unresolved))


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

    def _compute_chunks(
        self, question: EvalQuestion, chunks: list[RetrievedChunk], catalog: list[RetrievedChunk] | None
    ) -> MetricResult:
        relevance = _relevance(question, chunks, catalog)
        if relevance.catalog_unavailable:
            return _undefined_result(self, relevance.note, catalog_unavailable=True)
        if relevance.lineage_failure:
            ground_truth = "source_coordinate" if question.evidence else "chunk_id"
            return _undefined_result(self, relevance.note, lineage_failure=True, ground_truth=ground_truth)
        if not relevance.qrels:
            return _undefined_result(self, relevance.note or "No resolvable relevant chunks")
        value = _measure(self.stage_measure, relevance.qrels, chunks, self.stage_k)
        details: dict[str, Any] = {
            "hits": len(relevance.matched),
            "gold_count": len(relevance.qrels),
            "retrieved_count": len(chunks[: self.stage_k]),
            "ground_truth": "source_coordinate" if question.evidence else "chunk_id",
        }
        if relevance.unresolved_gold_passages:
            details["unresolved_gold_passages"] = list(relevance.unresolved_gold_passages)
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
        catalog = kwargs.get("chunk_catalog")
        return self._compute_chunks(question, response.retrieved_chunks, catalog)

    async def compute_batch(
        self, questions: list[EvalQuestion], responses: list[EvalResponse], **kwargs: Any
    ) -> MetricResult:
        result = await super().compute_batch(questions, responses, **kwargs)
        catalog = kwargs.get("chunk_catalog")
        stage_scores: dict[str, list[float]] = defaultdict(list)
        stage_per_question: dict[str, dict[str, float]] = defaultdict(dict)
        stage_not_applicable: dict[str, int] = defaultdict(int)
        for question, response in zip(questions, responses):
            for stage in RETRIEVAL_STAGES:
                chunks = _stage_chunks(response, stage)
                if chunks is None:
                    continue
                stage_result = self._compute_chunks(question, chunks, catalog)
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

    def _compute_chunks(
        self, question: EvalQuestion, chunks: list[RetrievedChunk], catalog: list[RetrievedChunk] | None
    ) -> MetricResult:
        result = super()._compute_chunks(question, chunks, catalog)
        if result.value is not None:
            relevance = _relevance(question, chunks, catalog)
            result.details["first_relevant_rank"] = next(
                (index + 1 for index, chunk in enumerate(chunks) if chunk.chunk_id in relevance.qrels), None
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
        catalog = kwargs.get("chunk_catalog")
        lists = {stage: _stage_chunks(response, stage) for stage in ("bm25", "vector", "fusion")}
        if any(chunks is None for chunks in lists.values()):
            return _undefined_result(self, "BM25, vector, and fusion stage rankings are required")
        scores: dict[str, float] = {}
        for stage, chunks in lists.items():
            metric = NDCG(10)._compute_chunks(question, chunks or [], catalog)
            if metric.value is None:
                return _undefined_result(
                    self,
                    metric.details["note"],
                    lineage_failure="lineage_failure" in metric.details,
                    catalog_unavailable=metric.details.get("catalog_unavailable", False),
                    ground_truth=metric.details.get("ground_truth"),
                )
            scores[stage] = metric.value
        best_leg = max(scores["bm25"], scores["vector"])
        return MetricResult(self.name, scores["fusion"] - best_leg, self.group, {
            "fusion_ndcg_at_10": scores["fusion"], "best_leg_ndcg_at_10": best_leg,
        }, 1)


class CandidateRecallCeiling(_AttributionMetric):
    def __init__(self, k: int | None = None):
        # `None` measures the whole pre-rerank candidate list, whatever depth
        # is actually configured (shipped default is `top_k: 10`) — a fixed
        # k=5 default under-covered candidates ranked 6-10, reporting evidence
        # inside the ceiling as outside it. Pass an explicit k to measure a
        # narrower cutoff.
        self.k = k

    @property
    def name(self) -> str:
        return "candidate_recall_ceiling"

    @property
    def description(self) -> str:
        return "Recall of the full pre-rerank candidate list"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        catalog = kwargs.get("chunk_catalog")
        stage = "fusion" if _stage_chunks(response, "fusion") is not None else "vector"
        chunks = _stage_chunks(response, stage)
        if chunks is None:
            return _undefined_result(self, "A pre-rerank candidate ranking is required")
        effective_k = self.k if self.k is not None else len(chunks)
        result = RecallAtK(effective_k)._compute_chunks(question, chunks, catalog)
        result.name = self.name
        result.details["candidate_stage"] = stage
        result.details["candidate_k"] = effective_k
        return result


class _RerankMovement(_AttributionMetric):
    direction: str

    def __init__(self, k: int = 5):
        self.k = k

    @property
    def description(self) -> str:
        return f"Relevant chunks the reranker moved {self.direction} the final top {self.k}"

    def compute(self, question: EvalQuestion, response: EvalResponse, **kwargs: Any) -> MetricResult:
        catalog = kwargs.get("chunk_catalog")
        pre = _stage_chunks(response, "fusion") or _stage_chunks(response, "vector")
        post = _stage_chunks(response, "rerank")
        if pre is None or post is None:
            return _undefined_result(self, "Pre-rerank and rerank stage rankings are required")
        existing_ids = {chunk.chunk_id for chunk in pre}
        combined = pre + [chunk for chunk in post if chunk.chunk_id not in existing_ids]
        relevance = _relevance(question, combined, catalog)
        if relevance.catalog_unavailable:
            return _undefined_result(self, relevance.note, catalog_unavailable=True)
        if relevance.lineage_failure:
            ground_truth = "source_coordinate" if question.evidence else "chunk_id"
            return _undefined_result(self, relevance.note, lineage_failure=True, ground_truth=ground_truth)
        if not relevance.qrels:
            return _undefined_result(self, relevance.note or "No resolvable relevant chunks")
        pre_ids = {chunk.chunk_id for chunk in pre[: self.k] if chunk.chunk_id in relevance.qrels}
        post_ids = {chunk.chunk_id for chunk in post[: self.k] if chunk.chunk_id in relevance.qrels}
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
    # Per-format containment lives in evidence.py (_locator_contains): every
    # non-text format requires a positive coordinate assertion on both sides -
    # None on both sides (e.g. two PDF locators with no element_id) must never
    # compare equal as a "match". An unsupported/unknown format is never
    # contained.
    if not _locator_contains(evidence.source_format, locator, evidence.locator):
        return False
    # Secondary check: see evidence._normalized_text_disagrees. A chunk's
    # normalized_text_hash hashes its whole node content, a strict superset of
    # the evidence span by construction, so containment (not hash equality) is
    # the right test; hash equality remains a valid fast path. Absent hash and
    # text carries no signal, so containment stands rather than manufacturing
    # a failure out of a lineage field that was never recorded.
    if _normalized_text_disagrees(evidence, source):
        return False
    return True


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
