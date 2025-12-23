"""
RAG Pipelines

High-level pipelines for document processing and query inference:
- ingestion: Complete document processing flow (chunking → embedding → indexing)
- inference: Complete RAG query flow (retrieval → reranking → generation)
"""

from pipelines.ingestion import (
    ingest_document,
    extract_file_metadata,
    SUPPORTED_EXTENSIONS,
)

from pipelines.inference import (
    query_rag,
    query_rag_stream,
    get_or_create_chat_memory,
    clear_session_memory,
    get_chat_history,
    initialize_bm25_retriever,
    refresh_bm25_retriever,
    create_reranker_postprocessor,
)

__all__ = [
    # Ingestion
    'ingest_document',
    'extract_file_metadata',
    'SUPPORTED_EXTENSIONS',
    # Inference
    'query_rag',
    'query_rag_stream',
    'get_or_create_chat_memory',
    'clear_session_memory',
    'get_chat_history',
    'initialize_bm25_retriever',
    'refresh_bm25_retriever',
    'create_reranker_postprocessor',
]
