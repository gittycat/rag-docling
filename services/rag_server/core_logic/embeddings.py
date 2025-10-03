from langchain_ollama import OllamaEmbeddings
import logging
from core_logic.env_config import get_required_env

logger = logging.getLogger(__name__)

def get_embedding_function():
    ollama_url = get_required_env("OLLAMA_URL")
    model_name = get_required_env("EMBEDDING_MODEL")

    logger.info(f"[EMBEDDINGS] Initializing OllamaEmbeddings")
    logger.info(f"[EMBEDDINGS] Ollama URL: {ollama_url}")
    logger.info(f"[EMBEDDINGS] Model: {model_name}")

    embedding_function = OllamaEmbeddings(
        base_url=ollama_url,
        model=model_name
    )

    logger.info(f"[EMBEDDINGS] OllamaEmbeddings initialized successfully")
    return embedding_function
