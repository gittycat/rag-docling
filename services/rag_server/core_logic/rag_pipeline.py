from typing import Dict, List
from core_logic.chroma_manager import get_or_create_collection, query_documents
from core_logic.llm_handler import generate_response

def query_rag(query_text: str, n_results: int = 3) -> Dict:
    """
    End-to-end RAG query pipeline.

    Steps:
    1. Get ChromaDB collection
    2. Query for similar documents (embeddings generated automatically)
    3. Extract relevant context from results
    4. Generate LLM response using context
    5. Return answer with sources

    Args:
        query_text: User's question
        n_results: Number of similar documents to retrieve

    Returns:
        Dictionary with 'answer' and 'sources' keys
    """
    # Step 1: Get collection
    collection = get_or_create_collection()

    # Step 2: Query for similar documents
    results = query_documents(collection, query_text, n_results=n_results)

    # Step 3: Extract context and sources
    context_docs = []
    sources = []

    if results['documents'] and len(results['documents'][0]) > 0:
        for i, doc in enumerate(results['documents'][0]):
            context_docs.append(doc)

            # Extract source information
            metadata = results['metadatas'][0][i] if i < len(results['metadatas'][0]) else {}
            source = {
                'document_name': metadata.get('file_name', 'Unknown'),
                'excerpt': doc[:200] + '...' if len(doc) > 200 else doc,
                'path': metadata.get('path', ''),
                'distance': results['distances'][0][i] if i < len(results['distances'][0]) else None
            }
            sources.append(source)

    # Combine context
    context = "\n\n".join(context_docs) if context_docs else ""

    # Step 4: Generate response
    answer = generate_response(query_text, context)

    # Step 5: Return result
    return {
        'answer': answer,
        'sources': sources,
        'query': query_text
    }
