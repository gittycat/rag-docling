# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local RAG system with two FastAPI services using Docling + LlamaIndex for document processing, ChromaDB for vector storage, and Ollama for LLM inference.

## Architecture

### Service Design

- `fastapi_web_app` (port 8000): User-facing web interface with conversational UI
- `rag-server` (port 8001): Backend RAG processing service
- `celery-worker`: Async document processing worker
- `redis`: Message broker + result backend for Celery
- `chromadb`: Vector database (persistent storage)

### Network Isolation

- `public` network: Web app accessible from host
- `private` network: Internal services (ChromaDB, RAG server, Redis, Celery)
- Ollama runs on host machine at `http://host.docker.internal:11434`

### Document Processing Flow

**Upload (Async via Celery):**
1. Documents uploaded → `rag-server` `/upload` endpoint
2. Files saved to `/tmp/shared` volume, Celery tasks queued (one per file)
3. Celery worker processes tasks: DoclingReader → DoclingNodeParser → nodes
4. Embeddings generated per-chunk with progress tracking (via Redis)
5. Nodes stored in ChromaDB via VectorStoreIndex

**Query (Synchronous):**
1. Query → retrieval (top-k=10) → reranking (top-n selection)
2. LLM (gemma3:4b) generates answer with retrieved context

### Key Patterns

- **Async Document Processing**: Celery + Redis for background upload processing with real-time progress tracking (SSE)
- **Document Storage**: Nodes stored with `document_id` metadata, ID format: `{doc_id}-chunk-{i}`
- **Retrieval Strategy**: Two-stage (high-recall embedding search → precision reranking)
- **Dynamic Context**: Returns 0-10 nodes based on relevance scores, not fixed top-k
- **Conversational RAG**: Session-based memory with `condense_plus_context` mode, Redis-backed persistence ([details](docs/CONVERSATIONAL_RAG.md))
- **Prompts**: LlamaIndex native prompts (system_prompt, context_prompt, condense_prompt)
- **Progress Tracking**: Redis-based progress tracking with SSE streaming to frontend
- **Data Protection**: ChromaDB persistence verification on startup, automated backup/restore scripts

## Async Upload Architecture

### Upload Flow

1. **Frontend**: User uploads files → `POST /admin/upload`
2. **Web App**: Proxies files to RAG server → `POST /upload`
3. **RAG Server**: Saves files to `/tmp/shared`, queues Celery tasks, returns `batch_id`
4. **Frontend**: Redirects to `/admin/upload/progress/{batch_id}`
5. **Progress Page**: Opens SSE stream → `GET /admin/upload/progress/{batch_id}/stream`
6. **Celery Worker**: Processes tasks asynchronously, updates Redis progress
7. **SSE Stream**: Polls Redis every 0.5s, streams progress updates to frontend
8. **Completion**: When all tasks done, SSE closes, redirects to admin page

### Progress Tracking

- **Storage**: Redis (key: `batch:{batch_id}`, TTL: 1 hour)
- **Structure**: `{batch_id, total, completed, total_chunks, completed_chunks, tasks: {task_id: {...}}}`
- **Granularity**: Per-task status + per-chunk progress (for large documents)
- **Updates**: Real-time via SSE (Server-Sent Events)

### Shared Volume

- **Path**: `/tmp/shared` (Docker volume `docs_repo`)
- **Purpose**: File transfer between web app, RAG server, and Celery worker
- **Cleanup**: Worker deletes files after processing (success or error)

## Common Commands

### Development

```bash
# Start services (requires Ollama running on host)
docker compose up -d

# Build after dependency changes
docker compose build

# View logs
docker compose logs -f rag-server
docker compose logs -f fastapi_web_app

# Stop services
docker compose down -v

# Monitor Celery worker
docker compose logs -f celery-worker

# Check Redis
docker compose logs -f redis
```

### Testing

```bash
# RAG Server tests (33 core tests)
cd services/rag_server
uv sync
.venv/bin/pytest -v

# Evaluation tests (27 tests)
.venv/bin/pytest tests/evaluation/ -v

# Web App tests (21 tests)
cd services/fastapi_web_app
uv sync
uv run pytest -v
```

### Evaluation

See [docs/evaluation/EVALUATION_SYSTEM.md](docs/evaluation/EVALUATION_SYSTEM.md) for complete evaluation guide.

```bash
cd services/rag_server
uv sync --group eval
.venv/bin/python evaluation/eval_runner.py
```

## Critical Implementation Details

### Docling + LlamaIndex Integration

**Document Processing** (`services/rag_server/core_logic/document_processor.py`):
- **CRITICAL**: Must use `DoclingReader(export_type=DoclingReader.ExportType.JSON)` - DoclingNodeParser requires JSON format, not default MARKDOWN
- ChromaDB metadata must be flat types (str, int, float, bool, None) - complex types filtered via `clean_metadata_for_chroma()`

**Embeddings** (`services/rag_server/core_logic/embeddings.py`):
- `OllamaEmbedding` with `model_name` parameter
- Default: `nomic-embed-text`

**Vector Store** (`services/rag_server/core_logic/chroma_manager.py`):
- `ChromaVectorStore` wraps ChromaDB collection
- `VectorStoreIndex.from_vector_store()` creates index
- Direct ChromaDB access via `._vector_store._collection` for deletion/listing

**RAG Pipeline** (`services/rag_server/core_logic/rag_pipeline.py`):
- `index.as_chat_engine(chat_mode="condense_plus_context")` with native prompts
- Reranking: `SentenceTransformerRerank` with top-n selection (returns top 5-10 nodes)
- Session-based memory via `ChatMemoryBuffer` with Redis-backed persistence
- Pre-initializes reranker model at startup to avoid first-query timeout

**Reranking Strategy**:
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (auto-downloads from HuggingFace)
- Selection: top-n approach (returns top 5 nodes by default, or half of retrieval_top_k)
- Configurable via env vars: `ENABLE_RERANKER`, `RERANKER_MODEL`, `RETRIEVAL_TOP_K`

### Docker Build

**PyTorch CPU Index:** Dockerfile uses `--index-strategy unsafe-best-match` to resolve package version conflicts between PyTorch CPU index and PyPI.

### Environment Variables

**RAG Server (required):**
- `CHROMADB_URL`, `OLLAMA_URL`, `EMBEDDING_MODEL`, `LLM_MODEL`, `REDIS_URL`

**RAG Server (reranker):**
- `ENABLE_RERANKER=true`, `RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`, `RETRIEVAL_TOP_K=10`

**RAG Server (logging):**
- `LOG_LEVEL=DEBUG` (INFO for production)

**Celery Worker:**
- Same env vars as RAG Server (shares configuration)

**Web App:**
- `RAG_SERVER_URL=http://rag-server:8001`

## API Endpoints

**RAG Server** (port 8001):
- `GET /health`: Health check endpoint
- `GET /models/info`: Get LLM, embedding, and reranker model info
- `POST /query`: Chat query with session_id (optional, auto-generates if missing)
- `GET /chat/history/{session_id}`: Get conversation history
- `POST /chat/clear`: Clear chat history for session
- `GET /documents`: List all indexed documents (grouped by document_id)
- `POST /upload`: Upload documents (async via Celery, returns batch_id)
- `GET /tasks/{batch_id}/status`: Get upload batch progress (for SSE streaming)
- `DELETE /documents/{document_id}`: Delete document and all nodes

**Supported Formats:**
`.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`, `.adoc`

## Key Files

**Core Pipeline:**
- `services/rag_server/core_logic/rag_pipeline.py`: Chat engine with reranking + memory
- `services/rag_server/core_logic/chat_memory.py`: Session-based ChatMemoryBuffer with RedisChatStore (persistent)
- `services/rag_server/core_logic/document_processor.py`: DoclingReader + DoclingNodeParser
- `services/rag_server/core_logic/chroma_manager.py`: VectorStoreIndex (supports progress callbacks)
- `services/rag_server/core_logic/embeddings.py`: OllamaEmbedding
- `services/rag_server/core_logic/llm_handler.py`: Ollama LLM + native prompts
- `services/rag_server/core_logic/settings.py`: Global Settings initialization
- `services/rag_server/core_logic/progress_tracker.py`: Redis-based progress tracking
- `services/rag_server/main.py`: FastAPI endpoints

**Async Processing:**
- `services/rag_server/celery_app.py`: Celery application config
- `services/rag_server/tasks.py`: Celery tasks (process_document_task)

**Frontend:**
- `services/fastapi_web_app/templates/base.html`: Base template with dark mode
- `services/fastapi_web_app/templates/home.html`: Conversational chat UI
- `services/fastapi_web_app/templates/admin.html`: Document management
- `services/fastapi_web_app/templates/upload_progress.html`: Real-time upload progress (SSE)
- `services/fastapi_web_app/main.py`: Web app routes + session management + SSE streaming

**Evaluation:**
- `services/rag_server/evaluation/`: RAGAS-based evaluation system
- `services/rag_server/eval_data/golden_qa.json`: Test Q&A dataset (10 pairs)

**Backup & Maintenance:**
- `scripts/backup_chromadb.sh`: Automated ChromaDB backup (30-day retention)
- `scripts/restore_chromadb.sh`: Restore from backup
- `scripts/README.md`: Backup/restore documentation

## Backup & Restore

### ChromaDB Backup
```bash
# Manual backup to default location (./backups/chromadb/)
./scripts/backup_chromadb.sh

# Schedule daily backups at 2 AM (add to crontab)
0 2 * * * cd /path/to/rag-docling && ./scripts/backup_chromadb.sh >> /var/log/chromadb_backup.log 2>&1
```

### ChromaDB Restore
```bash
# List available backups
ls -lh ./backups/chromadb/

# Restore from specific backup
./scripts/restore_chromadb.sh ./backups/chromadb/chromadb_backup_20251013_020000.tar.gz
```

**Features**: Timestamped backups, automatic cleanup, health check verification, service stop/start handling.

## Common Issues

**Ollama not accessible:**
```bash
docker compose exec rag-server curl http://host.docker.internal:11434/api/tags
```

**ChromaDB connection fails:** RAG server must be on `private` network.

**Docker build fails:** Ensure `--index-strategy unsafe-best-match` in Dockerfile.

**Tests fail:** Use `.venv/bin/pytest` directly instead of `uv run pytest`.

**Reranker performance:** First query downloads model (~80MB). Subsequent queries use cache. Adds ~100-300ms latency.

**Redis connection:** Redis required for Celery + chat memory persistence + progress tracking. Check with `docker compose logs redis`.

**Celery worker issues:** Check `docker compose logs celery-worker`. Worker auto-restarts on crashes. Tasks timeout after 1 hour.

## Detailed Documentation

For comprehensive guides on specific topics, see:

- **[Conversational RAG Architecture](docs/CONVERSATIONAL_RAG.md)** - Session management, chat memory, model flexibility
- **[Evaluation System](docs/evaluation/EVALUATION_SYSTEM.md)** - RAGAS metrics, evaluation workflow, best practices
- **[Frontend Styling Guide](docs/frontend/STYLING_GUIDE.md)** - Jinja2 templates, dark mode, Tailwind CSS design system
- **[Troubleshooting History](docs/troubleshooting/)** - Historical issues and fixes
- **[Accuracy Improvement Plan](docs/RAG_ACCURACY_IMPROVEMENT_PLAN_2025.md)** - Future optimizations and plans
- **[Phase 1 Implementation Summary](docs/PHASE1_IMPLEMENTATION_SUMMARY.md)** - Completed critical fixes (Redis chat store, backups, reranker cleanup)

## Testing Strategy

**Test Files:**
- `services/rag_server/tests/`: 33 core tests + 27 evaluation tests
- `services/fastapi_web_app/tests/`: 21 web app tests

**Mocking Pattern:**
- DoclingReader/DoclingNodeParser mocked to return Node objects
- LlamaIndex components mocked via `@patch`
- VectorStoreIndex mocked with `._vector_store._collection` for ChromaDB access
