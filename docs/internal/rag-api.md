# RAG server API reference

The rag-server is a FastAPI application listening on port 8001. Routes are mounted
at the paths shown below with no version or `/api` prefix in the application
itself — the `/api` prefix seen from the browser is added by the webapp's
SvelteKit server-side proxy (`hooks.server.ts`), which strips nothing for
rag-server calls and forwards everything under `/api/*` (except `/api/eval/*`)
to `RAG_SERVER_URL` (default `http://localhost:8001`).

All request/response shapes below are the exact Pydantic models in
`services/rag_server/schemas/`, cross-checked against the route handlers in
`services/rag_server/api/routes/`.

## Auth

Auth is bearer-token, and only enforced in the server deployment tier. The
dependency lives in `infrastructure/auth.py`: if the environment variable
`RAG_SERVER_AUTH_TOKEN_FILE` is unset, `require_bearer_token` is a no-op and
every route is open. When it is set, the token is read once from the file at
that path (cached process-wide) and every request to a protected router must
send `Authorization: Bearer <token>`; a missing or non-matching token returns
401. The comparison uses `secrets.compare_digest` (constant-time).

`/health` is mounted without the auth dependency and is always reachable
un-authenticated — it exists for orchestrators/load balancers that don't carry
a token. Every other router (`query`, `documents`, `chat`, `sessions`,
`metrics`, `api-keys`, `settings`) is registered in `main.py` with
`dependencies=[Depends(require_bearer_token)]`.

In the default/local compose tier, `RAG_SERVER_AUTH_TOKEN_FILE` is not set, so
the whole API is open on the private Docker network. The webapp's own
server-side proxy is the only component that attaches this bearer token; the
browser never sees or sends it.

## Documents

| Method & path | Purpose | Request | Response | Notable status codes |
|---|---|---|---|---|
| `GET /documents` | List all indexed documents | Query params `sort_by` (`uploaded_at`\|`file_name`\|`name`\|`chunks`, default `uploaded_at`; `name` is accepted as an alias for `file_name`) and `sort_order` (`asc`\|`desc`, default `desc`). Invalid values silently fall back to the defaults rather than erroring. | `DocumentListResponse { documents: list[dict] }`. Each dict has `id`, `file_name`, `file_type`, `chunks`, `uploaded_at`, `file_size_bytes`. Not sub-modeled — FastAPI does not validate the dict's inner keys. | 500 on any DB error |
| `POST /documents/check-duplicates` | Check whether files (by content hash) already exist before uploading | `FileCheckRequest { files: list[{filename, size, hash}] }` | `FileCheckResponse { results: dict[filename, FileCheckResult] }`, where `FileCheckResult` is `{filename, exists, document_id, existing_filename, reason}` | 500 on DB error |
| `POST /upload` | Upload one or more files for ingestion | `multipart/form-data`, field `files` (repeated) | `BatchUploadResponse { status: "queued", batch_id, tasks: list[{task_id, filename}] }` | 503 if the active embedding provider is TEI and it fails a pre-flight reachability check (`GET {tei_base_url}/health`); 400 if every file was rejected (unsupported extension) and none queued |
| `GET /tasks/{batch_id}/status` | Poll ingestion progress for a batch | Path param `batch_id` (UUID) | `BatchProgressResponse { batch_id, total, completed, tasks: dict }` | 404 if batch not found; 400 if `batch_id` is not a valid UUID |
| `DELETE /documents/{document_id}` | Delete a document and its indexed chunks | Path param `document_id` (UUID) | `DeleteResponse { status: "success", message }` | 404 if not found; 400 if `document_id` is not a valid UUID |
| `GET /documents/{document_id}/download` | Download the original uploaded file | Path param `document_id` (UUID) | Raw file bytes (`FileResponse`, `media_type=application/octet-stream`) | 404 if the document row exists but the stored file is gone, or if the document doesn't exist at all; 400 on invalid UUID |

Unsupported file extensions are rejected per-file inside the batch (accumulated
into an `errors` list) rather than failing the whole upload; the endpoint only
returns 400 if *no* file in the batch was accepted. Uploaded files are staged
to a shared temp directory and a Postgres task row is created per file inside
one transaction, so they become immediately claimable by the task worker.

## Query

| Method & path | Purpose | Request | Response | Notable status codes |
|---|---|---|---|---|
| `POST /query` | Ask a question against the RAG pipeline (non-streaming) | `QueryRequest { query, session_id?, is_temporary=false, include_chunks=false }` | `QueryResponse { answer, sources: list[dict], session_id, citations: list[dict] \| null, metrics: QueryMetrics \| null }` | 500 on any pipeline exception (retrieval, LLM call, etc. are not distinguished at the HTTP layer) |
| `POST /query/with-context` | Run generation with caller-supplied passages, bypassing retrieval entirely | `QueryWithContextRequest { query, context_passages: list[{text, doc_id}], session_id? }` | Same `QueryResponse` shape; `citations` is always `null` on this path | 500 on exception |
| `POST /query/stream` | Same as `/query` but streamed via SSE | `QueryRequest` (identical body) | `text/event-stream` — see "SSE streaming contract" below | Errors surface as an `event: error` frame, not an HTTP error status, once the stream has started |

`QueryResponse.sources` and `QueryResponse.citations` are both typed as loose
`list[dict]`, not sub-modeled Pydantic types. FastAPI's `response_model=QueryResponse`
therefore validates that they are lists of dicts but does **not** validate or
enforce any particular set of keys inside them — their actual shape is
whatever the inference pipeline's source/citation extraction produced at that
moment. In practice, each source dict carries `document_id`, `document_name`,
`excerpt`, `full_text`, `path`, `score`, and (only when `include_chunks=true`)
`chunk_id`/`chunk_index`; each citation dict (only present when numeric
citations are enabled) carries `source_index`, `document_id`, `chunk_id`,
`chunk_index`. None of this is enforced by the schema.

`QueryMetrics.token_usage` is `null` whenever the underlying token counter saw
zero total tokens for that call — this happens when the active LLM provider
doesn't feed token counts into the pipeline's callback handler.

`POST /query/with-context` has no caller anywhere in the webapp — it is
reachable only via direct API calls (e.g. by the eval service or manual
testing).

## SSE streaming contract (`POST /query/stream`)

The response is a `StreamingResponse` with `media_type="text/event-stream"`
and headers `Cache-Control: no-cache`, `Connection: keep-alive`,
`X-Accel-Buffering: no` (the last one disables reverse-proxy buffering so the
stream actually reaches the client incrementally rather than arriving as one
buffered chunk).

Every frame is written as a raw `"event: <name>\ndata: <json>\n\n"` string.
The sequence for a successful call is:

1. **`event: token`** — emitted once per generated token/chunk while the LLM
   is producing the answer. Payload: `{"token": "<text>"}`. This event may
   fire many times.
2. **`event: sources`** — emitted exactly once, after the full answer has been
   assembled (i.e. after the last `token` event, not interleaved with them).
   Payload: `{"sources": [...], "citations": [...] | null, "session_id": "..."}`.
   `sources` and `citations` follow the same loose, unvalidated shape described
   above for the non-streaming endpoint — nothing in the SSE path enforces a
   schema on these either, since they are hand-serialized JSON rather than a
   FastAPI response model.
3. **`event: done`** — emitted exactly once, always last on success. Payload:
   `{}`.
4. **`event: error`** — emitted instead of the remaining sequence if any
   exception occurs mid-stream. Payload: `{"error": "<str(exception)>"}`. The
   generator stops after this; no `done` event follows an `error` event.

Example (illustrative, not a captured trace):

```
event: token
data: {"token": "The"}

event: token
data: {"token": " answer"}

event: sources
data: {"sources": [{"document_id": "...", "document_name": "handbook.pdf", "excerpt": "...", "full_text": "...", "path": "...", "score": 0.82}], "citations": null, "session_id": "abc-123"}

event: done
data: {}
```

Session metadata (last-touched timestamp, auto-generated title on first
message) is updated after the answer is fully streamed but before the
`sources` event is sent.

Output-guardrail PII scanning, where enabled, is audit-only on this endpoint:
because tokens are already on the wire by the time a full-answer scan could
run, a detected leak cannot be blocked here the way it can on the
non-streaming `/query` path — it can only be logged.

## Sessions

Session endpoints are split across two routers: `sessions.py` (list/create/
delete/archive) mounted at `/chat/sessions...`, and `chat.py` (history/clear)
mounted at `/chat/history/...` and `/chat/clear`.

| Method & path | Purpose | Request | Response | Notable status codes |
|---|---|---|---|---|
| `GET /chat/sessions` | List persisted (non-temporary) sessions | Query params `include_archived` (bool, default `false`), `limit` (1–500, default 100), `offset` (default 0) | `SessionListResponse { sessions: list[SessionMetadataResponse], total }` | 500 on DB error |
| `GET /chat/sessions/{session_id}` | Get one session's metadata | Path param `session_id` | `SessionMetadataResponse { session_id, title, created_at, updated_at, is_archived, is_temporary, llm_model, search_type }` | 404 if not found |
| `POST /chat/sessions/new` | Create a session | `CreateSessionRequest { is_temporary=false, title?, first_message? }` — if `title` is omitted and `first_message` is given, a title is AI-generated from it; otherwise the title defaults to `"New Chat"` | `CreateSessionResponse { session_id, title, created_at, is_temporary, llm_model, search_type }` | 500 on error |
| `DELETE /chat/sessions/{session_id}` | Permanently delete a session (metadata + messages) | Path param `session_id` | `DeleteSessionResponse { status, message }` | 404 if not found |
| `POST /chat/sessions/{session_id}/archive` | Archive a session | Path param `session_id` | `ArchiveSessionResponse { status, message }` | 404 if not found |
| `POST /chat/sessions/{session_id}/unarchive` | Restore a session from archive | Path param `session_id` | `ArchiveSessionResponse { status, message }` | 404 if not found |
| `GET /chat/history/{session_id}` | Get full message history + metadata for a session | Path param `session_id` | `ChatHistoryResponse { session_id, messages: list[dict], metadata: SessionMetadataResponse \| null }`. Each message dict is `{role, content}`. | 500 on error (no explicit 404 for an unknown session — `messages` is just empty and `metadata` is `null`) |
| `POST /chat/clear` | Clear a session's chat memory (cache + Postgres rows) | `ClearSessionRequest { session_id }` | `ClearSessionResponse { status, message }` | 500 on error |

`GET /chat/sessions` always excludes temporary sessions server-side (by
design — temporary sessions have no Postgres row to list). A session's own
temporary-ness for the *current* conversation is tracked client-side via a URL
parameter, not by reading this field back.

## Settings and API keys

| Method & path | Purpose | Request | Response | Notable status codes |
|---|---|---|---|---|
| `GET /settings` | Read the current toggleable settings | none | `SettingsResponse { contextual_retrieval_enabled }` | — |
| `PATCH /settings` | Update a toggleable setting | `SettingsUpdate { contextual_retrieval_enabled? }` | `SettingsResponse { contextual_retrieval_enabled }` (post-update value) | 500 if the config-file write fails |
| `GET /api-keys` | List providers that require an API key and whether one is set | none | `list[ApiKeyStatus { provider, has_key, masked_key }]` | — |
| `POST /api-keys/{provider}` | Set and validate an API key for a provider | Path param `provider`; body `ApiKeySetRequest { api_key }` | `ApiKeySetResponse { provider, status: "valid", masked_key }` | 400 if the provider isn't one of the configured providers requiring a key, or if the key fails provider-side validation |

`PATCH /settings` currently only recognizes one field,
`contextual_retrieval_enabled`; setting it writes straight through to
`config.yml` via `update_config_file(...)` so both rag-server and the task
worker pick up the change (subject to the config mtime auto-reload). This is
the only pipeline knob exposed for runtime mutation through this endpoint —
everything else the `/metrics/system` endpoint reports (top-k, hybrid search,
reranker on/off, chunk size, etc.) is read-only from this API.

`masked_key` on both API-key endpoints shows the first 7 and last 3 characters
of the key (or just the last 3 for very short keys), never the full value.

## Health and metrics

| Method & path | Purpose | Request | Response | Notable status codes |
|---|---|---|---|---|
| `GET /health` | Liveness check, unauthenticated | none | `{"status": "healthy"}` | Always 200 if the process is up — does not probe Postgres or TEI |
| `GET /models/info` | Model + pricing summary for the active LLM | none | `ModelsInfoResponse { llm_model, llm_provider, llm_execution_boundary, embedding_model, reranker_model, reranker_enabled, cost_per_1m_input_tokens, cost_per_1m_output_tokens }` | — |
| `GET /config` | Server-side operational config exposed to clients | none | `ConfigResponse { max_upload_size_mb }` (from env var `MAX_UPLOAD_SIZE`, default `80`) | — |
| `GET /metrics/system` | Full system overview: models, retrieval config, doc/chunk counts, component health | none | `SystemMetrics` (nests `ModelsConfig`, `RetrievalConfig`, `document_count`, `chunk_count`, `health_status`, `component_status: dict[str, str]`) | 500 on error |
| `GET /metrics/models` | Just the models portion of the above, standalone | none | `ModelsConfig { llm, embedding, reranker?, eval? }`, each a `ModelInfo` with `name`, `provider`, `model_type`, `execution_boundary`, `size`, `reference_url`, `description`, `status` | 500 on error |
| `GET /metrics/retrieval` | Just the retrieval-config portion, standalone | none | `RetrievalConfig { retrieval_top_k, final_top_n, hybrid_search, contextual_retrieval, reranker, pipeline_description }` | 500 on error |

`GET /health` differs from `/metrics/system`'s `component_status` in what it
actually checks: `/health` only confirms the FastAPI process is answering
requests. `/metrics/system` separately probes Postgres (`SELECT 1`) and TEI
(`GET {tei_base_url}/health`) and reports `"healthy"` / `"unhealthy"` /
`"unavailable"` per component, rolling them up into `health_status`
(`"healthy"` only if every component reported `"healthy"`, else `"degraded"`).

`/models/info` and `/metrics/models`/`/metrics/retrieval` are all functionally
subsumed by `/metrics/system`, which nests the same model and retrieval data
in one call — the webapp only ever calls `/metrics/system`.
