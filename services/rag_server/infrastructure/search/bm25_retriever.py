"""BM25 retriever using pg_textsearch (Timescale) for PostgreSQL full-text search."""

import logging
import time
from typing import Any

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.postgres import get_session

logger = logging.getLogger(__name__)

# BM25 failures are non-fatal — a broken extension or index silently downgrades
# every hybrid query to vector-only. Track the outcome of the last search so
# /metrics/system can surface the degradation instead of it living in the logs.
_last_error: str | None = None
_last_error_at: float | None = None
_last_success_at: float | None = None
_failure_count: int = 0


def _record_success() -> None:
    global _last_success_at, _last_error, _last_error_at, _failure_count
    _last_success_at = time.time()
    _last_error = None
    _last_error_at = None
    _failure_count = 0


def _record_failure(error: Exception) -> None:
    global _last_error, _last_error_at, _failure_count
    _last_error = f"{type(error).__name__}: {error}"
    _last_error_at = time.time()
    _failure_count += 1


def get_bm25_health() -> dict[str, Any]:
    """Outcome of the most recent BM25 search, for health reporting.

    status is "unknown" until a search has run in this process.
    """
    if _last_error is not None:
        status = "unhealthy"
    elif _last_success_at is not None:
        status = "healthy"
    else:
        status = "unknown"

    return {
        "status": status,
        "last_error": _last_error,
        "last_error_at": _last_error_at,
        "last_success_at": _last_success_at,
        "consecutive_failures": _failure_count,
    }


async def probe_bm25(session: AsyncSession) -> dict[str, Any]:
    """Actively verify the pg_textsearch extension and BM25 index are usable.

    Runs the same operator/index pair the retriever uses, so a missing extension,
    a dropped index or a permissions problem shows up here rather than as silently
    empty hybrid results.
    """
    sql = text(
        "SELECT 1 FROM document_chunks "
        "WHERE content <@> to_bm25query(:query, 'idx_chunks_bm25') < 0 LIMIT 1"
    )
    try:
        await session.execute(sql, {"query": "bm25 health probe"})
    except Exception as e:
        logger.error(f"[BM25] Health probe failed — hybrid search is degraded to vector-only: {e}")
        return {"status": "unavailable", "error": f"{type(e).__name__}: {e}"}
    return {"status": "healthy", "error": None}


class PgSearchBM25Retriever(BaseRetriever):
    """
    BM25 retriever using pg_textsearch (Timescale) for true BM25 full-text search.

    Unlike in-memory BM25, this uses PostgreSQL's pg_textsearch extension which:
    - Scales to millions of documents
    - Persists across restarts
    - Uses optimized inverted indexes with BM25 ranking
    - Supports stemming and tokenization
    """

    def __init__(self, similarity_top_k: int = 10):
        super().__init__()
        self._similarity_top_k = similarity_top_k

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        """Synchronous retrieve - schedules async version on the main event loop."""
        from infrastructure.database.postgres import run_async_safely
        return run_async_safely(self._aretrieve(query_bundle))

    async def _aretrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        """
        Retrieve documents using pg_textsearch BM25.

        Uses pg_textsearch BM25 index on document_chunks.content field.
        """
        query_str = query_bundle.query_str
        if not query_str.strip():
            return []

        logger.debug(f"[BM25] Searching for: {query_str[:100]}...")

        async with get_session() as session:
            return await self._search_bm25(session, query_str)

    async def _search_bm25(
        self, session: AsyncSession, query_str: str
    ) -> list[NodeWithScore]:
        """Execute BM25 search using pg_textsearch <@> operator."""
        # pg_textsearch uses the <@> operator which returns negative BM25 scores
        # (lower = better match, so we ORDER BY ASC and negate for positive scores)
        sql = text("""
            SELECT
                dc.id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.metadata,
                dc.source_locator,
                dc.created_at,
                d.file_name,
                d.file_type,
                d.file_path,
                d.file_size_bytes,
                d.file_hash,
                d.uploaded_at,
                -(dc.content <@> to_bm25query(:query, 'idx_chunks_bm25')) as bm25_score
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.content <@> to_bm25query(:query, 'idx_chunks_bm25') < 0
            ORDER BY dc.content <@> to_bm25query(:query, 'idx_chunks_bm25')
            LIMIT :limit
        """)

        try:
            result = await session.execute(
                sql, {"query": query_str, "limit": self._similarity_top_k}
            )
            rows = result.fetchall()
        except Exception as e:
            # Degrading to vector-only silently is the failure mode 4.5 describes:
            # log at error level and record it so /metrics/system reports it.
            _record_failure(e)
            logger.error(
                f"[BM25] Search failed — this query degrades to vector-only "
                f"(consecutive failures: {_failure_count}): {e}"
            )
            return []

        _record_success()

        nodes_with_scores = []
        for row in rows:
            # Build metadata dict
            metadata = dict(row.metadata) if row.metadata else {}
            metadata.update({
                "document_id": str(row.document_id),
                "chunk_index": row.chunk_index,
                "file_name": row.file_name,
                "file_type": row.file_type,
                "path": row.file_path,
                "file_size_bytes": row.file_size_bytes,
                "file_hash": row.file_hash,
                "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
                "source_locator": (
                    dict(source_locator) if (source_locator := getattr(row, "source_locator", None)) else None
                ),
            })

            # Create TextNode
            node = TextNode(
                id_=f"{row.document_id}-chunk-{row.chunk_index}",
                text=row.content,
                metadata=metadata,
            )

            nodes_with_scores.append(
                NodeWithScore(node=node, score=float(row.bm25_score))
            )

        logger.debug(f"[BM25] Found {len(nodes_with_scores)} results")
        return nodes_with_scores
