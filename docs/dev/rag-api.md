# RAG Server API Reference

Base URL: `http://localhost:8001`

## Health & Configuration

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/config` | System configuration (max_upload_size_mb) |
| GET | `/models/info` | Model names and settings |
| GET | `/settings` | Current toggleable settings |
| PATCH | `/settings` | Update settings (writes to config.yml; rag-server and worker both pick up changes) |
| GET | `/api-keys` | Providers requiring API keys and their status |
| POST | `/api-keys/{provider}` | Set and validate an API key for a provider |

## Documents

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/documents` | List documents (supports sorting) |
| POST | `/documents/check-duplicates` | Check file hashes for duplicates |
| POST | `/upload` | Upload files (returns batch_id) |
| GET | `/tasks/{batch_id}/status` | Upload progress |
| DELETE | `/documents/{document_id}` | Delete document |
| GET | `/documents/{document_id}/download` | Download original file |

**Sorting Parameters:** `sort_by` (name, chunks, uploaded_at), `sort_order` (asc, desc)

## Query & Chat

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/query` | RAG query (non-streaming) |
| POST | `/query/stream` | RAG query (SSE streaming) |
| POST | `/query/with-context` | RAG generation with pre-injected context (bypasses retrieval; used by evals) |
| GET | `/chat/history/{session_id}` | Get conversation history |
| POST | `/chat/clear` | Clear session history |

**Query Request:**
```json
{
  "query": "What is...",
  "session_id": "uuid-optional",
  "is_temporary": false
}
```

**Streaming Events:** `token`, `sources`, `done`, `error`

## Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/chat/sessions` | List sessions (paginated) |
| GET | `/chat/sessions/{session_id}` | Get session metadata |
| POST | `/chat/sessions/new` | Create new session |
| DELETE | `/chat/sessions/{session_id}` | Delete session |
| POST | `/chat/sessions/{session_id}/archive` | Archive session |
| POST | `/chat/sessions/{session_id}/unarchive` | Unarchive session |

## Metrics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/metrics/system` | Complete system overview |
| GET | `/metrics/models` | Detailed model info |
| GET | `/metrics/retrieval` | Retrieval pipeline config |

Evaluation endpoints (runs, dashboard, comparison) live on the evals service (port 8002) — see [eval-framework.md](eval-framework.md).
