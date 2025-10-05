from typing import Dict, List, Optional
from llama_index.core import PromptTemplate
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank
from core_logic.chroma_manager import get_or_create_collection
from core_logic.llm_handler import get_prompt_template
from core_logic.env_config import get_optional_env
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
    """Create combined reranker strategy with threshold-based filtering"""
    config = get_reranker_config()

    if not config['enabled']:
        logger.info("[RERANKER] Reranking disabled")
        return None

    logger.info(f"[RERANKER] Initializing with model: {config['model']}")
    logger.info(f"[RERANKER] Similarity threshold: {config['similarity_threshold']}")

    postprocessors = [
        SentenceTransformerRerank(
            model=config['model'],
            top_n=config['retrieval_top_k']
        ),
        SimilarityPostprocessor(
            similarity_cutoff=config['similarity_threshold']
        )
    ]

    logger.info("[RERANKER] Postprocessors initialized successfully")
    return postprocessors

def query_rag(query_text: str, n_results: int = 3) -> Dict:
    index = get_or_create_collection()
    config = get_reranker_config()

    prompt_template_str = get_prompt_template()
    qa_prompt = PromptTemplate(prompt_template_str)

    retrieval_top_k = config['retrieval_top_k'] if config['enabled'] else n_results
    logger.info(f"[RAG] Using retrieval_top_k={retrieval_top_k}, reranker_enabled={config['enabled']}")

    query_engine = index.as_query_engine(
        similarity_top_k=retrieval_top_k,
        node_postprocessors=create_reranker_postprocessors(),
        text_qa_template=qa_prompt
    )

    response = query_engine.query(query_text)

    sources = []
    for node in response.source_nodes:
        metadata = node.metadata
        source = {
            'document_name': metadata.get('file_name', 'Unknown'),
            'excerpt': node.get_content()[:200] + '...' if len(node.get_content()) > 200 else node.get_content(),
            'path': metadata.get('path', ''),
            'distance': 1.0 - node.score if hasattr(node, 'score') and node.score else None
        }
        sources.append(source)

    logger.info(f"[RAG] Query completed. Sources returned: {len(sources)}")

    return {
        'answer': str(response),
        'sources': sources,
        'query': query_text
    }
