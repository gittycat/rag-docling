from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.storage.chat_store import SimpleChatStore
from llama_index.core import Settings
from typing import Dict
import logging

logger = logging.getLogger(__name__)

# Global in-memory chat store (persists across requests within same process)
_chat_store = SimpleChatStore()

# Cache of memory buffers per session
_memory_cache: Dict[str, ChatMemoryBuffer] = {}

def get_token_limit_for_chat_history() -> int:
    """
    Get the token limit for chat history based on the LLM's context window.

    Strategy:
    - Try to introspect model's context_window from Settings.llm
    - Reserve ~50% for chat history, ~40% for retrieved context, ~10% for response
    - Fallback to safe default of 3000 tokens if introspection unavailable
    """
    try:
        llm = Settings.llm

        # Check if LLM has metadata about context window
        if hasattr(llm, 'metadata') and hasattr(llm.metadata, 'context_window'):
            context_window = llm.metadata.context_window
            logger.info(f"[CHAT_MEMORY] Detected model context window: {context_window} tokens")

            # Allocate 50% for chat history
            token_limit = int(context_window * 0.5)
            logger.info(f"[CHAT_MEMORY] Allocating {token_limit} tokens for chat history (50% of context window)")
            return token_limit

        # Check if LLM has context_window as direct attribute
        if hasattr(llm, 'context_window'):
            context_window = llm.context_window
            logger.info(f"[CHAT_MEMORY] Detected model context window: {context_window} tokens")
            token_limit = int(context_window * 0.5)
            logger.info(f"[CHAT_MEMORY] Allocating {token_limit} tokens for chat history (50% of context window)")
            return token_limit

    except Exception as e:
        logger.warning(f"[CHAT_MEMORY] Could not introspect model context window: {e}")

    # Fallback to safe default
    default_limit = 3000
    logger.info(f"[CHAT_MEMORY] Using default token limit: {default_limit}")
    return default_limit


def get_or_create_chat_memory(session_id: str) -> ChatMemoryBuffer:
    """
    Get or create a ChatMemoryBuffer for the given session_id.

    Uses in-memory storage with SimpleChatStore. Each session has its own
    isolated conversation history.

    Args:
        session_id: Unique identifier for the conversation session

    Returns:
        ChatMemoryBuffer configured for the session
    """
    # Check cache first
    if session_id in _memory_cache:
        logger.debug(f"[CHAT_MEMORY] Retrieved cached memory for session: {session_id}")
        return _memory_cache[session_id]

    # Create new memory buffer
    token_limit = get_token_limit_for_chat_history()

    memory = ChatMemoryBuffer.from_defaults(
        token_limit=token_limit,
        chat_store=_chat_store,
        chat_store_key=session_id
    )

    # Cache it
    _memory_cache[session_id] = memory
    logger.info(f"[CHAT_MEMORY] Created new memory for session: {session_id} (token_limit={token_limit})")

    return memory


def clear_session_memory(session_id: str) -> None:
    """
    Clear the chat history for a specific session.

    Args:
        session_id: Session to clear
    """
    # Remove from cache
    if session_id in _memory_cache:
        del _memory_cache[session_id]

    # Clear from store
    messages = _chat_store.get_messages(session_id)
    if messages:
        # SimpleChatStore doesn't have direct clear, so we delete by setting empty
        _chat_store.delete_messages(session_id)
        logger.info(f"[CHAT_MEMORY] Cleared memory for session: {session_id}")


def get_chat_history(session_id: str) -> list:
    """
    Get the full chat history for a session.

    Args:
        session_id: Session to retrieve history for

    Returns:
        List of ChatMessage objects
    """
    messages = _chat_store.get_messages(session_id)
    return messages if messages else []
