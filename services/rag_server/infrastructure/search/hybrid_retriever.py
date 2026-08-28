"""Hybrid retriever combining BM25 and vector search with RRF fusion."""

import logging
import time
from collections import defaultdict
from typing import Any

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle

logger = logging.getLogger(__name__)


class HybridRRFRetriever(BaseRetriever):
    """
    Hybrid retriever using Reciprocal Rank Fusion (RRF) to combine
    BM25 (sparse) and vector (dense) search results.

    RRF Formula: score = sum(1 / (k + rank)) for each result list
    where k is a constant (default 60) that controls rank sensitivity.

    Research shows hybrid search improves retrieval by ~48% vs vector-only,
    and combined with reranking achieves 67% improvement.
    """

    def __init__(
        self,
        bm25_retriever: BaseRetriever,
        vector_retriever: BaseRetriever,
        rrf_k: int = 60,
        similarity_top_k: int = 10,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
    ):
        super().__init__()
        self._bm25_retriever = bm25_retriever
        self._vector_retriever = vector_retriever
        self._rrf_k = rrf_k
        self._similarity_top_k = similarity_top_k
        self._bm25_weight = bm25_weight
        self._vector_weight = vector_weight
        self._last_stage_traces: list[dict[str, Any]] = []

    @property
    def last_stage_traces(self) -> list[dict[str, Any]]:
        """The ranked legs and fusion output from the most recent retrieval."""
        return self._last_stage_traces.copy()

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        """Synchronous retrieve using RRF fusion."""
        # Get results from both retrievers
        bm25_start = time.perf_counter()
        bm25_results = self._bm25_retriever.retrieve(query_bundle)
        bm25_duration_ms = (time.perf_counter() - bm25_start) * 1000

        vector_start = time.perf_counter()
        vector_results = self._vector_retriever.retrieve(query_bundle)
        vector_duration_ms = (time.perf_counter() - vector_start) * 1000

        fusion_start = time.perf_counter()
        fused_results = self._fuse_results(bm25_results, vector_results)
        fusion_duration_ms = (time.perf_counter() - fusion_start) * 1000
        self._last_stage_traces = self._build_stage_traces(
            bm25_results,
            vector_results,
            fused_results,
            bm25_duration_ms,
            vector_duration_ms,
            fusion_duration_ms,
        )
        return fused_results

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        """Async retrieve using RRF fusion."""
        import asyncio

        async def capture(retriever: BaseRetriever) -> tuple[list[NodeWithScore], float]:
            started = time.perf_counter()
            results = await retriever._aretrieve(query_bundle)
            return results, (time.perf_counter() - started) * 1000

        # Run both retrievers in parallel
        bm25_task = asyncio.create_task(
            capture(self._bm25_retriever)
        )
        vector_task = asyncio.create_task(
            capture(self._vector_retriever)
        )

        (bm25_results, bm25_duration_ms), (vector_results, vector_duration_ms) = await asyncio.gather(
            bm25_task, vector_task
        )

        fusion_start = time.perf_counter()
        fused_results = self._fuse_results(bm25_results, vector_results)
        fusion_duration_ms = (time.perf_counter() - fusion_start) * 1000
        self._last_stage_traces = self._build_stage_traces(
            bm25_results,
            vector_results,
            fused_results,
            bm25_duration_ms,
            vector_duration_ms,
            fusion_duration_ms,
        )
        return fused_results

    def _build_stage_traces(
        self,
        bm25_results: list[NodeWithScore],
        vector_results: list[NodeWithScore],
        fused_results: list[NodeWithScore],
        bm25_duration_ms: float,
        vector_duration_ms: float,
        fusion_duration_ms: float,
    ) -> list[dict[str, Any]]:
        from infrastructure.search.bm25_retriever import get_bm25_health
        from infrastructure.search.vector_retriever import get_vector_health

        bm25_health = get_bm25_health()
        vector_health = get_vector_health()
        bm25_trace = self._stage_trace("bm25", bm25_results, bm25_duration_ms, bm25_health)
        vector_trace = self._stage_trace("vector", vector_results, vector_duration_ms, vector_health)
        degraded = [trace for trace in (bm25_trace, vector_trace) if trace["status"] == "degraded"]
        fusion_error = "; ".join(trace["error"] for trace in degraded if trace["error"]) or None
        return [
            bm25_trace,
            vector_trace,
            {
                "name": "fusion",
                "duration_ms": fusion_duration_ms,
                "item_count": len(fused_results),
                "items": self._stage_items(fused_results),
                "status": "degraded" if degraded else "ok",
                "error": fusion_error,
            },
        ]

    @staticmethod
    def _stage_items(results: list[NodeWithScore]) -> list[dict[str, Any]]:
        return [
            {
                "chunk_id": node_with_score.node.node_id,
                "doc_id": str(node_with_score.node.metadata.get("document_id", "")),
                "score": node_with_score.score,
                "rank": rank,
                "metadata": {
                    "file_hash": node_with_score.node.metadata.get("file_hash"),
                    "source_locator": node_with_score.node.metadata.get("source_locator"),
                },
            }
            for rank, node_with_score in enumerate(results, start=1)
        ]

    def _stage_trace(
        self,
        name: str,
        results: list[NodeWithScore],
        duration_ms: float,
        health: dict[str, Any],
    ) -> dict[str, Any]:
        error = health.get("last_error")
        return {
            "name": name,
            "duration_ms": duration_ms,
            "item_count": len(results),
            "items": self._stage_items(results),
            "status": "degraded" if error else "ok",
            "error": error,
        }

    def _fuse_results(
        self,
        bm25_results: list[NodeWithScore],
        vector_results: list[NodeWithScore],
    ) -> list[NodeWithScore]:
        """
        Fuse results using Reciprocal Rank Fusion.

        RRF score = bm25_weight * (1 / (k + bm25_rank)) + vector_weight * (1 / (k + vector_rank))
        """
        logger.debug(
            f"[HYBRID] Fusing {len(bm25_results)} BM25 + {len(vector_results)} vector results"
        )

        # Track scores and nodes by ID
        rrf_scores: dict[str, float] = defaultdict(float)
        node_map: dict[str, NodeWithScore] = {}

        # Score BM25 results
        for rank, node_with_score in enumerate(bm25_results, start=1):
            node_id = node_with_score.node.node_id
            rrf_scores[node_id] += self._bm25_weight * (1.0 / (self._rrf_k + rank))
            if node_id not in node_map:
                node_map[node_id] = node_with_score

        # Score vector results
        for rank, node_with_score in enumerate(vector_results, start=1):
            node_id = node_with_score.node.node_id
            rrf_scores[node_id] += self._vector_weight * (1.0 / (self._rrf_k + rank))
            if node_id not in node_map:
                node_map[node_id] = node_with_score

        # Sort by RRF score
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)

        # Build result list with RRF scores
        fused_results = []
        for node_id in sorted_ids[: self._similarity_top_k]:
            original = node_map[node_id]
            fused_results.append(
                NodeWithScore(node=original.node, score=rrf_scores[node_id])
            )

        logger.debug(f"[HYBRID] Fused to {len(fused_results)} results")
        return fused_results


def create_hybrid_retriever(
    similarity_top_k: int = 10,
    rrf_k: int = 60,
) -> HybridRRFRetriever:
    """
    Create a hybrid retriever combining BM25 (pg_textsearch) and vector search
    (pgvector + pgvectorscale). Both retrievers read document_chunks directly, so
    there is nothing to pass in.

    Args:
        similarity_top_k: Number of results to return
        rrf_k: RRF constant (default 60)

    Returns:
        HybridRRFRetriever instance
    """
    from infrastructure.search.bm25_retriever import PgSearchBM25Retriever
    from infrastructure.search.vector_retriever import PgVectorRetriever

    bm25_retriever = PgSearchBM25Retriever(similarity_top_k=similarity_top_k)
    vector_retriever = PgVectorRetriever(similarity_top_k=similarity_top_k)

    return HybridRRFRetriever(
        bm25_retriever=bm25_retriever,
        vector_retriever=vector_retriever,
        rrf_k=rrf_k,
        similarity_top_k=similarity_top_k,
    )
