
## Libraries
- When adding libraries or packages, search online and use the most current released version.
- Be progressive when selecting a library or package. Go for libraries and packages that have a high adoption rate unless it is not widely used (eg: less than 1K stars in github).

## Database
- Use SQL Schema for migrations (or migration tool output reviewed as SQL).
- Use **query builders** for most queries, not ORM.
- Optionally, lightweight mappings (dataclasses / pydantic models) without relying on ORM relationship loading for critical paths.
- Keep tricky SQL as explicit SQL (views, CTEs, window functions) and call it directly.


## Library and Tool documentation
Use the Svelte MCP server for any Svelte related coding, question or documentation.

Otherwise, use context7 when I need code generation, setup or configuration steps, or
library/API documentation. This means you should automatically use the Context7 MCP
tools to resolve library id when it is not known, and get library docs without me having to explicitly ask.

### Context7 IDs
For tailwind 4, use context7 with id: websites/tailwindcss
For DaisyUI doc, use context7 with id: websites/daisyui


## Language-Specific Guidelines

## Python

### Prefer Functions Over Classes
- Use module-level functions instead of classes for stateless operations
- Avoid singleton pattern (`_instance = None` + `get_instance()`) - just use functions
- Classes are appropriate for: stateful objects, resource lifecycle management, framework integration


### Documentation
- Skip docstrings on private helpers - use inline comments if non-obvious
- Type hints replace parameter/return documentation
- Keep public API docstrings to one line when possible

## Project Overview

Local RAG system: FastAPI + Docling + LlamaIndex + PostgreSQL (pg_textsearch BM25) + ChromaDB + Ollama. Implements Hybrid Search (BM25 + vector + RRF) and Contextual Retrieval.

## Architecture

- `webapp` (port 8000): SvelteKit UI — proxies `/api/eval/*` to evals, other `/api/*` to rag-server
- `rag-server` (port 8001): RAG API — `public` + `private` networks, exposed to host
- `evals` (port 8002): Standalone eval service (DeepEval) — `public` + `private` networks
- `task-worker`: Async document processing worker via SKIP LOCKED — `public` + `private` (public for host Ollama access)
- `postgres`: PostgreSQL 17 with pg_textsearch (BM25) — `private` network only
- `chromadb`: Vector database for embeddings — `private` network only
- Ollama: runs on host at `http://host.docker.internal:11434`

### Document Processing

**Upload:** POST /upload → files saved to `/tmp/shared` → tasks created in job_tasks table → worker claims via SKIP LOCKED → DoclingReader → contextual prefix → DoclingNodeParser → embeddings → ChromaDB (vectors) + PostgreSQL (text + pg_textsearch BM25)

**Query:** hybrid retrieval (BM25 + ChromaDB vectors + RRF, top-k=10) → SentenceTransformerRerank (top 5-10) → LLM answer → chat history saved to PostgreSQL

### Key Patterns
- **Hybrid Search**: pg_textsearch BM25 + ChromaDB vectors with RRF fusion (k=60), auto-indexes
- **Contextual Retrieval**: LLM-generated context prepended to chunks before embedding (toggle: `enable_contextual_retrieval` in config.yml)
- **Async Processing**: SKIP LOCKED on job_tasks table for work queue + PostgreSQL job_batches for progress tracking
- **Async Concurrency**: Evals use `asyncio.gather()` + `Semaphore` for parallel RAG queries and LLM judge calls. RAG server offloads sync generators/LLM calls to executor threads to avoid blocking FastAPI's event loop.
- **Conversational RAG**: `condense_plus_context` mode, `ChatMemoryBuffer` + `PostgresChatStore`
- **PII Masking**: opt-in (`pii.enabled` in config.yml) reversible Presidio token masking on all LLM-bound text — query path, session titles, contextual-retrieval ingestion (`infrastructure/pii/`)
- **Document IDs**: `{doc_id}-chunk-{i}`

## Package Management

**Tool:** `uv` (not pip). All services use `pyproject.toml`.

```bash
cd services/rag_server
uv sync                    # install deps
uv sync --group eval       # install with eval group
uv add <package>           # add dependency
uv add --group dev <pkg>   # add dev dependency
uv run pytest              # run commands in venv
```

## Commands

**Task runner:** `just` (context7 id: `just_systems-man`)

```bash
just test-unit             # unit tests
just test-integration      # integration tests (requires docker services)
just test-eval             # eval tests (requires API key for the active.eval provider)
just test-eval-full        # full eval suite
just eval ...              # custom eval run (tier/datasets/samples)
just show-config           # show RAG configuration
just show-config-full      # show full config with all settings
```

**Evaluation:** DeepEval in the standalone `services/evals` service; judge = `active.eval` model in config.yml. See `docs/dev/eval-framework.md`.
```bash
docker compose exec evals .venv/bin/python -m evals.cli eval --tier generation --datasets ragbench --samples 5
# or via API: POST http://localhost:8002/eval/runs
```

**CI/CD:** Forgejo with `.forgejo/workflows/ci.yml`. Core tests run on every push. Eval tests triggered with `[eval]` in commit message or manual dispatch.

## Critical Implementation Details

### Hybrid Search & Contextual Retrieval
- `pg_textsearch BM25Retriever` + `ChromaVectorStore` combined via `HybridRRFRetriever` (k=60)
- BM25 index auto-refreshes on insert/update/delete
- Falls back to vector-only if `enable_hybrid_search: false` in config.yml
- Contextual retrieval: `add_contextual_prefix_to_chunk()` in `pipelines/ingestion.py`

### Docling + LlamaIndex
- **CRITICAL**: Must use `DoclingReader(export_type=DoclingReader.ExportType.JSON)` — DoclingNodeParser requires JSON
- Reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`, pre-initialized at startup
- Embeddings: `OllamaEmbedding` (`nomic-embed-text:latest`, 768 dimensions)

### Docker Build
- Dockerfile uses `--index-strategy unsafe-best-match` for PyTorch CPU index resolution
- Includes gcc, g++, make for pystemmer compilation (sentence-transformers dep)

### Database Schema
```sql
-- services/postgres/init.sql
documents, document_chunks, chat_sessions, chat_messages, job_batches, job_tasks
-- Extensions: pg_textsearch
-- job_tasks serves as work queue via SKIP LOCKED (idx_tasks_claimable partial index)
-- Note: embedding vectors stored in ChromaDB, not PostgreSQL
```

### Configuration
- `config.yml`: all model settings, prompt templates, provider config
- API keys stored as files under `secrets/` (filename = key name)
- Supported providers: ollama/vllm (local), openai/anthropic/google/deepseek/moonshot (cloud, require API keys)
- Env vars (docker-compose.yml): `DATABASE_HOST`, `DATABASE_PORT`, `CHROMADB_HOST`, `CHROMADB_PORT`, `MAX_UPLOAD_SIZE=80`, `LOG_LEVEL=WARNING`

## Key Files

All under `services/rag_server/`:
- `pipelines/ingestion.py` — document chunking, contextual retrieval, embedding
- `pipelines/inference.py` — RAG query, hybrid search, reranking, chat engine
- `infrastructure/search/` — `vector_store.py`, `bm25_retriever.py`, `hybrid_retriever.py`
- `infrastructure/database/postgres.py` — async connection pool (asyncpg + SQLAlchemy 2.0)
- `infrastructure/database/` — `documents.py`, `sessions.py`, `jobs.py` (flat async functions, explicit session passing)
- `infrastructure/llm/factory.py` — multi-provider LLM client factory
- `infrastructure/pii/` — Presidio masking service, streaming unmask, guardrails, audit
- `infrastructure/tasks/` — `task_worker.py`, `worker.py`

Eval service under `services/evals/`: `evals/runner.py`, `evals/cli.py`, `api/`, datasets in `evals/data/` (golden_qa.json + public dataset cache).

## Common Issues

- **Docker build fails:** ensure `--index-strategy unsafe-best-match` in Dockerfile
- **Reranker slow on first query:** downloads model (~80MB), adds ~100-300ms
- **task-worker issues:** `docker compose logs task-worker` — auto-restarts, stuck tasks reset after 1 hour
- **Slow processing:** contextual retrieval takes ~85% of time (LLM calls per chunk)

## Testing

Tests in `services/rag_server/tests/` (and `services/evals/tests/`). Unit tests use `@patch` mocks. Integration tests require `--run-integration` flag. Eval tests require `--run-eval` flag + the API key for the `active.eval` provider.

### Integration Test Strategy
- **No separate test-runner service** — tests reuse the `rag-server` service definition to avoid config drift (env, secrets, volumes, networks)
- **Local/debug:** `docker compose exec -T rag-server .venv/bin/pytest tests/integration -v --run-integration` — fast, reuses running container
- **CI:** `docker compose run --rm rag-server .venv/bin/pytest tests/integration -v --run-integration` — fresh container, no state leakage
- `exec` uses `RAG_SERVER_URL=http://localhost:8001` (same container); `run` uses `http://rag-server:8001` (sibling container)
