from typing import Dict, List, Optional, Generator
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.query_engine import RetrieverQueryEngine
from infrastructure.database.chroma import get_or_create_collection
from infrastructure.llm.prompts import get_system_prompt, get_context_prompt, get_condense_prompt
from core.config import get_optional_env
from services.chat import get_or_create_chat_memory
from services.hybrid_retriever import create_hybrid_retriever, get_hybrid_retriever_config
import logging
import json

logger = logging.getLogger(__name__)

def reranker_config() -> Dict:
    """Get reranker configuration from environment variables"""
    return {
        'enabled': get_optional_env('ENABLE_RERANKER', 'true').lower() == 'true',
        'model': get_optional_env('RERANKER_MODEL', 'cross-encoder/ms-marco-MiniLM-L-6-v2'),
        'retrieval_top_k': int(get_optional_env('RETRIEVAL_TOP_K', '10'))
    }

def create_reranker_postprocessors() -> Optional[List]:
    """Create reranker with top-n selection"""
    config = reranker_config()

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
    config = reranker_config()
    hybrid_config = get_hybrid_retriever_config()

    # Get LlamaIndex native prompts
    system_prompt = get_system_prompt()
    context_prompt = get_context_prompt()
    condense_prompt = get_condense_prompt()  # None = use LlamaIndex default

    memory = get_or_create_chat_memory(session_id)

    # Always use configured retrieval_top_k for better coverage with granular Docling chunks
    retrieval_top_k = config['retrieval_top_k']
    logger.info(f"[RAG] Using retrieval_top_k={retrieval_top_k}, reranker_enabled={config['enabled']}, hybrid_search_enabled={hybrid_config['enabled']}, session_id={session_id}")

    # Create hybrid retriever if enabled (combines BM25 + Vector with RRF)
    retriever = create_hybrid_retriever(index, similarity_top_k=retrieval_top_k)

    # Create chat engine based on whether hybrid search is enabled
    if retriever is not None:
        logger.info("[RAG] Using hybrid retriever (BM25 + Vector + RRF)")
        # CondensePlusContextChatEngine requires 'retriever' directly (not query_engine)
        chat_engine = CondensePlusContextChatEngine.from_defaults(
            retriever=retriever,
            memory=memory,
            node_postprocessors=create_reranker_postprocessors(),
            system_prompt=system_prompt,
            context_prompt=context_prompt,
            condense_prompt=condense_prompt,
            verbose=False
        )
    else:
        logger.info("[RAG] Using vector retriever only")
        # Use standard as_chat_engine when not using custom retriever
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

    sources = _extract_sources(response.source_nodes)

    logger.info(f"[RAG] Query completed. Sources returned: {len(sources)}")

    return {
        'answer': str(response),
        'sources': sources,
        'query': query_text,
        'session_id': session_id
    }


def _extract_sources(source_nodes) -> List[Dict]:
    """Extract source information from response nodes."""
    sources = []
    seen_docs = set()  # Deduplicate by document_id

    for node in source_nodes:
        metadata = node.metadata
        doc_id = metadata.get('document_id')

        # Deduplicate sources by document_id
        if doc_id and doc_id in seen_docs:
            continue
        if doc_id:
            seen_docs.add(doc_id)

        full_text = node.get_content()
        source = {
            'document_id': doc_id,
            'document_name': metadata.get('file_name', 'Unknown'),
            'excerpt': full_text[:200] + '...' if len(full_text) > 200 else full_text,
            'full_text': full_text,
            'path': metadata.get('path', ''),
            'score': node.score if hasattr(node, 'score') and node.score else None
        }
        sources.append(source)

    return sources


def _create_chat_engine(index, session_id: str):
    """Create chat engine with hybrid search and reranking."""
    config = reranker_config()
    hybrid_config = get_hybrid_retriever_config()

    system_prompt = get_system_prompt()
    context_prompt = get_context_prompt()
    condense_prompt = get_condense_prompt()

    memory = get_or_create_chat_memory(session_id)
    retrieval_top_k = config['retrieval_top_k']

    logger.info(f"[RAG] Creating chat engine: retrieval_top_k={retrieval_top_k}, reranker={config['enabled']}, hybrid={hybrid_config['enabled']}")

    retriever = create_hybrid_retriever(index, similarity_top_k=retrieval_top_k)

    if retriever is not None:
        logger.info("[RAG] Using hybrid retriever (BM25 + Vector + RRF)")
        chat_engine = CondensePlusContextChatEngine.from_defaults(
            retriever=retriever,
            memory=memory,
            node_postprocessors=create_reranker_postprocessors(),
            system_prompt=system_prompt,
            context_prompt=context_prompt,
            condense_prompt=condense_prompt,
            verbose=False
        )
    else:
        logger.info("[RAG] Using vector retriever only")
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

    return chat_engine


def query_rag_stream(query_text: str, session_id: str) -> Generator[str, None, None]:
    """
    Stream RAG query response as Server-Sent Events.

    Yields SSE-formatted strings:
    - event: token, data: {"token": "..."}
    - event: sources, data: {"sources": [...], "session_id": "..."}
    - event: done, data: {}

    On error:
    - event: error, data: {"error": "..."}
    """
    try:
        index = get_or_create_collection()
        chat_engine = _create_chat_engine(index, session_id)

        logger.info(f"[RAG_STREAM] Starting streaming query, session_id={session_id}")

        # Use stream_chat for token-by-token streaming
        streaming_response = chat_engine.stream_chat(query_text)

        # Stream tokens
        for token in streaming_response.response_gen:
            yield f"event: token\ndata: {json.dumps({'token': token})}\n\n"

        # After streaming completes, extract sources
        sources = _extract_sources(streaming_response.source_nodes)
        logger.info(f"[RAG_STREAM] Streaming complete. Sources: {len(sources)}")

        # Send sources
        yield f"event: sources\ndata: {json.dumps({'sources': sources, 'session_id': session_id})}\n\n"

        # Send done event
        yield f"event: done\ndata: {{}}\n\n"

    except Exception as e:
        logger.error(f"[RAG_STREAM] Error during streaming: {str(e)}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
