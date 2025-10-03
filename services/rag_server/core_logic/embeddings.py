import os
from langchain_ollama import OllamaEmbeddings
import logging

logger = logging.getLogger(__name__)

def get_embedding_function():
    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    model_name = "nomic-embed-text"

    logger.info(f"[EMBEDDINGS] Initializing OllamaEmbeddings")
    logger.info(f"[EMBEDDINGS] Ollama URL: {ollama_url}")
    logger.info(f"[EMBEDDINGS] Model: {model_name}")

    embedding_function = OllamaEmbeddings(
        base_url=ollama_url,
        model=model_name
    )

    logger.info(f"[EMBEDDINGS] OllamaEmbeddings initialized successfully")
    return embedding_function
