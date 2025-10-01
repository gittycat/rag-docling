import os
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction

def get_embedding_function():
    """
    Create and return ChromaDB's Ollama embedding function.
    Uses nomic-embed-text model (768 dimensions) for text embeddings.
    """
    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    model_name = "nomic-embed-text"

    embedding_function = OllamaEmbeddingFunction(
        url=f"{ollama_url}/api/embeddings",
        model_name=model_name
    )

    return embedding_function
