# Migration Scripts

This directory contains database migration and maintenance scripts.

## Session Migration

### migrate_sessions.py

Adds metadata to existing chat sessions that were created before the session management feature was implemented.

**What it does:**
- Scans Redis for all existing session keys (`chat:history:*`)
- Creates metadata for sessions that don't have it
- Generates titles from the first user message or uses timestamp as fallback
- Sets default values for `created_at`, `last_updated`, and `archived` fields

**Usage:**

```bash
# From the rag_server directory
cd services/rag_server

# Make script executable
chmod +x scripts/migrate_sessions.py

# Run migration (requires Redis to be running)
REDIS_URL=redis://localhost:6379/0 python scripts/migrate_sessions.py

# Or with Docker Compose
docker compose exec rag-server python scripts/migrate_sessions.py
```

**Environment Variables:**
- `REDIS_URL`: Redis connection URL (default: `redis://localhost:6379/0`)

**Output:**
- Logs migration progress for each session
- Reports total: migrated, skipped, and error counts

**Safety:**
- Only creates metadata for sessions that don't have it (idempotent)
- Does not modify existing chat history
- Safe to run multiple times
