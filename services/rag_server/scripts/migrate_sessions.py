#!/usr/bin/env python3
"""
Migration script to add metadata to existing chat sessions.

This script:
1. Scans Redis for existing session keys (chat:history:*)
2. Creates metadata for sessions that don't have it
3. Generates titles based on first message content or timestamp
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from llama_index.core.llms import ChatMessage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def generate_title_from_content(content: str, max_length: int = 50) -> str:
    """Generate a title from message content."""
    # Clean up the content
    content = content.strip()

    # Remove common prefixes
    prefixes = ["what", "how", "why", "when", "where", "who", "can", "could", "would", "should"]
    first_word = content.split()[0].lower() if content.split() else ""

    # If it starts with a question word, keep it
    if first_word in prefixes:
        # Take first sentence or first N characters
        sentences = re.split(r'[.!?]', content)
        title = sentences[0] if sentences else content
    else:
        # Just take first N characters
        title = content

    # Truncate to max length
    if len(title) > max_length:
        title = title[:max_length].rsplit(' ', 1)[0] + "..."

    return title.capitalize()


async def migrate_sessions():
    """Migrate existing sessions to include metadata."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    logger.info(f"Connecting to Redis at {redis_url}")
    redis_client = await aioredis.from_url(redis_url, decode_responses=True)

    try:
        # Scan for all session history keys
        pattern = "chat:history:*"
        logger.info(f"Scanning for sessions matching pattern: {pattern}")

        migrated = 0
        skipped = 0
        errors = 0

        async for key in redis_client.scan_iter(match=pattern, count=100):
            session_id = key.replace("chat:history:", "")
            metadata_key = f"chat:metadata:{session_id}"

            # Check if metadata already exists
            if await redis_client.exists(metadata_key):
                logger.debug(f"Session {session_id} already has metadata, skipping")
                skipped += 1
                continue

            try:
                # Get chat history
                history_data = await redis_client.get(key)
                if not history_data:
                    logger.warning(f"No history data found for session {session_id}")
                    skipped += 1
                    continue

                messages = json.loads(history_data)
                if not messages:
                    logger.warning(f"Empty message list for session {session_id}")
                    skipped += 1
                    continue

                # Generate title from first user message
                title: Optional[str] = None
                for msg_data in messages:
                    if msg_data.get("role") == "user":
                        content = msg_data.get("content", "")
                        if content:
                            title = generate_title_from_content(content)
                            break

                # Fallback to timestamp-based title
                if not title:
                    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
                    title = f"Chat from {timestamp}"

                # Create metadata
                metadata = {
                    "session_id": session_id,
                    "title": title,
                    "created_at": datetime.utcnow().isoformat(),
                    "last_updated": datetime.utcnow().isoformat(),
                    "archived": False
                }

                # Store metadata with 1-hour TTL (same as chat history)
                await redis_client.set(
                    metadata_key,
                    json.dumps(metadata),
                    ex=3600
                )

                logger.info(f"Migrated session {session_id} with title: {title}")
                migrated += 1

            except Exception as e:
                logger.error(f"Error migrating session {session_id}: {e}", exc_info=True)
                errors += 1

        logger.info(f"Migration complete: {migrated} migrated, {skipped} skipped, {errors} errors")

    finally:
        await redis_client.close()


if __name__ == "__main__":
    asyncio.run(migrate_sessions())
