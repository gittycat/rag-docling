import os
from langchain_ollama import OllamaEmbeddings

def get_embedding_function():
    """
    Create and return LangChain's Ollama embedding function.
    Uses nomic-embed-text model (768 dimensions) for text embeddings.

    This replaces ChromaDB's OllamaEmbeddingFunction with LangChain's
    implementation for better integration with LangChain ecosystem.
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    model_name = "nomic-embed-text"

    embedding_function = OllamaEmbeddings(
        base_url=ollama_url,
        model=model_name
    )

    return embedding_function
