from typing import Dict
from llama_index.core import PromptTemplate
from core_logic.chroma_manager import get_or_create_collection
from core_logic.llm_handler import get_prompt_template

def query_rag(query_text: str, n_results: int = 3) -> Dict:
    index = get_or_create_collection()

    prompt_template_str = get_prompt_template()
    qa_prompt = PromptTemplate(prompt_template_str)

    query_engine = index.as_query_engine(
        similarity_top_k=n_results,
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

    return {
        'answer': str(response),
        'sources': sources,
        'query': query_text
    }
