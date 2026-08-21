# Database

RAGBench's relational store is PostgreSQL, and it holds everything: chunk text,
chunk embeddings, and application state (documents, chat sessions, the task
queue). Three extensions are enabled by `init.sql`:

| Extension | Provides |
|---|---|
| `pg_textsearch` (Timescale) | the `bm25` index access method and `to_bm25query()` for BM25 full-text search |
| `vector` (pgvector) | the `vector` column type and the `<=>` cosine-distance operator |
| `vectorscale` (pgvectorscale, installed `CASCADE` on `vector`) | the `diskann` index access method — StreamingDiskANN |

```sql
CREATE EXTENSION IF NOT EXISTS pg_textsearch;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
```

There is no separate vector database. Schema is created by a single init script
(`services/postgres/init.sql`), run once by `docker-entrypoint-initdb.d` on
first container start; there is no migration tool wired up despite an Alembic
scaffold existing in the tree (see "Migrations" below).

## Schema

### `documents`

Source-file records, one row per uploaded document.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | primary key, `gen_random_uuid()` default |
| `file_name` | `VARCHAR(255)` | display name |
| `file_type` | `VARCHAR(50)` | extension |
| `file_path` | `TEXT` | nullable |
| `file_size_bytes` | `BIGINT` | nullable |
| `file_hash` | `VARCHAR(64)` | SHA-256, **unique** — backs duplicate detection |
| `uploaded_at` | `TIMESTAMPTZ` | default `NOW()` |
| `metadata` | `JSONB` | default `{}` |

### `document_chunks`

Chunk text, metadata, and the chunk's embedding vector — one row carries all
three, so BM25 and vector search read the same table.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | primary key |
| `document_id` | `UUID` | `REFERENCES documents(id) ON DELETE CASCADE` |
| `chunk_index` | `INTEGER` | 0-based position within the document |
| `content` | `TEXT` | chunk text, contextual-retrieval prefix included inline when enabled |
| `metadata` | `JSONB` | default `{}` |
| `embedding` | `vector(768)` | nullable — a chunk row can exist before its embedding is written; `NULL` rows are neither indexed nor returned |
| `created_at` | `TIMESTAMPTZ` | default `NOW()` |

The `768` is a schema constant matching the active embedding model
(`nomic-embed-text`), and `vector_store.dimension` in `config.yml` must state the
same number — the retriever's health probe builds its probe vector from the
config value, so a divergence surfaces there. Changing embedding models already
required a full re-ingest; with the dimension in the DDL it additionally requires
recreating the schema, because `init.sql` does not re-run against an existing
volume.

The `ON DELETE CASCADE` on `document_id` is what removes embeddings when a
document is deleted. There is no separate vector-deletion step and no way for an
orphaned vector to exist.

Unique constraint on `(document_id, chunk_index)`. A `content_with_context`
column existed until `docs/suggestions.md` #4.3: it was written from a
`contextual_prefix` metadata key nothing ever set, so it was always empty
while the prefix itself went into `content`. Column, write and the BM25
retriever's read of it are gone. Databases created before that change still
have the empty column — `init.sql` does not re-run on an existing volume, so
drop it by hand if you want it gone:

```sql
ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_with_context;
```

### BM25 index

```sql
CREATE INDEX idx_chunks_bm25 ON document_chunks
USING bm25 (content) WITH (text_config='english');
```

This index is created once, in `init.sql`, against the `content` column. The
`text_config='english'` option — which
selects English stemming/stopword rules for the underlying tsvector-style
tokenization — is **hardcoded in the DDL**. There is no corresponding
`config.yml` key; changing the search language requires editing `init.sql`
and rebuilding the index, not touching configuration.

Query-time usage is `PgSearchBM25Retriever` only: the `<@>` distance operator
against `to_bm25query(...)`, which returns negative scores (lower is better)
that the retriever negates. A second implementation in this module
(`search_chunks_bm25`, built on `bm25_search()`/`websearch_to_tsquery()`) had
no caller and was deleted — see `docs/suggestions.md` #4.4 and
`rag-pipeline.md`/`retrieval.md` for the retrieval-side detail. No manual
reindex step is needed after insert — the index maintains itself.

### Vector index

```sql
CREATE INDEX idx_chunks_embedding ON document_chunks
USING diskann (embedding vector_cosine_ops);
```

`diskann` is pgvectorscale's StreamingDiskANN access method. The operator class
is `vector_cosine_ops` and **cosine distance is the only supported metric here** —
the retriever's `<=>` operator and the index must agree, so an L2 or inner-product
query would not use this index. All index parameters are left at their defaults;
none are exposed in `config.yml`.

StreamingDiskANN is why the embeddings can live in Postgres at all. It keeps the
graph on disk and only an SBQ-compressed representation resident in RAM — roughly
96 bytes per vector at 768 dimensions, against roughly 3.2 KB for a fully
in-memory HNSW index. On a 16 GB machine that is the difference between a corpus
ceiling around 150k documents and one around 765k — assuming 10-page documents
(~11 chunks each); the real unit is chunks, so larger documents scale the figures
down proportionally. See `architecture.md` for the full basis.

Like the BM25 index, this one is created once in `init.sql` and maintains itself
on insert; no manual reindex step exists. It is checked by name by
`probe_vector_index()` — a *dropped* diskann index does not error, it silently
degrades every vector query to a sequential scan, so absence has to be detected
rather than caught.

### `chat_sessions` / `chat_messages`

Backs the Postgres-backed chat store (`PostgresChatStore`, implementing
LlamaIndex's `BaseChatStore`).

| `chat_sessions` column | Type | Notes |
|---|---|---|
| `id` | `UUID` | primary key, caller-supplied (not server-generated) |
| `title` | `VARCHAR(255)` | default `'New Chat'` |
| `llm_model` | `VARCHAR(100)` | nullable |
| `search_type` | `VARCHAR(20)` | nullable |
| `is_archived` | `BOOLEAN` | default `false` |
| `is_temporary` | `BOOLEAN` | default `false` |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | default `NOW()`, `updated_at` bumped on session touch |

| `chat_messages` column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL` | primary key |
| `session_id` | `UUID` | `REFERENCES chat_sessions(id) ON DELETE CASCADE` |
| `role` | `VARCHAR(20)` | not null |
| `content` | `TEXT` | not null |
| `metadata` | `JSONB` | default `{}` |
| `created_at` | `TIMESTAMPTZ` | default `NOW()` |

Index: `idx_messages_session` on `chat_messages(session_id)`.

Despite `is_temporary` existing as a column, temporary sessions are never
persisted through this table in practice — chat-and-memory.md covers the
in-memory cache asymmetry; `list_sessions()` always filters
`is_temporary == False`.

### `job_batches` / `job_tasks`

The document-ingestion task queue and its progress-tracking parent.

| `job_batches` column | Type | Notes |
|---|---|---|
| `id` | `UUID` | primary key, caller-supplied |
| `total_tasks` | `INTEGER` | not null |
| `completed_tasks` | `INTEGER` | default `0` |
| `status` | `VARCHAR(30)` | default `'pending'` |
| `created_at` | `TIMESTAMPTZ` | default `NOW()` |

| `job_tasks` column | Type | Notes |
|---|---|---|
| `id` | `UUID` | primary key |
| `batch_id` | `UUID` | `REFERENCES job_batches(id) ON DELETE CASCADE` |
| `filename` | `VARCHAR(255)` | not null |
| `file_path` | `TEXT` | not null — shared-volume path to the queued upload |
| `status` | `VARCHAR(30)` | default `'pending'` (`pending` / `processing` / `completed` / `error`) |
| `attempt` | `INTEGER` | default `0` |
| `total_chunks` | `INTEGER` | default `0` |
| `completed_chunks` | `INTEGER` | default `0` — see note below on granularity |
| `error_message` | `TEXT` | nullable |
| `created_at` | `TIMESTAMPTZ` | default `NOW()` |
| `started_at` | `TIMESTAMPTZ` | nullable |

Indexes: `idx_tasks_batch` on `batch_id`; `idx_tasks_claimable`, a **partial**
index on `created_at` where `status = 'pending'` — this keeps the `SKIP
LOCKED` claim query (below) fast by indexing only the rows it actually scans,
regardless of how large the table grows with completed/errored history.

`completed_chunks` increments once per embedding batch (`INGEST_BATCH_SIZE =
32` chunks), not once per chunk — for documents with more than 32 chunks, a
progress bar computed as `completed_chunks / total_chunks` will visibly jump
in steps rather than increment smoothly. This is a UI-smoothness quirk, not a
correctness bug; both fields are in the same "chunks embedded" unit.

## Connection pooling

The async engine (`services/rag_server/infrastructure/database/postgres.py`)
is a SQLAlchemy 2.0 + asyncpg engine, built once as a module-level singleton:

```python
_engine = create_async_engine(
    database_url,
    pool_size=db_config.pool_size,        # 10
    max_overflow=db_config.max_overflow,  # 20
    pool_pre_ping=db_config.pool_pre_ping,  # true
    pool_recycle=db_config.pool_recycle,    # 3600
    echo=os.environ.get("LOG_LEVEL", "").upper() == "DEBUG",
)
```

Values come from `database.*` in `config.yml` and are read once at first
engine creation:

| Setting | Value | Why it matters |
|---|---|---|
| `pool_size` | 10 | persistent connections kept open per service process (rag-server, task-worker each get their own pool) |
| `max_overflow` | 20 | additional connections allowed under burst load, on top of `pool_size` — so a single service can open up to 30 connections before requests start queuing for a slot |
| `pool_pre_ping` | `true` | issues a lightweight check before handing out a pooled connection, so a connection killed by the server (idle timeout, restart) is detected and replaced rather than surfacing as a query-time error |
| `pool_recycle` | 3600 | connections older than 1 hour are recycled rather than reused, avoiding failures against servers/proxies that silently drop long-lived connections |

Every write path uses `get_session()`, an async context manager that opens a
session, begins an explicit transaction (`session.begin()`), and
commits/rolls back automatically at block exit — there is no ad hoc
session/connection management scattered through the codebase.

The choice of a bounded `QueuePool`-style engine (rather than `NullPool`, which
opens a fresh connection per operation) was a deliberate fix for a prior
incident where fire-and-forget async tasks exhausted Postgres connections;
see `design-decisions.md` for the full context/problem/resolution/lesson
writeup. This document only states the current configuration.

### Where the server-side connection limit lives

The PostgreSQL server-side limit is a literal in the Postgres service's compose
command, and nowhere else:

```
command: postgres -c max_connections=200
```

`config.yml` used to carry a `database.max_connections` key that looked like it
set this. It never did — nothing read it — and it was removed (commit `e26a4d2`).
`config.yml`'s `database:` block now carries only the application-side pool
settings and an inline comment pointing here. To change the server limit, edit the
compose `command:` line; there is no config-file route to it.

## The `SKIP LOCKED` task queue

`job_tasks` doubles as a work queue for the async document-ingestion worker.
Workers claim the oldest pending row with a single round-trip CTE
(`infrastructure/database/jobs.py`, `claim_next_task`):

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

`FOR UPDATE SKIP LOCKED` lets multiple worker coroutines poll the same table
concurrently without blocking on each other's row locks: each claim attempt
picks the oldest pending row that isn't already locked by another in-flight
claim, atomically flips it to `processing`, and bumps the retry counter — all
in one statement, so there's no separate select-then-update race window. If
no pending row is available, the query returns no rows and the caller treats
that as "queue empty."

The worker pool polls this in a loop (one coroutine per unit of configured
concurrency) with a 1-second idle interval between empty claims.

**Retry and failure handling**: a task that fails is either requeued or
permanently failed depending on its attempt count (capped at 3 attempts).
Requeuing uses `reset_task_for_retry()`, which flips `status` back to
`pending` and clears `started_at`/`error_message` — but does **not** reset
`attempt`, since it was already incremented by the claim that picked it up;
attempt count is monotonic across retries of the same task. Between retries
the worker sleeps a backoff delay before resetting the task, so retries are
not immediate.

**Stuck-task recovery**: a periodic background check
(`reset_stuck_tasks(timeout_seconds, max_attempts)`) finds rows still
`processing` after a timeout — evidence of a worker that crashed or was
killed mid-task without ever reaching a terminal status — and resolves them
in one of two ways:

```sql
-- exhausted: mark permanently errored
UPDATE job_tasks
SET status = 'error',
    error_message = 'Task exceeded maximum retry attempts (stuck worker)'
WHERE status = 'processing'
  AND started_at < NOW() - make_interval(secs => :timeout)
  AND attempt >= :max_attempts

-- not yet exhausted: release back to the queue
UPDATE job_tasks
SET status = 'pending', started_at = NULL
WHERE status = 'processing'
  AND started_at < NOW() - make_interval(secs => :timeout)
  AND attempt < :max_attempts
```

The 1-hour stuck-task timeout matches the project's documented "stuck tasks
reset after 1 hour" behavior. This check runs on its own periodic schedule
independent of the claim loop, so a crashed worker's task is recovered
without operator intervention, bounded by the same `max_attempts` used for
ordinary retries.

Batch-level rollup (`job_batches.completed_tasks`) is updated transactionally
alongside each task's terminal status via `_finish_task()`, and the batch
flips to `completed` or `completed_with_errors` once every task in it has
reached a terminal state.

## Query patterns

Per project convention, database access uses SQLAlchemy's Core/ORM as a
**query builder**, not ORM relationship loading, for anything on a critical
path:

- Simple CRUD (create/get/update a `Document`, `ChatSession`, `JobTask`, …)
  goes through typed `select()` / `update()` / `delete()` statements against
  the mapped classes in `infrastructure/database/models.py`.
- Chunk counts and sort-by-chunk-count listings (`list_documents`) build an
  explicit subquery with `func.count()` and an `outerjoin`, rather than
  loading `Document.chunks` and counting in Python.
- BM25 search, vector search, and the `SKIP LOCKED` claim are all raw, explicit
  SQL via `text()` — deliberately, since each depends on PostgreSQL-specific
  syntax (`pg_textsearch`'s `<@>`/`to_bm25query()` pair, pgvector's `<=>`
  operator, `FOR UPDATE SKIP LOCKED`) that a query builder can't express
  portably. The query embedding is bound as a pgvector text literal
  (`"[0.1,0.2,…]"`) and cast server-side with `CAST(:qvec AS vector)`, because no
  pgvector asyncpg codec is registered on this engine.
- `Document.chunks` is declared as an ORM relationship
  (`cascade="all, delete-orphan"`) purely so that deleting a `Document` row
  cascades to its chunks — and therefore to their embeddings; nothing in the
  codebase eagerly loads or iterates
  that relationship for query purposes — chunk reads go through the explicit
  `get_chunks_for_document()`/`get_all_chunks()` query-builder functions
  instead.

## Migrations / init SQL

Schema is created by `services/postgres/init.sql`, mounted read-only and run
by the official Postgres image's `docker-entrypoint-initdb.d` mechanism on
first container start only — it does not re-run against an existing data
volume. Statements are `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT
EXISTS`, so the script is safe to leave in place across restarts, but it is
**not** a repeatable migration mechanism: there is no versioning, no
up/down migration history, and no automatic application of schema changes to
an already-initialized volume.

An Alembic scaffold exists at
`services/rag_server/infrastructure/database/migrations/` (`env.py`
configured for async SQLAlchemy migrations, autogenerate wired to the ORM
`Base.metadata`) but the `versions/` directory contains no migration files —
only an empty `__init__.py`. Alembic is not currently used to evolve the
schema; `init.sql` is the sole source of truth for what tables/indexes exist,
and any schema change today means hand-editing `init.sql` plus (for an
existing deployment) manually applying the equivalent `ALTER`/`CREATE INDEX`
statements against the live database.

Role/grant setup is handled by two shell scripts run alongside `init.sql`:
`services/postgres/00-roles.sh` and `services/postgres/02-grants.sh`,
consuming the `RAG_SERVER_DB_USER`/`RAG_SERVER_DB_PASSWORD` Docker secrets to
create and grant the application role.

## Eval runs are not stored in Postgres

Evaluation run results are **not** relational data. The `evals` service
persists each run as a flat file under `data/eval_runs/` (a host bind mount,
configurable via `EvalConfig.runs_dir`, default `Path("data/eval_runs")`) —
there is no `eval_runs` table, and no code path in the `evals` service writes
run results to PostgreSQL. Anyone expecting to query eval history via SQL
will not find it there; see `eval-framework.md` for the run-record format and
what's stored per run.
