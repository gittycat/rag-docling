# RAG pipeline (ingestion)

Audience: developers working on RAGBench. This covers the ingestion path end to
end — from an uploaded file to searchable, embedded chunks — plus the async
task worker that drives it.

## Stage overview

Ingestion runs as a single function, `ingest_document()`, invoked by the task
worker for each queued document. It runs synchronously inside a worker thread
(see "Task worker" below) and executes these stages in order:

1. **Extract file metadata** — file name, extension, size, SHA-256 hash, parent
   path. The caller-supplied display filename overwrites whatever the metadata
   extraction step derived from the on-disk path, so the name shown to users
   matches what they uploaded rather than a temp-file name.
2. **Chunk the document** — dispatches to either `SentenceSplitter` (plain
   text/Markdown) or Docling (everything else). See "Chunking" below.
3. **Contextual retrieval (optional)** — prepends an LLM-generated one-to-two
   sentence context blurb to each chunk. Off by default. See its own section.
4. **Add document metadata to chunks** — attaches `document_id`, `chunk_index`,
   `uploaded_at`, file metadata, and a node ID of the form
   `{document_id}-chunk-{index}` to every chunk, then sanitizes the metadata
   dict down to scalar types (`str`, `int`, `float`, `bool`, `None`) before it
   is handed to ChromaDB — any list/dict metadata Docling attached is dropped
   at this point.
5. **Embed and index** — batches chunks, calls the embedding model, and
   inserts the resulting nodes into the ChromaDB vector store.
6. **BM25 refresh (no-op)** — a placeholder step; the `pg_textsearch` BM25
   index in Postgres updates itself automatically on chunk insert, so no
   manual refresh call is actually needed here.

The function returns a dict containing `document_id`, `filename`, a chunk
count, and `chunks_data` — one entry per chunk with `chunk_index`, `content`,
`content_with_context`, and `metadata` — which the task worker then persists to
Postgres.

## Docling: reader configuration and the JSON export constraint

Docling handles every supported format except plain text and Markdown:
`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`, `.adoc`.

The reader **must** be constructed as:

```python
DoclingReader(export_type=DoclingReader.ExportType.JSON)
```

This is not a stylistic choice. `DoclingNodeParser` — the node parser that
turns a loaded document into chunks — expects Docling's structured document
tree (`DoclingDocument`), which only the JSON export preserves. The default
export type is Markdown, which flattens that structure into plain text.
Construct the reader with the Markdown default (or omit `export_type`
entirely) and `DoclingNodeParser` has nothing to parse: the code paths that
depend on structural chunking break, either by raising or by silently
producing degenerate chunks, because the parser is designed against the JSON
tree, not against Markdown text. Any change to this reader construction should
be treated as a breaking change to ingestion for every non-text format.

`DoclingNodeParser()` itself is constructed with no explicit parameters — no
chunk size, overlap, or tokenizer argument is passed anywhere in this
codebase. Chunking behavior for PDFs, Word docs, spreadsheets, and the rest is
entirely whatever the installed `llama-index-node-parser-docling` package
does internally. A version bump of that dependency can silently change chunk
boundaries for every non-text document type, with no local override to fall
back on.

## Chunking parameters

| Path | Parser | Parameters | Configurable? |
|---|---|---|---|
| `.txt`, `.md` | `SentenceSplitter` | `chunk_size=500`, `chunk_overlap=50` | No |
| all other supported types | `DoclingNodeParser` | none (library defaults) | No |

For plain text and Markdown files, `chunk_size=500` and `chunk_overlap=50` are
**hardcoded Python defaults** on the chunking function in
`services/rag_server/core/config.py` — they are not read from `config.yml`,
and there is no config key for them at all. An operator who goes looking in
`config.yml` for a chunk-size knob for text files will not find one; changing
this value requires a code change and a redeploy, not a configuration edit.

A related but distinct constant, `INGEST_BATCH_SIZE = 32`, governs how many
chunks are embedded per batch during indexing — it is chunking-adjacent, also
hardcoded, and also absent from `config.yml`.

## Contextual retrieval

Contextual retrieval (Anthropic's technique of prepending a short LLM-written
context blurb to each chunk before embedding) is implemented as an optional
ingestion stage.

**Toggle**: `retrieval.enable_contextual_retrieval` in `config.yml`. The
shipped `config.yml` sets this to `false`, with a comment noting it makes
document processing much slower. Note that the Pydantic model's own default
for this field is `True` — the opposite of what's shipped. A deployment that
somehow bypassed `config.yml` and relied on the Pydantic default alone would
silently get contextual retrieval turned on, with the corresponding slowdown.
Toggling it is a one-line YAML edit (it can also be flipped programmatically
at runtime through the config-update helper).

**The prompt**, templated with the document name, file extension, and the
first 400 characters of the chunk as a preview:

```
Document: {document_name} ({document_type})

Chunk content:
{chunk_preview}

Provide a concise 1-2 sentence context for this chunk, explaining what document it's from and what topic it discusses.
Format: "This section from [document/topic] discusses [specific topic/concept]."

Context (1-2 sentences only):
```

**One LLM call per chunk.** There is no batching of multiple chunks into a
single prompt, and no caching — every chunk gets a fresh LLM call on every
ingestion run, even if the same document is re-ingested. The model used is
whatever is configured as the active inference model in `config.yml` (the
same model used for chat/generation — there is no separate, cheaper "context
model" configured for this purpose).

**Concurrency** is bounded by an `asyncio.Semaphore` sized from
`retrieval.contextual_concurrency` (default `8`, same value in both
`config.yml` and the Pydantic model). All chunks belonging to one document are
dispatched together under that semaphore via `asyncio.gather`, and the
original chunk order is preserved in the result.

Because `ingest_document()` runs inside the task worker's executor thread
(no running event loop), the contextual-retrieval stage is free to call
`asyncio.run(...)` internally to drive its async LLM calls from otherwise
synchronous code. This is safe only because of where it runs — calling
`ingest_document()` directly from a context that already has a running event
loop would raise `RuntimeError: asyncio.run() cannot be called from a running
event loop`.

**Failure handling is per-chunk and silent.** If the LLM call for a given
chunk raises for any reason, the code logs a warning and returns the chunk
**unmodified** — the document does not fail ingestion, and nothing in the
returned result records how many chunks failed to get a context blurb. A
document can therefore end up with a mix of contextualized and
non-contextualized chunks, invisibly.

When a context is generated successfully, it is prepended directly into the
chunk's text as `f"{context}\n\n{node.text}"` — two newlines, then the
original chunk content.

If PII masking is enabled, the document name and chunk preview sent to the
LLM are masked first, and the returned context is unmasked (with fuzzy
recovery) before being merged into the chunk text — one token mapping is
shared across all of a document's concurrent chunk calls so the same entity
maps to the same token throughout.

### Defect: `content_with_context` is always empty

The code that assembles `chunks_data` for Postgres reads
`node.metadata.get("contextual_prefix", "")` to populate the
`content_with_context` column. But the contextual-retrieval stage described
above never sets a `contextual_prefix` metadata key on the node — it merges
the generated context straight into `node.text`, not into a separate metadata
field. The practical effect: **`document_chunks.content_with_context` in
Postgres is always an empty string**, regardless of whether contextual
retrieval ran or succeeded. The generated context is not lost — it lives
inside `content` (via the embedded/indexed node text) — but the column
specifically meant to hold it never gets populated. The BM25 retriever (see
`retrieval.md`) prefers `content_with_context` over `content` when building
its result text, and so silently falls back to plain `content` for every
query, again regardless of whether contextual retrieval is enabled.

## Embedding generation

The embedding model and provider are selected via `active.embedding` in
`config.yml` (currently `nomic-embed`, resolving to `nomic-embed-text:latest`
served by Ollama). Only Ollama and OpenAI embedding providers are implemented;
selecting anything else raises at startup. Embedding batch size defaults per
provider (64 for Ollama, 100 for OpenAI) unless overridden by config.

At ingestion time, chunks are grouped into batches of `INGEST_BATCH_SIZE = 32`
(a separate, hardcoded constant, distinct from the embedding client's own
batch size). Each batch is embedded with one call to the embedding model, the
resulting vectors are assigned onto the chunk nodes, and the batch is inserted
into the vector store. A progress callback fires once per batch, which is why
the "chunks completed" counter surfaced to the API can jump by up to 32 at a
time rather than incrementing per chunk.

Batch embedding retries up to 3 times with exponential backoff (2s, then 4s),
but only for errors that look connection-related (matching
`eof|connection|timeout|refused|unavailable` in the error message,
case-insensitive); any other error, or the third failure, propagates
immediately and aborts the whole document's ingestion.

## ChromaDB collection and per-chunk metadata

All documents share a single ChromaDB collection — the name comes from
`chromadb.collection` in `config.yml` (default `document_chunks`) — created
via `get_or_create_collection`. Documents are distinguished within that one
collection purely by metadata, not by separate per-document collections. The
client connects over HTTP only (`chromadb.HttpClient`); there is no
persistent/embedded-mode code path in this codebase.

Per-chunk metadata stored in Chroma (after the scalar-only sanitize pass):

- `file_name`, `file_type`, `path`, `file_size_bytes`, `file_hash`
- `chunk_index` (0-based position within the document)
- `document_id`
- `uploaded_at` (ISO 8601 UTC)
- node ID: `{document_id}-chunk-{chunk_index}`

Any non-scalar metadata Docling attached upstream is dropped at this stage —
only `str`, `int`, `float`, `bool`, and `None` survive into Chroma.

## Task worker

The task worker is a separate long-running process (its own container) that
polls a Postgres-backed job queue and processes documents one at a time per
worker slot.

**Claiming a task** uses `SELECT ... FOR UPDATE SKIP LOCKED` so that multiple
worker processes can poll the same queue without contending on the same row:

```sql
WITH next_task AS (
    SELECT id FROM job_tasks
    WHERE status = 'pending'
    ORDER BY created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE job_tasks
SET status = 'processing',
    started_at = NOW(),
    attempt = attempt + 1
FROM next_task
WHERE job_tasks.id = next_task.id
RETURNING job_tasks.id, job_tasks.batch_id, job_tasks.filename,
          job_tasks.file_path, job_tasks.attempt
```

This is a single round trip: it picks the oldest pending row not already
locked by another worker, flips it to `processing`, bumps the attempt count,
and returns it. If nothing is pending, it returns nothing and the worker goes
back to polling.

**Poll interval**: 1 second between queue checks when idle.

**Concurrency**: controlled by the `WORKER_CONCURRENCY` environment variable,
default `2`. It is hard-capped in code at `MAX_WORKER_CONCURRENCY = 8`,
justified in a comment as protecting the connection-pool budget — this cap is
**not configurable via `config.yml`**; raising it requires a code change.
Each concurrency slot runs its own independent claim loop.

**Retries**: a task gets up to `MAX_ATTEMPTS = 3` attempts. On failure, if the
attempt count is already at the max, the task is marked permanently failed;
otherwise it's put back to `pending` after a delay that increases with the
attempt number (5s, 15s, then 60s) — note the attempt counter itself is not
reset on retry, since the claim step already incremented it. A missing
temp-upload file (e.g. the shared volume was reset) is treated as an
immediate, non-retryable permanent failure regardless of attempt count.

**Stuck-task reset**: a background check runs every 60 seconds looking for
tasks that have been stuck in `processing` for over an hour. Tasks past that
timeout that are already at the max attempt count are marked as errored;
tasks past the timeout but still under the attempt limit are reset back to
`pending` so a healthy worker can reclaim them. This matches the documented
behavior that stuck tasks reset after roughly an hour.

## Progress tracking

Progress is tracked at batch, task, and chunk level. Chunk-level progress is
driven by the same per-batch embedding callback described above: the first
callback sets the task's total chunk count, and each subsequent callback
increments a completed-chunks counter by one. Because the callback fires once
per embedding batch of up to 32 chunks, `completed_chunks` advances in bursts
for any document with more than 32 chunks, rather than one increment per
chunk — this affects progress-bar smoothness, not correctness of the final
count.

## Supported formats

`.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`,
`.adoc`. Of these, only `.txt` and `.md` are routed to `SentenceSplitter`;
everything else goes through Docling. Unsupported extensions are rejected
both at upload time (per-file error, not a 500) and, redundantly, inside the
chunking function itself if that check is ever bypassed.

## Deletion and re-ingestion

Deleting a document (`DELETE /documents/{document_id}`) removes the
`Document` row from Postgres; its `DocumentChunk` rows cascade-delete via a
foreign key. The route then best-effort removes the on-disk stored original
file (a failure here is logged, not fatal).

### Defect: ChromaDB vectors are never removed on delete

Nothing in the deletion path — neither the route nor the underlying
document-deletion function — calls into ChromaDB to remove the vectors that
correspond to the deleted document. Postgres and the on-disk file are
cleaned up; the embeddings are not. In practice this means a "deleted"
document's chunks can continue to surface in vector search indefinitely,
even though the document no longer exists anywhere else in the system. There
is no cleanup job or endpoint that reconciles this.

Duplicate detection is advisory only: a `check-duplicates` endpoint lets a
client pre-check file hashes before uploading, but the upload endpoint itself
does not enforce hash-based deduplication. A hash collision that bypasses the
pre-check would hit a unique constraint on `file_hash` at insert time, with
no graceful handling visible in the surrounding code. There is no dedicated
re-ingest endpoint — re-ingesting a document means deleting it and uploading
it again.
