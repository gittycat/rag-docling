"""PgVectorRetriever: node-id parity with BM25, and its failure posture.

A vector fault never fails a query — it degrades hybrid search to BM25-only.
These tests pin that degradation, the signal that makes it visible, and the
node-id format that RRF fusion dedupes on.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from llama_index.core.schema import QueryBundle

DOCUMENT_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture(autouse=True)
def _reset_vector_health():
    from infrastructure.search import vector_retriever

    vector_retriever._last_error = None
    vector_retriever._last_error_at = None
    vector_retriever._last_success_at = None
    vector_retriever._failure_count = 0
    yield


def _row(chunk_index=3):
    """One result row, shaped so both retrievers can build a node from it."""
    return SimpleNamespace(
        id=UUID("99999999-9999-9999-9999-999999999999"),
        document_id=DOCUMENT_ID,
        chunk_index=chunk_index,
        content="the chunk text",
        metadata={"section": "intro"},
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        file_name="report.pdf",
        file_type="pdf",
        file_path="/app/documents/report.pdf",
        file_size_bytes=1234,
        file_hash="abc123",
        uploaded_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        similarity=0.87,
        bm25_score=4.2,
    )


def _session(rows=None, side_effect=None):
    session = AsyncMock()
    if side_effect is not None:
        session.execute.side_effect = side_effect
    else:
        result_proxy = Mock()
        result_proxy.fetchall.return_value = rows or []
        session.execute.return_value = result_proxy
    return session


def _embed_model(*, embedding=None, side_effect=None):
    from llama_index.core.embeddings import BaseEmbedding

    model = MagicMock(spec=BaseEmbedding)
    if side_effect is not None:
        model.aget_query_embedding = AsyncMock(side_effect=side_effect)
    else:
        model.aget_query_embedding = AsyncMock(return_value=embedding)
    return model


@pytest.mark.asyncio
async def test_node_ids_are_byte_identical_to_the_bm25_retriever():
    """RRF fusion dedupes on node_id: if these diverge, every chunk found by both
    retrievers is counted twice and fusion silently breaks."""
    from infrastructure.search.bm25_retriever import PgSearchBM25Retriever
    from infrastructure.search.vector_retriever import PgVectorRetriever

    row = _row()

    vector_nodes = await PgVectorRetriever(similarity_top_k=5)._search_vector(
        _session(rows=[row]), [0.1, 0.2]
    )
    bm25_nodes = await PgSearchBM25Retriever(similarity_top_k=5)._search_bm25(
        _session(rows=[row]), "the chunk"
    )

    assert vector_nodes[0].node.node_id == bm25_nodes[0].node.node_id
    assert vector_nodes[0].node.node_id == f"{DOCUMENT_ID}-chunk-3"
    # Fused results must carry identical metadata whichever retriever surfaced them.
    assert vector_nodes[0].node.metadata == bm25_nodes[0].node.metadata
    assert vector_nodes[0].score == pytest.approx(0.87)


@pytest.mark.asyncio
async def test_query_vector_is_bound_not_interpolated():
    """The embedding reaches Postgres as a bound literal cast server-side."""
    from infrastructure.search.vector_retriever import PgVectorRetriever

    session = _session()
    await PgVectorRetriever(similarity_top_k=7)._search_vector(session, [0.1, -0.2])

    sql, params = session.execute.await_args.args
    assert "CAST(:qvec AS vector)" in str(sql)
    assert params["qvec"] == "[0.1,-0.2]"
    assert params["limit"] == 7


@pytest.mark.asyncio
async def test_failed_query_embedding_returns_empty_instead_of_raising():
    """An unreachable embedding model degrades the query to BM25-only."""
    from llama_index.core import Settings

    from infrastructure.search.vector_retriever import PgVectorRetriever, get_vector_health

    Settings.embed_model = _embed_model(side_effect=ConnectionError("tei unreachable"))
    try:
        results = await PgVectorRetriever(similarity_top_k=5)._aretrieve(
            QueryBundle(query_str="what is this about?")
        )
    finally:
        Settings._embed_model = None

    assert results == []  # caller sees "no dense matches", not an error
    health = get_vector_health()
    assert health["status"] == "unhealthy"
    assert "tei unreachable" in health["last_error"]


@pytest.mark.asyncio
async def test_failed_search_returns_empty_and_is_recorded():
    from infrastructure.search.vector_retriever import PgVectorRetriever, get_vector_health

    retriever = PgVectorRetriever(similarity_top_k=5)
    results = await retriever._search_vector(
        _session(side_effect=RuntimeError('type "vector" does not exist')), [0.1, 0.2]
    )

    assert results == []
    health = get_vector_health()
    assert health["status"] == "unhealthy"
    assert health["consecutive_failures"] == 1
    assert "does not exist" in health["last_error"]


@pytest.mark.asyncio
async def test_consecutive_failures_accumulate_then_clear_on_success():
    from infrastructure.search.vector_retriever import PgVectorRetriever, get_vector_health

    retriever = PgVectorRetriever(similarity_top_k=5)
    for _ in range(3):
        await retriever._search_vector(_session(side_effect=RuntimeError("boom")), [0.1])
    assert get_vector_health()["consecutive_failures"] == 3

    await retriever._search_vector(_session(), [0.1])

    health = get_vector_health()
    assert health["status"] == "healthy"
    assert health["consecutive_failures"] == 0
    assert health["last_error"] is None
