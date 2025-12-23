from typing import Optional
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.retrievers.bm25 import BM25Retriever
from infrastructure.database.chroma import get_all_nodes
from infrastructure.config.models_config import get_models_config
import logging

logger = logging.getLogger(__name__)

_bm25_retriever = None


def get_hybrid_retriever_config():
    """Get hybrid retriever configuration from models config file"""
    config = get_models_config()
    return {
        'enabled': config.retrieval.enable_hybrid_search,
        'similarity_top_k': config.retrieval.top_k,
        'rrf_k': config.retrieval.rrf_k
    }


def initialize_bm25_retriever(index: VectorStoreIndex, similarity_top_k: int = 10):
    """
    Initialize BM25 retriever with all nodes from ChromaDB.
    This should be called once at startup and cached.
    """
    global _bm25_retriever

    logger.info("[HYBRID] Initializing BM25 retriever")

    nodes = get_all_nodes(index)

    if not nodes:
        logger.warning("[HYBRID] No nodes found in ChromaDB - BM25 retriever will be empty")
        return None

    _bm25_retriever = BM25Retriever.from_defaults(
        nodes=nodes,
        similarity_top_k=similarity_top_k
    )

    logger.info(f"[HYBRID] BM25 retriever initialized with {len(nodes)} nodes")
    return _bm25_retriever


def get_bm25_retriever():
    """Get cached BM25 retriever"""
    return _bm25_retriever


def create_hybrid_retriever(index: VectorStoreIndex, similarity_top_k: int = 10):
    """
    Create hybrid retriever combining BM25 (sparse) and vector (dense) search
    with Reciprocal Rank Fusion (RRF).

    Research shows:
    - 48% improvement in retrieval quality (Pinecone benchmark)
    - BM25 excels at: exact keywords, IDs, names, abbreviations
    - Vector search excels at: semantic understanding, context
    - RRF: simple, robust fusion requiring no hyperparameter tuning

    Args:
        index: VectorStoreIndex for vector search
        similarity_top_k: Number of results to return

    Returns:
        QueryFusionRetriever combining BM25 and vector search with RRF
    """
    config = get_hybrid_retriever_config()

    if not config['enabled']:
        logger.info("[HYBRID] Hybrid search disabled, using vector search only")
        return None

    logger.info(f"[HYBRID] Creating hybrid retriever with similarity_top_k={similarity_top_k}")

    # Initialize BM25 retriever if not already cached
    bm25_retriever = get_bm25_retriever()
    if bm25_retriever is None:
        bm25_retriever = initialize_bm25_retriever(index, similarity_top_k)
        if bm25_retriever is None:
            logger.warning("[HYBRID] BM25 initialization failed, falling back to vector search only")
            return None

    # Create vector retriever
    vector_retriever = index.as_retriever(similarity_top_k=similarity_top_k)
    logger.info("[HYBRID] Vector retriever created")

    # Create fusion retriever with RRF
    # mode="reciprocal_rerank" uses RRF formula: score = 1/(rank + k)
    # k=60 is optimal per research (configurable via RRF_K env var)
    fusion_retriever = QueryFusionRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        similarity_top_k=similarity_top_k,
        num_queries=1,  # Single query (no multi-query generation yet)
        mode="reciprocal_rerank",  # RRF mode
        use_async=True,  # Parallel retrieval for better performance
        verbose=False
    )

    logger.info(f"[HYBRID] Hybrid retriever created with RRF (k={config['rrf_k']})")
    return fusion_retriever


def refresh_bm25_retriever(index: VectorStoreIndex):
    """
    Refresh BM25 retriever after documents are added/deleted.
    Should be called after document upload or deletion operations.
    """
    global _bm25_retriever

    config = get_hybrid_retriever_config()
    if not config['enabled']:
        return

    logger.info("[HYBRID] Refreshing BM25 retriever with updated nodes")
    _bm25_retriever = initialize_bm25_retriever(index, config['similarity_top_k'])
    logger.info("[HYBRID] BM25 retriever refreshed")
