from typing import List, Dict
import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.vector_stores.chroma import ChromaVectorStore
from infrastructure.llm.embeddings import get_embedding_function
from core.config import get_required_env
import logging
import time

logger = logging.getLogger(__name__)

COLLECTION_NAME = "documents"

def get_chroma_client():
    chroma_url = get_required_env("CHROMADB_URL")
    host = chroma_url.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(chroma_url.split(":")[-1])
    return chromadb.HttpClient(host=host, port=port)


def get_or_create_collection():
    logger.info(f"[CHROMA] Getting or creating collection: {COLLECTION_NAME}")
    client = get_chroma_client()
    logger.info(f"[CHROMA] ChromaDB client initialized")

    chroma_collection = client.get_or_create_collection(name=COLLECTION_NAME)
    logger.info(f"[CHROMA] ChromaDB collection retrieved")

    embedding_function = get_embedding_function()
    logger.info(f"[CHROMA] Embedding function retrieved")

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    logger.info(f"[CHROMA] ChromaVectorStore created")

    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        embed_model=embedding_function
    )
    logger.info(f"[CHROMA] VectorStoreIndex initialized for collection: {COLLECTION_NAME}")

    return index


def _insert_node_with_retry(index, node, max_retries=3, base_delay=2.0):
    """
    Insert a node with retry logic for Ollama connection errors.

    Args:
        index: VectorStoreIndex to insert into
        node: TextNode to insert
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff

    Raises:
        Exception: If all retries fail
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            index.insert_nodes([node])
            return  # Success
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()

            # Check if it's an Ollama connection error
            is_connection_error = any(term in error_msg for term in [
                'eof', 'connection', 'timeout', 'refused', 'unavailable'
            ])

            if is_connection_error and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # Exponential backoff
                logger.warning(f"[CHROMA] Ollama connection error (attempt {attempt + 1}/{max_retries}): {str(e)}")
                logger.info(f"[CHROMA] Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                # Not a connection error or last attempt - raise immediately
                raise

    # All retries failed
    raise Exception(f"Failed to embed node after {max_retries} attempts. Last error: {str(last_error)}") from last_error


def add_documents(index, nodes: List, progress_callback=None):
    logger.info(f"[CHROMA] Starting embedding generation and indexing for {len(nodes)} nodes")
    embedding_start = time.time()

    if nodes:
        first_text = nodes[0].get_content()
        preview = first_text[:100] + "..." if len(first_text) > 100 else first_text
        logger.info(f"[CHROMA] First node preview: {preview}")

    total_nodes = len(nodes)

    for i, node in enumerate(nodes, 1):
        node_start = time.time()
        logger.info(f"[CHROMA] Starting embedding for chunk {i}/{total_nodes}")

        try:
            _insert_node_with_retry(index, node, max_retries=3, base_delay=2.0)
        except Exception as e:
            # Add context about which chunk failed
            raise Exception(f"Failed to embed chunk {i}/{total_nodes}: {str(e)}") from e

        node_duration = time.time() - node_start
        elapsed = time.time() - embedding_start
        avg_per_node = elapsed / i
        est_remaining = avg_per_node * (total_nodes - i)

        logger.info(f"[CHROMA] Chunk {i}/{total_nodes} embedded in {node_duration:.2f}s - Elapsed: {elapsed:.1f}s, Est. remaining: {est_remaining:.1f}s")

        if progress_callback:
            progress_callback(i, total_nodes)

    total_duration = time.time() - embedding_start
    avg_per_node = total_duration / len(nodes)
    logger.info(f"[CHROMA] Successfully embedded and indexed {len(nodes)} nodes in {total_duration:.2f}s (avg: {avg_per_node:.2f}s per node)")


def query_documents(index, query_text: str, n_results: int = 5) -> Dict:
    retriever = index.as_retriever(similarity_top_k=n_results)
    nodes = retriever.retrieve(query_text)

    documents = []
    metadatas = []
    distances = []
    ids = []

    for node in nodes:
        documents.append(node.get_content())
        metadatas.append(node.metadata)
        distances.append(1.0 - node.score if hasattr(node, 'score') and node.score else 0.0)
        ids.append(node.node_id)

    return {
        'documents': [documents],
        'metadatas': [metadatas],
        'distances': [distances],
        'ids': [ids]
    }


def delete_document(index, document_id: str):
    chroma_collection = index._vector_store._collection

    results = chroma_collection.get(
        where={"document_id": document_id}
    )

    if results and results['ids']:
        chroma_collection.delete(ids=results['ids'])


def list_documents(index, sort_by: str = 'uploaded_at', sort_order: str = 'desc') -> List[Dict]:
    """
    List all documents with their metadata.

    Args:
        index: VectorStoreIndex to query
        sort_by: Field to sort by ('name', 'chunks', 'uploaded_at'). Default: 'uploaded_at'
        sort_order: Sort order ('asc' or 'desc'). Default: 'desc' (newest first)

    Returns:
        List of document dicts with id, file_name, file_type, path, file_size_bytes,
        chunks, and uploaded_at fields.
    """
    chroma_collection = index._vector_store._collection

    results = chroma_collection.get()

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
                'file_size_bytes': metadata.get('file_size_bytes', 0),
                'uploaded_at': metadata.get('uploaded_at'),  # ISO 8601 timestamp or None for legacy docs
                'chunks': 0
            }

        doc_map[doc_id]['chunks'] += 1

    documents = list(doc_map.values())

    # Sort documents
    reverse = sort_order == 'desc'
    if sort_by == 'name':
        documents.sort(key=lambda d: d.get('file_name', '').lower(), reverse=reverse)
    elif sort_by == 'chunks':
        documents.sort(key=lambda d: d.get('chunks', 0), reverse=reverse)
    elif sort_by == 'uploaded_at':
        # Sort by upload time (None values go to end)
        documents.sort(
            key=lambda d: d.get('uploaded_at') or '',
            reverse=reverse
        )

    return documents


def get_all_nodes(index) -> List[TextNode]:
    """
    Retrieve all nodes from ChromaDB collection for BM25 indexing.
    Returns list of TextNode objects with text content and metadata.
    """
    logger.info("[CHROMA] Retrieving all nodes for BM25 indexing")
    chroma_collection = index._vector_store._collection

    results = chroma_collection.get()

    nodes = []
    if results and results['ids']:
        for i, node_id in enumerate(results['ids']):
            text = results['documents'][i] if i < len(results['documents']) else ""
            metadata = results['metadatas'][i] if i < len(results['metadatas']) else {}

            node = TextNode(
                id_=node_id,
                text=text,
                metadata=metadata
            )
            nodes.append(node)

    logger.info(f"[CHROMA] Retrieved {len(nodes)} nodes for BM25 indexing")
    return nodes


def check_documents_exist(index, file_checks: List[Dict]) -> Dict[str, Dict]:
    """
    Check if documents with given file hashes already exist in ChromaDB.

    Args:
        index: VectorStoreIndex to query
        file_checks: List of dicts with {filename, size, hash}

    Returns:
        Dict mapping filename to status info:
        {
            "filename.pdf": {
                "exists": True/False,
                "document_id": "...",  # if exists
                "reason": "Already uploaded"  # if exists
            }
        }
    """
    logger.info(f"[CHROMA] Checking {len(file_checks)} files for duplicates")
    chroma_collection = index._vector_store._collection

    # Get all documents from ChromaDB
    results = chroma_collection.get()

    # Build map of file_hash -> document info
    hash_to_doc = {}
    if results and results['ids']:
        for i, node_id in enumerate(results['ids']):
            metadata = results['metadatas'][i] if i < len(results['metadatas']) else {}
            file_hash = metadata.get('file_hash')

            if file_hash and file_hash not in hash_to_doc:
                # Store first occurrence of each hash
                hash_to_doc[file_hash] = {
                    "document_id": metadata.get('document_id'),
                    "file_name": metadata.get('file_name', 'Unknown'),
                    "file_size_bytes": metadata.get('file_size_bytes', 0)
                }

    logger.info(f"[CHROMA] Found {len(hash_to_doc)} unique document hashes in database")

    # Check each file
    result = {}
    for file_check in file_checks:
        filename = file_check['filename']
        file_hash = file_check['hash']

        if file_hash in hash_to_doc:
            doc_info = hash_to_doc[file_hash]
            result[filename] = {
                "exists": True,
                "document_id": doc_info["document_id"],
                "existing_filename": doc_info["file_name"],
                "reason": f"Duplicate of '{doc_info['file_name']}' (already uploaded)"
            }
            logger.info(f"[CHROMA] Found duplicate: {filename} matches {doc_info['file_name']}")
        else:
            result[filename] = {
                "exists": False
            }

    duplicates_count = sum(1 for v in result.values() if v["exists"])
    logger.info(f"[CHROMA] Duplicate check complete: {duplicates_count}/{len(file_checks)} files are duplicates")

    return result
