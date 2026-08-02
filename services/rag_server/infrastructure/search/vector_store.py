"""ChromaDB vector store wrapper for LlamaIndex integration."""

import logging
import os
from typing import Optional

from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb

from infrastructure.config.models_config import get_models_config

logger = logging.getLogger(__name__)

_chroma_client: Optional[chromadb.HttpClient] = None
_vector_store: Optional[ChromaVectorStore] = None
_vector_index: Optional[VectorStoreIndex] = None


def get_chroma_client() -> chromadb.HttpClient:
    """Get or create the ChromaDB HTTP client singleton."""
    global _chroma_client
    if _chroma_client is None:
        host = os.getenv("CHROMADB_HOST", "localhost")
        port = int(os.getenv("CHROMADB_PORT", "8000"))

        _chroma_client = chromadb.HttpClient(host=host, port=port)
        logger.info(f"Created ChromaDB client connection (host={host}, port={port})")
    return _chroma_client


def get_vector_store() -> ChromaVectorStore:
    """Get or create the ChromaVectorStore singleton."""
    global _vector_store
    if _vector_store is None:
        config = get_models_config()
        collection_name = config.chromadb.collection

        chroma_client = get_chroma_client()
        chroma_collection = chroma_client.get_or_create_collection(collection_name)

        _vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        logger.info(f"Created ChromaVectorStore (collection={collection_name})")
    return _vector_store


def get_vector_index() -> VectorStoreIndex:
    """Get or create the VectorStoreIndex singleton."""
    global _vector_index
    if _vector_index is None:
        vector_store = get_vector_store()
        _vector_index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        logger.info("Created VectorStoreIndex from ChromaVectorStore")
    return _vector_index


def reset_vector_store() -> None:
    """Reset the vector store singletons (for testing)."""
    global _vector_store, _vector_index
    _vector_store = None
    _vector_index = None


def delete_document_vectors(document_id: str) -> None:
    """Delete all ChromaDB vectors for a document, keyed on the "document_id"
    metadata field written by add_document_metadata_to_chunks() during ingestion.

    Chroma's delete(where=...) is idempotent: a document with no vectors (already
    deleted, or never indexed) is a silent no-op, not an error. Connection/HTTP
    errors from the Chroma client propagate to the caller.
    """
    get_vector_store().delete(ref_doc_id=document_id)


def list_chroma_document_ids() -> set[str]:
    """Return the distinct document_id values present in the Chroma collection.

    Used by the vector-reconciliation recipe to find vectors whose owning
    document no longer exists in Postgres (e.g. deleted before this fix shipped).
    """
    collection = get_chroma_client().get_or_create_collection(
        get_models_config().chromadb.collection
    )
    document_ids: set[str] = set()
    offset = 0
    page_size = 1000
    while True:
        page = collection.get(include=["metadatas"], limit=page_size, offset=offset)
        metadatas = page.get("metadatas") or []
        if not metadatas:
            break
        for md in metadatas:
            doc_id = (md or {}).get("document_id")
            if doc_id:
                document_ids.add(doc_id)
        if len(metadatas) < page_size:
            break
        offset += page_size
    return document_ids
