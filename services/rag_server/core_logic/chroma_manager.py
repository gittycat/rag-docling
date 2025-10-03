import os
from typing import List, Dict
import chromadb
from langchain_chroma import Chroma
from core_logic.embeddings import get_embedding_function
import logging

logger = logging.getLogger(__name__)

COLLECTION_NAME = "documents"

def get_chroma_client():
    chroma_url = os.getenv("CHROMADB_URL", "http://chromadb:8000")
    host = chroma_url.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(chroma_url.split(":")[-1])
    return chromadb.HttpClient(host=host, port=port)


def get_or_create_collection():
    logger.info(f"[CHROMA] Getting or creating collection: {COLLECTION_NAME}")
    client = get_chroma_client()
    logger.info(f"[CHROMA] ChromaDB client initialized")

    embedding_function = get_embedding_function()
    logger.info(f"[CHROMA] Embedding function retrieved")

    vectorstore = Chroma(
        client=client,
        collection_name=COLLECTION_NAME,
        embedding_function=embedding_function
    )
    logger.info(f"[CHROMA] Vectorstore initialized for collection: {COLLECTION_NAME}")

    return vectorstore


def add_documents(collection, documents: List[str], metadatas: List[Dict], ids: List[str]):
    logger.info(f"[CHROMA] Adding {len(documents)} documents to collection")
    logger.info(f"[CHROMA] Document IDs: {ids[:3]}..." if len(ids) > 3 else f"[CHROMA] Document IDs: {ids}")

    # Log first document preview
    if documents:
        preview = documents[0][:100] + "..." if len(documents[0]) > 100 else documents[0]
        logger.info(f"[CHROMA] First document preview: {preview}")

    # LangChain Chroma uses add_texts method
    logger.info(f"[CHROMA] Calling add_texts on vectorstore (will generate embeddings)")
    collection.add_texts(
        texts=documents,
        metadatas=metadatas,
        ids=ids
    )
    logger.info(f"[CHROMA] Successfully added {len(documents)} documents to ChromaDB")


def query_documents(collection, query_text: str, n_results: int = 5) -> Dict:
    # Use similarity_search_with_score for compatible results
    results_with_scores = collection.similarity_search_with_score(
        query=query_text,
        k=n_results
    )

    # Convert LangChain format to ChromaDB-compatible format
    documents = []
    metadatas = []
    distances = []
    ids = []

    for doc, score in results_with_scores:
        documents.append(doc.page_content)
        metadatas.append(doc.metadata)
        # ChromaDB uses distance (lower is better), score from similarity_search is similarity (higher is better)
        # Convert similarity to distance: distance = 1 - similarity (approximate)
        distances.append(1.0 - score if score <= 1.0 else score)
        ids.append(doc.metadata.get('id', ''))

    # Return in ChromaDB query format (nested lists for batch queries)
    return {
        'documents': [documents],
        'metadatas': [metadatas],
        'distances': [distances],
        'ids': [ids]
    }


def delete_document(collection, document_id: str):
    # Get underlying ChromaDB collection for deletion
    chroma_collection = collection._collection

    # Query for all chunks with this document_id
    results = chroma_collection.get(
        where={"document_id": document_id}
    )

    # Delete all matching chunk IDs
    if results and results['ids']:
        chroma_collection.delete(ids=results['ids'])


def list_documents(collection) -> List[Dict]:
    # Access underlying ChromaDB collection
    chroma_collection = collection._collection

    # Get all documents
    results = chroma_collection.get()

    # Group chunks by document_id
    doc_map = {}
    for i, chunk_id in enumerate(results['ids']):
        metadata = results['metadatas'][i] if i < len(results['metadatas']) else {}
        doc_id = metadata.get('document_id', chunk_id)

        if doc_id not in doc_map:
            doc_map[doc_id] = {
                'id': doc_id,
                'file_name': metadata.get('file_name', 'Unknown'),
                'file_type': metadata.get('file_type', ''),
                'path': metadata.get('path', ''),
                'chunks': 0
            }

        doc_map[doc_id]['chunks'] += 1

    return list(doc_map.values())
