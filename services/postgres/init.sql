-- PostgreSQL initialization script for RAG system
-- Run by docker-entrypoint-initdb.d on first container start, and safe to
-- re-run against an already-initialized database (`just db-reconcile`) —
-- every statement is idempotent. CREATE TABLE IF NOT EXISTS's column list is
-- a no-op on a table that already exists, so a column added to an existing
-- table also needs an explicit ALTER TABLE ADD COLUMN IF NOT EXISTS below.

-- Extensions: pg_textsearch for BM25 search, pgvector + pgvectorscale for vectors
CREATE EXTENSION IF NOT EXISTS pg_textsearch;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;

-- Documents table (source files)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_path TEXT,
    file_size_bytes BIGINT,
    file_hash VARCHAR(64) UNIQUE,
    uploaded_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'
);

-- Document chunks (text content for BM25 search plus its embedding vector)
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    -- Contextual-retrieval prefixes (when enabled) are prepended to the chunk
    -- text before it is stored, so this column is what the BM25 index covers.
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    -- Stable coordinates in the original source document. Kept separately
    -- from retrieval metadata so re-chunking does not invalidate gold anchors.
    source_locator JSONB,
    -- Nullable: a chunk row can exist before its embedding is written. NULL
    -- rows are neither indexed nor returned by the vector retriever.
    -- Dimension matches Qwen/Qwen3-Embedding-0.6B served via TEI (1024-dim).
    embedding vector(1024),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

-- Column reconciliation for document_chunks: a no-op on a fresh database
-- (already covered by CREATE TABLE above), but the only thing that actually
-- adds a column added later to CREATE TABLE's list on a pre-existing table.
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS source_locator JSONB;

-- BM25 index via pg_textsearch (Timescale) for ranked full-text search
CREATE INDEX IF NOT EXISTS idx_chunks_bm25 ON document_chunks
USING bm25 (content) WITH (text_config='english');

-- Vector index via pgvectorscale StreamingDiskANN; cosine distance only
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks
USING diskann (embedding vector_cosine_ops);

-- Per-document timing, token usage and outcome for the ingestion pipeline.
-- These rows are separate from chunk metadata so observing a failed or skipped
-- stage never changes the data used by retrieval.
CREATE TABLE IF NOT EXISTS document_ingestion_stages (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    stage         TEXT NOT NULL,
    -- Explicit pipeline order. Every row of one attempt is written in a single
    -- transaction and therefore shares created_at, and the id tiebreak is a
    -- random UUID, so ordering by those two returns stages in arbitrary order.
    stage_index   INTEGER NOT NULL DEFAULT 0,
    duration_ms   DOUBLE PRECISION NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    item_count    INTEGER,
    status        TEXT NOT NULL DEFAULT 'ok',
    error         TEXT,
    details       JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_stages_doc
    ON document_ingestion_stages(document_id, stage_index);

-- Chat sessions
CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY,
    title VARCHAR(255) DEFAULT 'New Chat',
    llm_model VARCHAR(100),
    search_type VARCHAR(20),
    is_archived BOOLEAN DEFAULT FALSE,
    is_temporary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Chat messages
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id);

-- Job batches (progress tracking)
CREATE TABLE IF NOT EXISTS job_batches (
    id UUID PRIMARY KEY,
    total_tasks INTEGER NOT NULL,
    completed_tasks INTEGER DEFAULT 0,
    status VARCHAR(30) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Job tasks (also serves as the work queue via SKIP LOCKED)
CREATE TABLE IF NOT EXISTS job_tasks (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES job_batches(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    status VARCHAR(30) DEFAULT 'pending',
    attempt INTEGER DEFAULT 0,
    total_chunks INTEGER DEFAULT 0,
    completed_chunks INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_batch ON job_tasks(batch_id);
-- Partial index: only pending tasks for fast SKIP LOCKED claims
CREATE INDEX IF NOT EXISTS idx_tasks_claimable ON job_tasks(created_at) WHERE status = 'pending';

-- Evaluation experiment store. A run remains independently exportable as JSON
-- during the dual-write transition, while these normalized rows make stage-level
-- failure questions queryable without reparsing a JSON artifact.
CREATE TABLE IF NOT EXISTS experiments (
    id                       TEXT PRIMARY KEY,
    name                     TEXT NOT NULL,
    corpus_snapshot_id       TEXT NOT NULL,
    chunking_config          JSONB NOT NULL DEFAULT '{}',
    embedding_model          TEXT NOT NULL,
    retrieval_settings       JSONB NOT NULL DEFAULT '{}',
    reranker_model           TEXT,
    prompts_hash             TEXT,
    judge_model              TEXT,
    judge_execution_boundary TEXT,
    judging_mode             TEXT NOT NULL CHECK (judging_mode IN ('inline', 'out_of_band', 'none')),
    code_version             TEXT NOT NULL,
    identity                 JSONB NOT NULL DEFAULT '{}',
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_experiments_snapshot ON experiments(corpus_snapshot_id);

CREATE TABLE IF NOT EXISTS runs (
    id               TEXT PRIMARY KEY,
    experiment_id    TEXT NOT NULL REFERENCES experiments(id),
    name             TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    completed_at     TIMESTAMPTZ,
    datasets         JSONB NOT NULL DEFAULT '[]',
    question_count   INTEGER NOT NULL,
    error_count      INTEGER NOT NULL DEFAULT 0,
    config           JSONB NOT NULL DEFAULT '{}',
    metadata         JSONB NOT NULL DEFAULT '{}',
    weighted_score   JSONB,
    created_on       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_experiment ON runs(experiment_id);

CREATE TABLE IF NOT EXISTS run_metrics (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id         TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    metric_name    TEXT NOT NULL,
    metric_group   TEXT NOT NULL,
    value          DOUBLE PRECISION,
    sample_size    INTEGER NOT NULL,
    details        JSONB NOT NULL DEFAULT '{}',
    UNIQUE(run_id, metric_name)
);

CREATE INDEX IF NOT EXISTS idx_run_metrics_name ON run_metrics(metric_name);

CREATE TABLE IF NOT EXISTS run_questions (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    question_id           TEXT NOT NULL,
    question              JSONB NOT NULL,
    response              JSONB NOT NULL,
    primary_failure_stage TEXT,
    failure_labels        TEXT[] NOT NULL DEFAULT '{}',
    UNIQUE(run_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_run_questions_primary_failure
    ON run_questions(primary_failure_stage);
CREATE INDEX IF NOT EXISTS idx_run_questions_failure_labels
    ON run_questions USING GIN(failure_labels);

CREATE TABLE IF NOT EXISTS question_stages (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_question_id BIGINT NOT NULL REFERENCES run_questions(id) ON DELETE CASCADE,
    stage           TEXT NOT NULL CHECK (stage IN (
        'retrieval_miss', 'fusion_miss', 'rerank_drop', 'context_truncated',
        'generation_drift', 'citation_error', 'wrong_abstention',
        'missed_abstention', 'correct'
    )),
    supported       BOOLEAN NOT NULL DEFAULT FALSE,
    assessable      BOOLEAN NOT NULL DEFAULT FALSE,
    evidence        JSONB NOT NULL DEFAULT '{}',
    UNIQUE(run_question_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_question_stages_supported
    ON question_stages(stage, run_question_id) WHERE supported;

-- Grants are handled in 02-grants.sh using secrets-backed roles.
