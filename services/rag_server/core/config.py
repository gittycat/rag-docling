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


def check_embedding_endpoint_reachable():
    """Fail fast with a clear message when a configured TEI endpoint is down."""
    import httpx
    from infrastructure.config.models_config import get_models_config

    config = get_models_config()
    endpoints = {
        model_config.base_url
        for model_config in (config.llm, config.embedding)
        if model_config.provider == "tei" and model_config.base_url
    }
    for url in endpoints:
        try:
            httpx.get(f"{url.rstrip('/')}/health", timeout=5)
        except httpx.HTTPError:
            print(
                f"ERROR: TEI is not reachable at {url} (required by the active "
                f"llm/embedding provider in config.yml).\n"
                "Start the tei service ('docker compose up -d tei'), then restart the "
                "services.",
                file=sys.stderr,
            )
            sys.exit(1)
    logger.info("[SETTINGS] TEI reachable at: %s", ", ".join(sorted(endpoints)) or "n/a")


def check_embedding_dimension_match():
    """Guard against silent retrieval corruption from switching embedding models.

    document_chunks.embedding is declared vector(N) where N is
    vector_store.dimension, so the active embedding model must produce exactly
    that many dimensions. Postgres would reject the mismatched INSERT anyway, but
    only once the first document is ingested — this fails at startup instead.

    Deliberately not a Postgres round-trip: this runs synchronously from inside
    the FastAPI startup coroutine (and from the worker before its loop exists),
    where bridging to the async engine would deadlock or bind the pool to a
    throwaway event loop. Server-side verification of the extension, the column
    and the diskann index lives in probe_vector_index(), on the health surface.
    """
    from infrastructure.config.models_config import get_models_config

    config = get_models_config()
    schema_dim = config.vector_store.dimension

    try:
        active_dim = len(Settings.embed_model.get_text_embedding("dim-probe"))
    except Exception as e:
        logger.warning(
            f"[SETTINGS] Could not probe the embedding model's dimension, skipping check: {e}"
        )
        return

    if schema_dim != active_dim:
        raise ValueError(
            f"Embedding dimension mismatch: document_chunks.embedding is declared "
            f"vector({schema_dim}) (config.yml vector_store.dimension), but the active "
            f"embedding model '{config.embedding.model}' produces {active_dim}-dimensional "
            f"vectors. Update vector_store.dimension, re-create the schema and re-ingest "
            f"every document, or switch the embedding model back."
        )


def initialize_settings():
    """Initialize global LlamaIndex Settings"""
    from infrastructure.llm.embeddings import get_embedding_function
    from infrastructure.llm.factory import get_llm_client

    logger.info("[SETTINGS] Initializing global LlamaIndex Settings")

    check_embedding_endpoint_reachable()

    Settings.embed_model = get_embedding_function()
    logger.info("[SETTINGS] Embedding model configured")

    check_embedding_dimension_match()
    logger.info("[SETTINGS] Embedding dimension check passed")

    Settings.llm = get_llm_client()
    logger.info("[SETTINGS] LLM configured")

    Settings.chunk_size = 500
    Settings.chunk_overlap = 50
    logger.info(f"[SETTINGS] Chunk settings: size={Settings.chunk_size}, overlap={Settings.chunk_overlap}")

    logger.info("[SETTINGS] Global Settings initialization complete")
