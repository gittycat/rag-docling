"""
Session Metadata Management Service

Manages chat session metadata separately from chat messages:
- Session metadata: title, timestamps, archive status
- Redis key pattern: session:metadata:{session_id}
- No TTL (persist indefinitely until deleted)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import redis

from core.config import get_required_env

logger = logging.getLogger(__name__)


@dataclass
class SessionMetadata:
    """Chat session metadata"""
    session_id: str
    title: str
    created_at: str  # ISO 8601 timestamp
    updated_at: str  # ISO 8601 timestamp
    is_archived: bool = False
    is_temporary: bool = False


def _get_redis_client():
    """Get Redis client for session metadata"""
    redis_url = get_required_env("REDIS_URL")
    return redis.from_url(redis_url, decode_responses=True)


def _metadata_key(session_id: str) -> str:
    """Generate Redis key for session metadata"""
    return f"session:metadata:{session_id}"


def create_session_metadata(
    session_id: str,
    is_temporary: bool = False,
    title: str = "New Chat"
) -> SessionMetadata:
    """
    Create new session metadata.

    If is_temporary=True, metadata is not persisted to Redis.
    """
    now = datetime.now(timezone.utc).isoformat()
    metadata = SessionMetadata(
        session_id=session_id,
        title=title,
        created_at=now,
        updated_at=now,
        is_archived=False,
        is_temporary=is_temporary
    )

    if not is_temporary:
        client = _get_redis_client()
        key = _metadata_key(session_id)
        client.set(key, json.dumps(asdict(metadata)))
        logger.info(f"[SESSION] Created metadata for session: {session_id}")
    else:
        logger.info(f"[SESSION] Created temporary session: {session_id} (not persisted)")

    return metadata


def get_session_metadata(session_id: str) -> Optional[SessionMetadata]:
    """Get session metadata from Redis"""
    client = _get_redis_client()
    key = _metadata_key(session_id)
    data = client.get(key)

    if not data:
        logger.debug(f"[SESSION] Metadata not found: {session_id}")
        return None

    metadata_dict = json.loads(data)
    return SessionMetadata(**metadata_dict)


def update_session_title(session_id: str, title: str) -> None:
    """Update session title (e.g., from first user message)"""
    metadata = get_session_metadata(session_id)
    if not metadata:
        logger.warning(f"[SESSION] Cannot update title - session not found: {session_id}")
        return

    metadata.title = title
    metadata.updated_at = datetime.now(timezone.utc).isoformat()

    client = _get_redis_client()
    key = _metadata_key(session_id)
    client.set(key, json.dumps(asdict(metadata)))
    logger.info(f"[SESSION] Updated title for {session_id}: {title}")


def touch_session(session_id: str) -> None:
    """Update session's updated_at timestamp (on each message)"""
    metadata = get_session_metadata(session_id)
    if not metadata:
        # Lazy initialization for existing sessions without metadata
        logger.info(f"[SESSION] Lazy-creating metadata for existing session: {session_id}")
        create_session_metadata(session_id)
        return

    metadata.updated_at = datetime.now(timezone.utc).isoformat()

    client = _get_redis_client()
    key = _metadata_key(session_id)
    client.set(key, json.dumps(asdict(metadata)))


def list_sessions(
    include_archived: bool = False,
    limit: int = 100,
    offset: int = 0
) -> List[SessionMetadata]:
    """
    List all sessions (excluding temporary).

    Returns sessions sorted by updated_at (newest first).
    Uses Redis SCAN for efficiency.
    """
    client = _get_redis_client()
    pattern = "session:metadata:*"

    sessions = []
    cursor = 0

    # Use SCAN to avoid blocking Redis
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=100)

        for key in keys:
            data = client.get(key)
            if data:
                metadata_dict = json.loads(data)
                metadata = SessionMetadata(**metadata_dict)

                # Filter temporary sessions
                if metadata.is_temporary:
                    continue

                # Filter archived if requested
                if not include_archived and metadata.is_archived:
                    continue

                sessions.append(metadata)

        if cursor == 0:
            break

    # Sort by updated_at (newest first)
    sessions.sort(key=lambda s: s.updated_at, reverse=True)

    # Apply pagination
    return sessions[offset:offset + limit]


def archive_session(session_id: str) -> None:
    """Mark session as archived"""
    metadata = get_session_metadata(session_id)
    if not metadata:
        logger.warning(f"[SESSION] Cannot archive - session not found: {session_id}")
        return

    metadata.is_archived = True
    metadata.updated_at = datetime.now(timezone.utc).isoformat()

    client = _get_redis_client()
    key = _metadata_key(session_id)
    client.set(key, json.dumps(asdict(metadata)))
    logger.info(f"[SESSION] Archived session: {session_id}")


def unarchive_session(session_id: str) -> None:
    """Restore session from archive"""
    metadata = get_session_metadata(session_id)
    if not metadata:
        logger.warning(f"[SESSION] Cannot unarchive - session not found: {session_id}")
        return

    metadata.is_archived = False
    metadata.updated_at = datetime.now(timezone.utc).isoformat()

    client = _get_redis_client()
    key = _metadata_key(session_id)
    client.set(key, json.dumps(asdict(metadata)))
    logger.info(f"[SESSION] Unarchived session: {session_id}")


def delete_session(session_id: str) -> None:
    """
    Delete session completely (metadata + messages).

    This deletes:
    1. Session metadata (session:metadata:{session_id})
    2. Chat messages (managed by RedisChatStore via LlamaIndex)
    """
    from pipelines.inference import clear_session_memory

    # Delete messages via LlamaIndex
    clear_session_memory(session_id)

    # Delete metadata
    client = _get_redis_client()
    key = _metadata_key(session_id)
    deleted = client.delete(key)

    if deleted:
        logger.info(f"[SESSION] Deleted session: {session_id}")
    else:
        logger.warning(f"[SESSION] Metadata not found for deletion: {session_id}")


def generate_session_title(first_user_message: str, max_length: int = 50) -> str:
    """
    Generate session title from first user message (simple truncation fallback).

    Truncates to max_length and adds "..." if needed.
    """
    if not first_user_message:
        return "New Chat"

    # Clean whitespace
    title = first_user_message.strip()

    # Truncate if needed
    if len(title) > max_length:
        title = title[:max_length].strip() + "..."

    return title


def generate_ai_title(first_user_message: str, max_length: int = 40) -> str:
    """
    Generate a concise chat title using AI from the first user message.

    Uses the configured LLM to create a short, descriptive title.
    Falls back to simple truncation if AI generation fails.

    Args:
        first_user_message: The user's first message in the chat
        max_length: Maximum length of the generated title

    Returns:
        A concise title for the chat session
    """
    if not first_user_message or not first_user_message.strip():
        return "New Chat"

    try:
        from infrastructure.llm.factory import get_llm_client

        llm = get_llm_client()

        prompt = f"""Generate a very short title (3-6 words max) for a chat that starts with this message.
Reply with ONLY the title, no quotes, no explanation, no punctuation at the end.

User message: {first_user_message[:500]}

Title:"""

        response = llm.complete(prompt)
        title = response.text.strip()

        # Clean up: remove quotes, limit length
        title = title.strip('"\'')
        if len(title) > max_length:
            title = title[:max_length].strip() + "..."

        # Fallback if AI returned empty or nonsensical response
        if not title or len(title) < 3:
            return generate_session_title(first_user_message, max_length)

        logger.info(f"[SESSION] AI-generated title: {title}")
        return title

    except Exception as e:
        logger.warning(f"[SESSION] AI title generation failed: {e}, using fallback")
        return generate_session_title(first_user_message, max_length)
