from llama_index.core import Settings
from core_logic.embeddings import get_embedding_function
from core_logic.llm_handler import get_llm_client
import logging

logger = logging.getLogger(__name__)

def initialize_settings():
    logger.info("[SETTINGS] Initializing global LlamaIndex Settings")

    Settings.embed_model = get_embedding_function()
    logger.info("[SETTINGS] Embedding model configured")

    Settings.llm = get_llm_client()
    logger.info("[SETTINGS] LLM configured")

    Settings.chunk_size = 500
    Settings.chunk_overlap = 50
    logger.info(f"[SETTINGS] Chunk settings: size={Settings.chunk_size}, overlap={Settings.chunk_overlap}")

    logger.info("[SETTINGS] Global Settings initialization complete")
