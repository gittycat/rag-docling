"""Document deletion service - coordinates ChromaDB and Postgres cleanup.

Single entry point for both call sites that delete a document (the HTTP route
and the task worker's pre-retry reset), so vector cleanup isn't duplicated.
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import documents as db_docs
from infrastructure.search.vector_store import delete_document_vectors

logger = logging.getLogger(__name__)


async def delete_document(session: AsyncSession, document_id: UUID) -> bool:
    """Delete a document: ChromaDB vectors first, then the Postgres row (chunks CASCADE).

    Vectors are removed before the Postgres row on purpose. If ChromaDB is
    unreachable, this raises and the Postgres row is left untouched — the
    document stays visible and the delete is retryable. The alternative
    ordering (Postgres first) would report "deleted" while orphaned vectors
    remain retrievable, which is the exact bug this function exists to fix.
    The tradeoff: a Postgres failure *after* a successful vector delete can
    leave a document with no vectors but still listed — a silent dead entry,
    which is a much smaller problem than a phantom-retrievable one.
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, delete_document_vectors, str(document_id))
    return await db_docs.delete_document(session, document_id)
