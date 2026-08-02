"""Tests for document deletion cleaning up ChromaDB vectors (docs/suggestions.md 4.1).

Covers:
- vector_store.delete_document_vectors() deletes by the "document_id" metadata key
  (via ChromaVectorStore.delete(ref_doc_id=...), which llama-index implements as
  collection.delete(where={"document_id": ref_doc_id}))
- vector_store.list_chroma_document_ids() paginates over the collection
- document_service.delete_document() deletes vectors before the Postgres row,
  and aborts the Postgres delete when vector deletion fails
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.search import vector_store
from services import document_service


@pytest.fixture(autouse=True)
def _reset_vector_store_singleton():
    vector_store.reset_vector_store()
    yield
    vector_store.reset_vector_store()


def test_delete_document_vectors_deletes_by_ref_doc_id():
    """document_id must be passed through as ChromaVectorStore's ref_doc_id, which
    llama-index resolves to collection.delete(where={"document_id": ref_doc_id}) —
    the metadata key add_document_metadata_to_chunks() writes during ingestion."""
    mock_store = MagicMock()

    with patch("infrastructure.search.vector_store.get_vector_store", return_value=mock_store):
        vector_store.delete_document_vectors("doc-123")

    mock_store.delete.assert_called_once_with(ref_doc_id="doc-123")


def test_delete_document_vectors_propagates_chroma_errors():
    """A ChromaDB connection failure must surface to the caller, not be swallowed."""
    mock_store = MagicMock()
    mock_store.delete.side_effect = ConnectionError("chromadb unreachable")

    with patch("infrastructure.search.vector_store.get_vector_store", return_value=mock_store):
        with pytest.raises(ConnectionError):
            vector_store.delete_document_vectors("doc-123")


def _mock_config():
    config = MagicMock()
    config.chromadb.collection = "document_chunks"
    return config


def test_list_chroma_document_ids_paginates_and_dedupes():
    fake_collection = MagicMock()
    page_size = 1000
    first_page = {"metadatas": [{"document_id": "a"}] * page_size}
    # Second page has fewer than page_size rows -> loop stops after this page
    second_page = {"metadatas": [{"document_id": "b"}, {"document_id": "a"}, {}]}
    fake_collection.get.side_effect = [first_page, second_page]
    fake_client = MagicMock()
    fake_client.get_or_create_collection.return_value = fake_collection

    with patch("infrastructure.search.vector_store.get_chroma_client", return_value=fake_client), \
         patch("infrastructure.search.vector_store.get_models_config", return_value=_mock_config()):
        result = vector_store.list_chroma_document_ids()

    assert result == {"a", "b"}
    assert fake_collection.get.call_count == 2


def test_list_chroma_document_ids_empty_collection():
    fake_collection = MagicMock()
    fake_collection.get.return_value = {"metadatas": []}
    fake_client = MagicMock()
    fake_client.get_or_create_collection.return_value = fake_collection

    with patch("infrastructure.search.vector_store.get_chroma_client", return_value=fake_client), \
         patch("infrastructure.search.vector_store.get_models_config", return_value=_mock_config()):
        result = vector_store.list_chroma_document_ids()

    assert result == set()


@pytest.mark.asyncio
async def test_delete_document_service_deletes_vectors_before_postgres_row():
    document_id = UUID("11111111-1111-1111-1111-111111111111")
    call_order = []

    def fake_delete_vectors(doc_id):
        call_order.append(("vectors", doc_id))

    async def fake_db_delete(session, doc_id):
        call_order.append(("postgres", doc_id))
        return True

    fake_session = AsyncMock()

    with patch("services.document_service.delete_document_vectors", side_effect=fake_delete_vectors) as mock_vec, \
         patch("services.document_service.db_docs.delete_document", side_effect=fake_db_delete) as mock_db:
        result = await document_service.delete_document(fake_session, document_id)

    assert result is True
    assert call_order == [("vectors", str(document_id)), ("postgres", document_id)]
    mock_vec.assert_called_once_with(str(document_id))
    mock_db.assert_called_once_with(fake_session, document_id)


@pytest.mark.asyncio
async def test_delete_document_service_aborts_postgres_delete_on_vector_failure():
    """If ChromaDB is unreachable, the Postgres row must NOT be deleted — the
    document stays visible and the caller must not report success."""
    document_id = UUID("22222222-2222-2222-2222-222222222222")
    fake_session = AsyncMock()

    with patch(
        "services.document_service.delete_document_vectors",
        side_effect=ConnectionError("chromadb unreachable"),
    ), patch("services.document_service.db_docs.delete_document", new=AsyncMock()) as mock_db:
        with pytest.raises(ConnectionError):
            await document_service.delete_document(fake_session, document_id)

    mock_db.assert_not_called()
