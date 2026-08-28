"""Unit coverage for retrieval-stage observability."""

import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.search.hybrid_retriever import HybridRRFRetriever
from pipelines.inference import search_rag_async
from schemas.query import SearchRequest


def _node(chunk_id: str, doc_id: str, score: float) -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(
            id_=chunk_id,
            text=chunk_id,
            metadata={
                "document_id": doc_id,
                "file_hash": "a" * 64,
                "source_locator": {"document_hash": "a" * 64, "source_format": "txt", "locator": {}},
            },
        ),
        score=score,
    )


class _StaticRetriever(BaseRetriever):
    def __init__(self, results: list[NodeWithScore]):
        super().__init__()
        self.results = results

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        return self.results

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        return self.results


def _healthy_traces(retriever: HybridRRFRetriever) -> list[dict]:
    with patch(
        "infrastructure.search.bm25_retriever.get_bm25_health",
        return_value={"last_error": None},
    ), patch(
        "infrastructure.search.vector_retriever.get_vector_health",
        return_value={"last_error": None},
    ):
        retriever.retrieve("where is the evidence?")
    return retriever.last_stage_traces


def test_hybrid_retriever_records_ranked_legs_and_fusion():
    retriever = HybridRRFRetriever(
        _StaticRetriever([_node("a", "doc-a", 0.9), _node("b", "doc-b", 0.8)]),
        _StaticRetriever([_node("b", "doc-b", 0.7), _node("c", "doc-c", 0.6)]),
        rrf_k=60,
        similarity_top_k=2,
    )

    traces = _healthy_traces(retriever)

    assert [trace["name"] for trace in traces] == ["bm25", "vector", "fusion"]
    assert [item["chunk_id"] for item in traces[0]["items"]] == ["a", "b"]
    assert [item["chunk_id"] for item in traces[1]["items"]] == ["b", "c"]
    assert [item["chunk_id"] for item in traces[2]["items"]] == ["b", "a"]
    assert traces[0]["items"][0]["metadata"]["file_hash"] == "a" * 64
    assert all(trace["status"] == "ok" for trace in traces)
    assert all(trace["duration_ms"] >= 0 for trace in traces)


def test_failed_vector_leg_is_explicitly_degraded():
    retriever = HybridRRFRetriever(
        _StaticRetriever([_node("a", "doc-a", 0.9)]),
        _StaticRetriever([]),
    )

    with patch(
        "infrastructure.search.bm25_retriever.get_bm25_health",
        return_value={"last_error": None},
    ), patch(
        "infrastructure.search.vector_retriever.get_vector_health",
        return_value={"last_error": "ConnectionError: embedder unavailable"},
    ):
        retriever.retrieve("where is the evidence?")

    traces = retriever.last_stage_traces
    vector = next(trace for trace in traces if trace["name"] == "vector")
    fusion = next(trace for trace in traces if trace["name"] == "fusion")
    assert vector["status"] == fusion["status"] == "degraded"
    assert vector["error"] == "ConnectionError: embedder unavailable"


def test_search_runs_only_retrieval_and_reranking():
    retriever = _StaticRetriever([_node("a", "doc-a", 0.9)])
    retriever.last_stage_traces = [
        {"name": "bm25", "duration_ms": 1.0, "item_count": 1, "items": [], "status": "ok", "error": None},
        {"name": "vector", "duration_ms": 2.0, "item_count": 1, "items": [], "status": "ok", "error": None},
        {"name": "fusion", "duration_ms": 0.1, "item_count": 1, "items": [], "status": "ok", "error": None},
    ]

    with patch("pipelines.inference.create_hybrid_retriever", return_value=retriever), patch(
        "pipelines.inference.create_reranker_postprocessor", return_value=None
    ):
        traces = asyncio.run(search_rag_async("where is the evidence?", top_k=3))

    assert [trace["name"] for trace in traces] == ["bm25", "vector", "fusion", "rerank"]
    assert traces[-1]["item_count"] == 1


def test_search_endpoint_filters_traces_without_creating_a_session():
    from api.routes.query import search

    traces = [
        {"name": "bm25", "duration_ms": 1.0, "item_count": 1, "items": [], "status": "ok", "error": None},
        {"name": "vector", "duration_ms": 1.0, "item_count": 1, "items": [], "status": "ok", "error": None},
    ]

    async def fake_search(query: str, top_k: int) -> list[dict]:
        assert query == "where is the evidence?"
        assert top_k == 3
        return traces

    with patch("api.routes.query.search_rag_async", fake_search):
        response = asyncio.run(
            search(SearchRequest(query="where is the evidence?", top_k=3, stages=["vector"]))
        )

    assert response == [traces[1]]
