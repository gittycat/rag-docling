"""Vector retriever using pgvector + pgvectorscale (StreamingDiskANN) in PostgreSQL."""

import logging
import time
from typing import Any

from llama_index.core import Settings
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.postgres import get_session

logger = logging.getLogger(__name__)

# Vector failures are non-fatal — a missing extension, a dropped index or an
# unreachable embedding model silently downgrades every hybrid query to
# BM25-only. Track the outcome of the last search so /metrics/system can surface
# the degradation instead of it living in the logs.
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


def _to_pgvector_literal(embedding: list[float]) -> str:
    # pgvector has no asyncpg codec registered here, so the vector is bound as a
    # text literal and cast server-side with CAST(:qvec AS vector).
    return "[" + ",".join(str(float(v)) for v in embedding) + "]"


def get_vector_health() -> dict[str, Any]:
    """Outcome of the most recent vector search, for health reporting.

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


async def probe_vector_index(session: AsyncSession) -> dict[str, Any]:
    """Actively verify the pgvector extension and the diskann index are usable.

    Runs the same operator the retriever uses with a probe vector of the
    configured dimension, so a missing extension, a dimension mismatch between
    config.yml and the schema, or a permissions problem shows up here rather than
    as silently empty hybrid results. The index is checked by name because a
    dropped diskann index degrades to a sequential scan instead of erroring.
    """
    from infrastructure.config.models_config import get_models_config

    dimension = get_models_config().vector_store.dimension
    # Non-zero probe vector: cosine distance against an all-zero vector is undefined.
    probe_vector = _to_pgvector_literal([1.0] + [0.0] * (dimension - 1))

    try:
        index_present = await session.scalar(
            text(
                "SELECT 1 FROM pg_class "
                "WHERE relname = 'idx_chunks_embedding' AND relkind = 'i'"
            )
        )
        if not index_present:
            message = (
                "diskann index 'idx_chunks_embedding' is missing — vector search "
                "would fall back to a sequential scan over every chunk"
            )
            logger.error(f"[VECTOR] Health probe failed: {message}")
            return {"status": "unavailable", "error": message}

        await session.execute(
            text(
                "SELECT 1 FROM document_chunks "
                "WHERE embedding IS NOT NULL "
                "ORDER BY embedding <=> CAST(:qvec AS vector) LIMIT 1"
            ),
            {"qvec": probe_vector},
        )
    except Exception as e:
        logger.error(
            f"[VECTOR] Health probe failed — hybrid search is degraded to BM25-only: {e}"
        )
        return {"status": "unavailable", "error": f"{type(e).__name__}: {e}"}

    return {"status": "healthy", "error": None}


class PgVectorRetriever(BaseRetriever):
    """
    Dense retriever using pgvector with a pgvectorscale StreamingDiskANN index.

    Embeddings live on document_chunks alongside the text and the BM25 index, so:
    - Retrieval is a single Postgres query, no second store to keep in sync
    - Deletes cascade from documents, so orphaned vectors are impossible
    - Only an SBQ-compressed representation stays resident in RAM
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
        Retrieve documents using cosine similarity over the embedding column.

        Uses the diskann index on document_chunks.embedding.
        """
        query_str = query_bundle.query_str
        if not query_str.strip():
            return []

        logger.debug(f"[VECTOR] Searching for: {query_str[:100]}...")

        try:
            # Must be the async variant: the sync one blocks the event loop on a
            # TEI round-trip, which would serialise the asyncio.gather() in
            # HybridRRFRetriever._aretrieve and stop BM25 running concurrently.
            query_embedding = await Settings.embed_model.aget_query_embedding(query_str)
        except Exception as e:
            # An unreachable embedding model degrades the query to BM25-only.
            _record_failure(e)
            logger.error(
                f"[VECTOR] Query embedding failed — this query degrades to BM25-only "
                f"(consecutive failures: {_failure_count}): {e}"
            )
            return []

        async with get_session() as session:
            return await self._search_vector(session, query_embedding)

    async def _search_vector(
        self, session: AsyncSession, query_embedding: list[float]
    ) -> list[NodeWithScore]:
        """Execute an ANN search using the pgvector <=> cosine-distance operator."""
        # <=> returns cosine distance in [0, 2] (lower = better), so ORDER BY ASC
        # and report 1 - distance as a similarity score.
        sql = text("""
            SELECT
                dc.id,
                dc.document_id,
                dc.chunk_index,
                dc.content,
                dc.metadata,
                dc.created_at,
                d.file_name,
                d.file_type,
                d.file_path,
                d.file_size_bytes,
                d.file_hash,
                d.uploaded_at,
                1 - (dc.embedding <=> CAST(:qvec AS vector)) AS similarity
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.embedding IS NOT NULL
            ORDER BY dc.embedding <=> CAST(:qvec AS vector)
            LIMIT :limit
        """)

        try:
            result = await session.execute(
                sql,
                {
                    "qvec": _to_pgvector_literal(query_embedding),
                    "limit": self._similarity_top_k,
                },
            )
            rows = result.fetchall()
        except Exception as e:
            # Degrading to BM25-only silently is the failure mode 4.5 describes:
            # log at error level and record it so /metrics/system reports it.
            _record_failure(e)
            logger.error(
                f"[VECTOR] Search failed — this query degrades to BM25-only "
                f"(consecutive failures: {_failure_count}): {e}"
            )
            return []

        _record_success()

        nodes_with_scores = []
        for row in rows:
            # Build metadata dict — must match PgSearchBM25Retriever exactly so
            # fused results carry identical metadata regardless of which
            # retriever surfaced them first.
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
            })

            # id_ MUST be byte-identical to PgSearchBM25Retriever's — RRF fusion
            # dedupes on node_id, so any divergence double-counts every result.
            node = TextNode(
                id_=f"{row.document_id}-chunk-{row.chunk_index}",
                text=row.content,
                metadata=metadata,
            )

            nodes_with_scores.append(
                NodeWithScore(node=node, score=float(row.similarity))
            )

        logger.debug(f"[VECTOR] Found {len(nodes_with_scores)} results")
        return nodes_with_scores
