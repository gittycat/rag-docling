"""Tests for the document deletion path (docs/suggestions.md 4.1).

Embeddings live in document_chunks.embedding, so deletion is one statement
against `documents` and the ON DELETE CASCADE on document_chunks.document_id
removes the chunks and their vectors with it. There is no second store to clean
up and therefore no partial-delete state to order around.

Covers:
- document_service.delete_document() is a straight delegation to the Postgres
  delete — no vector-store step to fail between the two
- infrastructure.database.documents.delete_document() issues exactly one DELETE,
  against documents, and reports whether a row was actually removed
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.database import documents as db_docs
from services import document_service


@pytest.mark.asyncio
async def test_delete_document_service_delegates_to_postgres():
    document_id = UUID("11111111-1111-1111-1111-111111111111")
    fake_session = AsyncMock()

    with patch("services.document_service.db_docs.delete_document", new=AsyncMock(return_value=True)) as mock_db:
        result = await document_service.delete_document(fake_session, document_id)

    assert result is True
    mock_db.assert_awaited_once_with(fake_session, document_id)


@pytest.mark.asyncio
async def test_delete_document_service_reports_missing_document():
    """A delete that removed nothing must not be reported as success."""
    document_id = UUID("22222222-2222-2222-2222-222222222222")
    fake_session = AsyncMock()

    with patch("services.document_service.db_docs.delete_document", new=AsyncMock(return_value=False)):
        result = await document_service.delete_document(fake_session, document_id)

    assert result is False


def _session_with_rowcount(rowcount):
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = rowcount
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_db_delete_document_issues_a_single_delete_on_documents():
    """Chunks and embeddings go via the FK cascade, so the row delete is the only
    statement — a second explicit delete would mean the cascade isn't relied on."""
    document_id = UUID("33333333-3333-3333-3333-333333333333")
    session = _session_with_rowcount(1)

    result = await db_docs.delete_document(session, document_id)

    assert result is True
    assert session.execute.await_count == 1
    statement = session.execute.await_args.args[0]
    compiled = str(statement).lower()
    assert compiled.startswith("delete from documents")
    assert "document_chunks" not in compiled


@pytest.mark.asyncio
async def test_db_delete_document_returns_false_when_no_row_matched():
    session = _session_with_rowcount(0)

    result = await db_docs.delete_document(session, UUID("44444444-4444-4444-4444-444444444444"))

    assert result is False
