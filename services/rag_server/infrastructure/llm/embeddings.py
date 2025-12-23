from llama_index.embeddings.ollama import OllamaEmbedding
import logging
from infrastructure.config.models_config import get_models_config

logger = logging.getLogger(__name__)

def get_embedding_function():
    config = get_models_config()
    ollama_url = config.embedding.base_url
    model_name = config.embedding.model

    logger.info(f"[EMBEDDINGS] Initializing OllamaEmbedding")
    logger.info(f"[EMBEDDINGS] Ollama URL: {ollama_url}")
    logger.info(f"[EMBEDDINGS] Model: {model_name}")

    embedding_function = OllamaEmbedding(
        base_url=ollama_url,
        model_name=model_name
    )

    logger.info(f"[EMBEDDINGS] OllamaEmbedding initialized successfully")
    return embedding_function
