import os
import sys
import logging
from llama_index.core import Settings

logger = logging.getLogger(__name__)


def get_required_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        print(f"ERROR: Required environment variable '{var_name}' is not set.", file=sys.stderr)
        print(f"Please define {var_name} in docker-compose.yml", file=sys.stderr)
        sys.exit(1)
    return value


def get_optional_env(var_name: str, default: str = "") -> str:
    return os.getenv(var_name, default)


def initialize_settings():
    """Initialize global LlamaIndex Settings"""
    from infrastructure.llm.embeddings import get_embedding_function
    from infrastructure.llm.handler import get_llm_client

    logger.info("[SETTINGS] Initializing global LlamaIndex Settings")

    Settings.embed_model = get_embedding_function()
    logger.info("[SETTINGS] Embedding model configured")

    Settings.llm = get_llm_client()
    logger.info("[SETTINGS] LLM configured")

    Settings.chunk_size = 500
    Settings.chunk_overlap = 50
    logger.info(f"[SETTINGS] Chunk settings: size={Settings.chunk_size}, overlap={Settings.chunk_overlap}")

    logger.info("[SETTINGS] Global Settings initialization complete")
