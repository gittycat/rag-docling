from typing import Dict, List, Optional
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank
from core_logic.chroma_manager import get_or_create_collection
from core_logic.llm_handler import get_system_prompt, get_context_prompt, get_condense_prompt
from core_logic.env_config import get_optional_env
from core_logic.chat_memory import get_or_create_chat_memory
import logging

logger = logging.getLogger(__name__)

def get_reranker_config() -> Dict:
    """Get reranker configuration from environment variables"""
    return {
        'enabled': get_optional_env('ENABLE_RERANKER', 'true').lower() == 'true',
        'model': get_optional_env('RERANKER_MODEL', 'cross-encoder/ms-marco-MiniLM-L-6-v2'),
        'similarity_threshold': float(get_optional_env('RERANKER_SIMILARITY_THRESHOLD', '0.65')),
        'retrieval_top_k': int(get_optional_env('RETRIEVAL_TOP_K', '10'))
    }

def create_reranker_postprocessors() -> Optional[List]:
    """Create reranker with top-n selection"""
    config = get_reranker_config()

    if not config['enabled']:
        logger.info("[RERANKER] Reranking disabled")
        return None

    logger.info(f"[RERANKER] Initializing with model: {config['model']}")
    # Use top_n to select best reranked nodes (usually 5-7 for good coverage)
    top_n = max(5, config['retrieval_top_k'] // 2)  # Return half of retrieved, min 5
    logger.info(f"[RERANKER] Returning top {top_n} nodes after reranking")

    postprocessors = [
        SentenceTransformerRerank(
            model=config['model'],
            top_n=top_n
        )
    ]

    logger.info("[RERANKER] Postprocessor initialized successfully")
    return postprocessors

def query_rag(query_text: str, session_id: str, n_results: int = 3) -> Dict:
    index = get_or_create_collection()
    config = get_reranker_config()

    # Get LlamaIndex native prompts
    system_prompt = get_system_prompt()
    context_prompt = get_context_prompt()
    condense_prompt = get_condense_prompt()  # None = use LlamaIndex default

    # Get or create chat memory for this session
    memory = get_or_create_chat_memory(session_id)

    # Always use configured retrieval_top_k for better coverage with granular Docling chunks
    retrieval_top_k = config['retrieval_top_k']
    logger.info(f"[RAG] Using retrieval_top_k={retrieval_top_k}, reranker_enabled={config['enabled']}, session_id={session_id}")

    # Use chat engine for conversational RAG with memory (LlamaIndex native approach)
    chat_engine = index.as_chat_engine(
        chat_mode="condense_plus_context",
        memory=memory,
        similarity_top_k=retrieval_top_k,
        node_postprocessors=create_reranker_postprocessors(),
        system_prompt=system_prompt,
        context_prompt=context_prompt,
        condense_prompt=condense_prompt,
        verbose=False
    )

    response = chat_engine.chat(query_text)

    logger.info(f"[RAG] Retrieved {len(response.source_nodes)} nodes for context")

    if response.source_nodes:
        total_context_length = 0
        for i, node in enumerate(response.source_nodes):
            node_text = node.get_content()
            total_context_length += len(node_text)
            score_info = f" (score: {node.score:.4f})" if hasattr(node, 'score') and node.score else ""
            logger.debug(f"[RAG] Node {i+1}{score_info}: {node_text[:150]}...")

        logger.info(f"[RAG] Total context length: {total_context_length} characters ({len(response.source_nodes)} nodes)")
    else:
        logger.warning("[RAG] No context nodes retrieved - LLM will respond without context")

    sources = []
    for node in response.source_nodes:
        metadata = node.metadata
        full_text = node.get_content()
        source = {
            'document_name': metadata.get('file_name', 'Unknown'),
            'excerpt': full_text[:200] + '...' if len(full_text) > 200 else full_text,
            'full_text': full_text,
            'path': metadata.get('path', ''),
            'distance': 1.0 - node.score if hasattr(node, 'score') and node.score else None
        }
        sources.append(source)

    logger.info(f"[RAG] Query completed. Sources returned: {len(sources)}")

    return {
        'answer': str(response),
        'sources': sources,
        'query': query_text,
        'session_id': session_id
    }
