# Architecture

RAGBench runs as a set of Docker Compose services on two Docker networks, `public`
and `private`. Compose orchestrates builds, health-gated startup ordering, volumes,
and secrets. This document covers the service inventory, the topology, the two main
request paths, and where the eval service fits relative to everything else. Pipeline
internals (chunking, contextual retrieval, embeddings) and retrieval mechanics (BM25,
RRF, reranking) are covered in `rag-pipeline.md` and `retrieval.md`.

## Service inventory

| Service | Role | Long-lived? | Notes |
|---|---|---|---|
| `webapp` | SvelteKit frontend, server-side proxy to the two backend APIs | Yes | Only service most users touch directly |
| `rag-server` | FastAPI app: document API, query/chat API, sessions, settings, health/metrics | Yes | Owns the ingestion queue and the inference pipeline |
| `postgres` | Relational store: documents, chat sessions/history, task queue, BM25 index | Yes | Never exposed outside the `private` network |
| `chromadb` | Vector store for chunk embeddings | Yes | Never exposed outside the `private` network |
| `task-worker` | Background ingestion processor | Yes | Same Docker image as `rag-server`, different entrypoint/command |
| `evals` | Evaluation API + CLI for RAG quality assessment | Yes | A plain HTTP client of `rag-server` — see below |

Two services are long-lived processes holding meaningful in-process state:
`rag-server` holds the two in-memory chat-memory caches and the PII session token
mapping (both process-local, both bounded — see `chat-and-memory.md` and
`pii-masking.md`); `evals` holds the active-job state and an in-memory index of
past runs rebuilt from disk at startup (see `eval-framework.md`). `task-worker` is
long-lived but stateless between tasks — all task state lives in Postgres.
`postgres` and `chromadb` are the only services with real persisted state.

## Docker topology and the network split

The base `docker-compose.yml` defines two bridge networks:

- **`public`**: host-reachable. `webapp`, `rag-server`, `task-worker`, and `evals`
  sit on it — `rag-server` and `task-worker` need it to reach Ollama at
  `host.docker.internal` when using local models.
- **`private`**: `internal: true` — no default gateway, no internet access, fully
  isolated. `postgres` and `chromadb` sit only here, reachable exclusively from
  `rag-server`, `task-worker`, and `evals` (all three are also attached to
  `private`).

`webapp` is the only service published to the host by default (`8000:3000`);
`rag-server` (`8001:8001`) and `evals` (`8002:8002`) also publish ports for direct
API access in the local/dev tier. Named volumes (`postgres_data`, `chroma_data`,
`docs_repo`) are Docker-managed; bind mounts (`config.yml`, `data/indexed_documents`,
`.cache/huggingface`) are host directories, chosen deliberately so PII masking
config, source documents, and downloaded model weights survive `docker compose
down -v` even though the named volumes would not.

### Overlays

The base file is combined with an overlay via `docker compose -f docker-compose.yml
-f docker-compose.<tier>.yml`, except two freestanding files that are never layered
on the base:

| File | Layers on base? | Purpose |
|---|---|---|
| `docker-compose.yml` | — | Full local/dev stack |
| `docker-compose.cloud.yml` | Yes | Replaces local `build:` with `image:` pulls for cloud deployment; templates `OLLAMA_HOST` for a separately hosted Ollama |
| `docker-compose.server.yml` | Yes | Adds a Caddy reverse proxy, removes direct port publishing from `webapp`/`rag-server`/`evals`, adds bearer-token auth — the tier for any deployment reached over a network rather than localhost |
| `docker-compose.bench.yml` | No (standalone) | Ephemeral benchmark stack: `tmpfs` Postgres, separate networks/volumes/ports so runs never touch dev data |
| `docker-compose.ci.yml` | No (standalone) | Self-hosted Forgejo + runner, independent of the app stack's lifecycle |

No compose file in the repo sets `deploy.resources` / CPU / memory limits on any
service — resource limiting is unconfigured across the whole stack.

## Request path (query/chat)

1. Client sends a chat message to `webapp`, which proxies `/api/*` to `rag-server`
   (and `/api/eval/*` to `evals`).
2. `rag-server` runs hybrid retrieval (BM25 via `pg_textsearch` in Postgres + vector
   search in ChromaDB, fused with RRF), reranks with a cross-encoder, and assembles
   a prompt.
3. The LLM (local via Ollama, or a cloud provider) generates the answer, optionally
   streamed over SSE.
4. The response, with sources, returns to the client through `webapp`.

Postgres and ChromaDB are only ever reached from `rag-server` / `task-worker` /
`evals`, never directly from `webapp` or the client — the `private` network
enforces this at the infrastructure level, not just by convention.

## Ingestion path

1. Client uploads a file; `webapp` proxies the upload to `rag-server`.
2. `rag-server` writes the file to a shared volume (`docs_repo`, mounted at
   `/tmp/shared`) and creates a row in the Postgres task queue (`job_tasks`).
3. `task-worker` claims the task via `SELECT ... FOR UPDATE SKIP LOCKED`, then runs
   Docling parsing → chunking → optional contextual enrichment → embedding →
   indexing (chunk text + BM25 into Postgres, embeddings into ChromaDB).
4. The client polls task/batch status by ID until ingestion completes.

`rag-server` and `task-worker` share the same Docker image and codebase — only the
container command differs (`main.py`'s FastAPI app vs. the task-worker entrypoint).
This is deliberate: task signatures must match between producer and consumer, and a
single dependency set avoids version drift between the two.

## Where the eval service sits

`evals` is not a privileged component of the RAG pipeline — it is an HTTP client of
`rag-server`, exactly like `webapp` or a curl script. It calls `rag-server`'s public
API (`/health`, `/models/info`, `/upload`, `/query`, `/query/with-context`,
`/tasks/{batch_id}/status`, `/documents/{id}`) to run evaluations, and has no
special internal access, no shared in-process state, and no direct connection to
Postgres or ChromaDB for RAG data (it does have its own on-disk JSON persistence
for eval runs — see `eval-framework.md`). It was split into its own service
specifically so its heavier dependencies (`datasets`, HuggingFace downloads) don't
bloat the `rag-server` image, and so a long eval run can't compete with `rag-server`
for its own process resources. The webapp proxies `/api/eval/*` to it on port 8002.

## Technology stack

Versions below are checked against `services/rag_server/pyproject.toml` and
`services/webapp/package.json` on this branch rather than carried over from
older documentation.

| Layer | Component | Version (as pinned) |
|---|---|---|
| Backend runtime | Python | 3.13+ |
| Backend runtime | uv | package manager, unpinned |
| API framework | FastAPI | 0.118.3+ |
| Database | PostgreSQL | 17 |
| Full-text search | pg_textsearch (Timescale extension) | — |
| Vector store | ChromaDB | 1.5.0+ |
| Task queue | PostgreSQL `SKIP LOCKED` | — |
| Document parser | Docling | 2.53.0+ |
| RAG framework | LlamaIndex core | 0.14.4+ |
| Reranker | sentence-transformers | 5.1.1+ |
| PII detection | presidio-analyzer / presidio-anonymizer | 2.2.363+ |
| PII NER model | spaCy `en_core_web_md` | 3.8.0 (pinned wheel) |
| PII optional recognizer | GLiNER | 0.2.28+ (optional dependency group) |
| Frontend framework | SvelteKit | 2.49.1+ |
| Frontend | Svelte | 5.45.6+ |
| Frontend | Vite | 7.2.6+ |
| UI library | DaisyUI | 5.5.14+ |
| CSS | Tailwind CSS | 4.1.17+ |
| Frontend charting | layerchart | 2.0.1+ |
| Frontend adapter | @sveltejs/adapter-node | 5.2.12+ |

The `rag-server` `pyproject.toml` also lists `pgvector` and
`llama-index-vector-stores-postgres` as dependencies, and there is a
`llama-index-vector-stores-postgres` import path available, but the code does not
use either for the actual vector index — `infrastructure/search/vector_store.py`
constructs a `ChromaVectorStore` backed by `chromadb`, and that is the only vector
store instantiated anywhere in the request path. Treat the pgvector dependency as
present-but-unused for this purpose.

LLM providers, selected per role (`llm`, `embedding`, `eval`) in `config.yml`:
Ollama (default, local), OpenAI, Anthropic, Google Gemini, DeepSeek, Moonshot, and
vLLM (OpenAI-compatible, self-hosted).

## Startup log line

`services/rag_server/main.py` logs, on every startup:

```
[STARTUP] Hybrid search enabled (pg_textsearch BM25 + ChromaDB vectors)
```

It used to read "pg_search BM25 + pgvector", which was wrong on both counts:
there is no `pg_search` extension (full-text search runs through the Timescale
`pg_textsearch` extension) and no `pgvector` column or index (vectors live
entirely in ChromaDB via the `ChromaVectorStore` integration described above).
Corrected per `docs/suggestions.md` #4.6; `/metrics/retrieval` carried the same
wrong `vector_store` value and now reports `ChromaDB` with the collection name
from `config.yml`.
