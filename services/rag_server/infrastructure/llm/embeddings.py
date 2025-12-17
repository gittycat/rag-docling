from llama_index.embeddings.ollama import OllamaEmbedding
import logging
from core.config import get_required_env

logger = logging.getLogger(__name__)

def get_embedding_function():
    ollama_url = get_required_env("OLLAMA_URL")
    model_name = get_required_env("EMBEDDING_MODEL")

    logger.info(f"[EMBEDDINGS] Initializing OllamaEmbedding")
    logger.info(f"[EMBEDDINGS] Ollama URL: {ollama_url}")
    logger.info(f"[EMBEDDINGS] Model: {model_name}")

    embedding_function = OllamaEmbedding(
        base_url=ollama_url,
        model_name=model_name
    )

    logger.info(f"[EMBEDDINGS] OllamaEmbedding initialized successfully")
    return embedding_function
