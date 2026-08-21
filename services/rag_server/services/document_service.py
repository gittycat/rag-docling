"""Document deletion service.

Single entry point for both call sites that delete a document (the HTTP route
and the task worker's pre-retry reset).
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database import documents as db_docs

logger = logging.getLogger(__name__)


async def delete_document(session: AsyncSession, document_id: UUID) -> bool:
    """Delete a document: one statement, chunks and their embeddings CASCADE.

    Embeddings live in document_chunks.embedding, so the existing ON DELETE
    CASCADE on document_chunks.document_id removes them with the row. There is
    no second store to keep in sync and therefore no partial-delete state to
    order around: the delete either commits whole or not at all.
    """
    return await db_docs.delete_document(session, document_id)
