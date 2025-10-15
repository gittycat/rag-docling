from typing import List, Dict
import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.vector_stores.chroma import ChromaVectorStore
from core_logic.embeddings import get_embedding_function
from core_logic.env_config import get_required_env
import logging

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


def add_documents(index, nodes: List, progress_callback=None):
    logger.info(f"[CHROMA] Adding {len(nodes)} nodes to index")

    if nodes:
        first_text = nodes[0].get_content()
        preview = first_text[:100] + "..." if len(first_text) > 100 else first_text
        logger.info(f"[CHROMA] First node preview: {preview}")

    total_nodes = len(nodes)

    for i, node in enumerate(nodes, 1):
        logger.info(f"[CHROMA] Embedding chunk {i}/{total_nodes}")
        index.insert_nodes([node])

        if progress_callback:
            progress_callback(i, total_nodes)

    logger.info(f"[CHROMA] Successfully added {len(nodes)} nodes to ChromaDB")


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


def list_documents(index) -> List[Dict]:
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
                'chunks': 0
            }

        doc_map[doc_id]['chunks'] += 1

    return list(doc_map.values())


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
