# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local RAG system with FastAPI REST API using Docling + LlamaIndex for document processing, ChromaDB for vector storage, and Ollama for LLM inference. The system implements Phase 2 high-impact retrieval improvements: Hybrid Search (BM25 + Vector + RRF) and Contextual Retrieval (Anthropic method).

## Architecture

### Service Design

- `rag-server` (port 8001): RAG API service - exposed to host for client integration
- `celery-worker`: Async document processing worker
- `redis`: Message broker + result backend for Celery, chat memory persistence, progress tracking
- `chromadb`: Vector database (persistent storage)

### Network Isolation

- `public` network: RAG server accessible from host on port 8001
- `private` network: Internal services (ChromaDB, Redis, Celery)
- Ollama runs on host machine at `http://host.docker.internal:11434`

### Document Processing Flow

**Upload (Async via Celery):**
1. Documents uploaded → `rag-server` `/upload` endpoint
2. Files saved to `/tmp/shared` volume, Celery tasks queued (one per file)
3. Celery worker processes tasks: DoclingReader → contextual prefix → DoclingNodeParser → nodes
4. Embeddings generated per-chunk with progress tracking (via Redis)
5. Nodes stored in ChromaDB via VectorStoreIndex
6. BM25 index refreshed with new nodes

**Query (Synchronous):**
1. Query → hybrid retrieval (BM25 + Vector + RRF with top-k=10)
2. Reranking → top-n selection (5-10 nodes)
3. LLM (gemma3:4b) generates answer with retrieved context
4. Chat history saved to Redis (session-based, 1-hour TTL)

### Key Patterns

- **Phase 2 Features**:
  - **Hybrid Search**: BM25 (sparse) + Vector (dense) with RRF fusion (k=60) - 48% retrieval improvement
  - **Contextual Retrieval**: LLM-generated document context prepended to chunks - 49% reduction in failures
  - **BM25 Auto-refresh**: Index updates after uploads/deletes
- **Async Document Processing**: Celery + Redis for background upload processing with real-time progress tracking
- **Document Storage**: Nodes stored with `document_id` metadata, ID format: `{doc_id}-chunk-{i}`
- **Retrieval Strategy**: Three-stage (hybrid BM25+Vector → RRF fusion → reranking → top-n selection)
- **Dynamic Context**: Returns 5-10 nodes based on reranking scores, not fixed top-k
- **Conversational RAG**: Session-based memory with `condense_plus_context` mode, Redis-backed persistence ([details](docs/CONVERSATIONAL_RAG.md))
- **Prompts**: LlamaIndex native prompts (system_prompt, context_prompt, condense_prompt)
- **Progress Tracking**: Redis-based progress tracking for async uploads
- **Data Protection**: ChromaDB persistence verification on startup, automated backup/restore scripts

## Async Upload Architecture

### Upload Flow

1. **Client**: Uploads files → `POST /upload`
2. **RAG Server**: Saves files to `/tmp/shared`, queues Celery tasks, returns `batch_id`
3. **Celery Worker**: Processes tasks asynchronously, updates Redis progress
4. **Client**: Polls `GET /tasks/{batch_id}/status` for progress
5. **Completion**: All tasks complete, files indexed in ChromaDB + BM25

### Progress Tracking

- **Storage**: Redis (key: `batch:{batch_id}`, TTL: 1 hour)
- **Structure**: `{batch_id, total, completed, total_chunks, completed_chunks, tasks: {task_id: {...}}}`
- **Granularity**: Per-task status + per-chunk progress (for large documents)
- **Updates**: Client polls progress endpoint

### Shared Volume

- **Path**: `/tmp/shared` (Docker volume `docs_repo`)
- **Purpose**: File transfer between RAG server and Celery worker
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
docker compose logs -f celery-worker
docker compose logs -f redis

# Stop services
docker compose down -v
```

### Testing

```bash
# RAG Server tests (33 core tests)
cd services/rag_server
uv sync
.venv/bin/pytest -v

# Evaluation tests (27 tests)
.venv/bin/pytest tests/evaluation/ -v
```

### Evaluation

**Framework:** DeepEval with Anthropic Claude (migrated from RAGAS on 2025-12-07)

See [docs/DEEPEVAL_IMPLEMENTATION_SUMMARY.md](docs/DEEPEVAL_IMPLEMENTATION_SUMMARY.md) for complete guide.

```bash
cd services/rag_server
uv sync --group eval

# Quick evaluation (5 test cases)
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python -m evaluation.cli eval --samples 5

# Full evaluation
.venv/bin/python -m evaluation.cli eval

# Show dataset stats
.venv/bin/python -m evaluation.cli stats

# Pytest integration
pytest tests/test_rag_eval.py --run-eval --eval-samples=5
```

## Critical Implementation Details

### Phase 2: Hybrid Search & Contextual Retrieval

**Hybrid Search** (`services/rag_server/core_logic/hybrid_retriever.py`):
- Combines BM25 (sparse/keyword) + Vector (dense/semantic) retrieval
- Reciprocal Rank Fusion (RRF) with k=60 for result merging
- Auto-initializes at startup, auto-refreshes after uploads/deletes
- 48% improvement in retrieval quality (Pinecone benchmark)

**Contextual Retrieval** (`services/rag_server/core_logic/document_processor.py`):
- LLM generates 1-2 sentence document context for each chunk
- Context prepended before embedding (zero query-time overhead)
- 49% reduction in retrieval failures (67% with reranking)
- Anthropic method implementation

**Integration** (`services/rag_server/core_logic/rag_pipeline.py`):
- Hybrid retriever passed directly to `CondensePlusContextChatEngine.from_defaults(retriever=retriever)`
- Falls back to vector-only search if hybrid disabled
- Dynamic switching based on `ENABLE_HYBRID_SEARCH` env var

### Docling + LlamaIndex Integration

**Document Processing** (`services/rag_server/core_logic/document_processor.py`):
- **CRITICAL**: Must use `DoclingReader(export_type=DoclingReader.ExportType.JSON)` - DoclingNodeParser requires JSON format, not default MARKDOWN
- ChromaDB metadata must be flat types (str, int, float, bool, None) - complex types filtered via `clean_metadata_for_chroma()`
- Contextual prefix added via `add_contextual_prefix()` before chunking

**Embeddings** (`services/rag_server/core_logic/embeddings.py`):
- `OllamaEmbedding` with `model_name` parameter
- Default: `nomic-embed-text:latest`

**Vector Store** (`services/rag_server/core_logic/chroma_manager.py`):
- `ChromaVectorStore` wraps ChromaDB collection
- `VectorStoreIndex.from_vector_store()` creates index
- Direct ChromaDB access via `._vector_store._collection` for deletion/listing
- `get_all_nodes()` exposes nodes for BM25 indexing

**RAG Pipeline** (`services/rag_server/core_logic/rag_pipeline.py`):
- Hybrid retriever: `create_hybrid_retriever()` → `CondensePlusContextChatEngine.from_defaults(retriever=...)`
- Vector-only fallback: `index.as_chat_engine(chat_mode="condense_plus_context")`
- Reranking: `SentenceTransformerRerank` with top-n selection (returns top 5-10 nodes)
- Session-based memory via `ChatMemoryBuffer` with Redis-backed persistence
- Pre-initializes reranker model at startup to avoid first-query timeout

**Reranking Strategy**:
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (auto-downloads from HuggingFace)
- Selection: top-n approach (returns top 5 nodes by default, or half of retrieval_top_k)
- Configurable via env vars: `ENABLE_RERANKER`, `RERANKER_MODEL`, `RETRIEVAL_TOP_K`

### Docker Build

**PyTorch CPU Index:** Dockerfile uses `--index-strategy unsafe-best-match` to resolve package version conflicts between PyTorch CPU index and PyPI.

**Build Tools:** Includes gcc, g++, make for pystemmer compilation (required by BM25)

### Environment Variables

**RAG Server (required):**
- `CHROMADB_URL`, `OLLAMA_URL`, `EMBEDDING_MODEL`, `LLM_MODEL`, `REDIS_URL`

**RAG Server (retrieval):**
- `ENABLE_RERANKER=true`, `RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`, `RETRIEVAL_TOP_K=10`
- `ENABLE_HYBRID_SEARCH=true`, `RRF_K=60`
- `ENABLE_CONTEXTUAL_RETRIEVAL=false` (default: off for speed, set to true for 49% better accuracy)

**RAG Server (Ollama optimization):**
- `OLLAMA_KEEP_ALIVE=10m` (keep model loaded: 10m, -1 for indefinite, 0 to unload immediately)

**RAG Server (logging):**
- `LOG_LEVEL=DEBUG` (INFO for production)

**Celery Worker:**
- Same env vars as RAG Server (shares configuration)

## API Endpoints

**RAG Server** (port 8001):
- `GET /health`: Health check endpoint
- `GET /models/info`: Get LLM, embedding, and reranker model info
- `POST /query`: Chat query with session_id (optional, auto-generates if missing)
- `GET /chat/history/{session_id}`: Get conversation history
- `POST /chat/clear`: Clear chat history for session
- `GET /documents`: List all indexed documents (grouped by document_id)
- `POST /upload`: Upload documents (async via Celery, returns batch_id)
- `GET /tasks/{batch_id}/status`: Get upload batch progress
- `DELETE /documents/{document_id}`: Delete document and all nodes

**Supported Formats:**
`.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`, `.adoc`

## Key Files

**Core Pipeline:**
- `services/rag_server/core_logic/rag_pipeline.py`: Chat engine with hybrid search + reranking + memory
- `services/rag_server/core_logic/hybrid_retriever.py`: BM25 + Vector + RRF implementation (Phase 2)
- `services/rag_server/core_logic/chat_memory.py`: Session-based ChatMemoryBuffer with RedisChatStore (persistent)
- `services/rag_server/core_logic/document_processor.py`: DoclingReader + contextual retrieval + DoclingNodeParser
- `services/rag_server/core_logic/chroma_manager.py`: VectorStoreIndex (supports progress callbacks + BM25 node access)
- `services/rag_server/core_logic/embeddings.py`: OllamaEmbedding
- `services/rag_server/core_logic/llm_handler.py`: Ollama LLM + native prompts
- `services/rag_server/core_logic/settings.py`: Global Settings initialization
- `services/rag_server/core_logic/progress_tracker.py`: Redis-based progress tracking
- `services/rag_server/main.py`: FastAPI endpoints

**Async Processing:**
- `services/rag_server/celery_app.py`: Celery application config
- `services/rag_server/tasks.py`: Celery tasks (process_document_task)

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

**BM25 not initializing:** Check `ENABLE_HYBRID_SEARCH=true` in docker-compose.yml. Requires documents in ChromaDB at startup, otherwise initializes after first upload.

**Contextual retrieval not working:** Check `ENABLE_CONTEXTUAL_RETRIEVAL=true` in docker-compose.yml. Verify LLM is accessible (check OLLAMA_URL).

**Redis connection:** Redis required for Celery + chat memory persistence + progress tracking. Check with `docker compose logs redis`.

**Celery worker issues:** Check `docker compose logs celery-worker`. Worker auto-restarts on crashes. Tasks timeout after 1 hour.

**Slow document processing:** Contextual retrieval (Phase 1) typically takes 85% of total processing time due to LLM calls per chunk. This is expected behavior. See [Performance Analysis](docs/PERFORMANCE_ANALYSIS.md) for optimization options.

## Detailed Documentation

For comprehensive guides on specific topics, see:

- **[DEVELOPMENT.md](DEVELOPMENT.md)** - Complete API documentation, configuration details, troubleshooting, and roadmap
- **[Conversational RAG Architecture](docs/CONVERSATIONAL_RAG.md)** - Session management, chat memory, model flexibility
- **[Performance Optimizations Summary](docs/PERFORMANCE_OPTIMIZATIONS_SUMMARY.md)** - Recent optimizations: contextual retrieval toggle, keep-alive (15x speedup)
- **[Performance Analysis](docs/PERFORMANCE_ANALYSIS.md)** - Document processing bottlenecks, timing breakdown, optimization opportunities
- **[Ollama Optimization Guide](docs/OLLAMA_OPTIMIZATION.md)** - Keep-alive settings, KV cache quantization, prompt caching investigation
- **[Evaluation System](docs/evaluation/EVALUATION_SYSTEM.md)** - RAGAS metrics, evaluation workflow, best practices
- **[Troubleshooting History](docs/troubleshooting/)** - Historical issues and fixes
- **[Accuracy Improvement Plan](docs/RAG_ACCURACY_IMPROVEMENT_PLAN_2025.md)** - Future optimizations and plans
- **[Phase 1 Implementation Summary](docs/PHASE1_IMPLEMENTATION_SUMMARY.md)** - Completed critical fixes (Redis chat store, backups, reranker cleanup)
- **[Phase 2 Implementation Summary](docs/PHASE2_IMPLEMENTATION_SUMMARY.md)** - Hybrid search & contextual retrieval (current implementation)

## Testing Strategy

**Test Files:**
- `services/rag_server/tests/`: 33 core tests + 27 evaluation tests

**Mocking Pattern:**
- DoclingReader/DoclingNodeParser mocked to return Node objects
- LlamaIndex components mocked via `@patch`
- VectorStoreIndex mocked with `._vector_store._collection` for ChromaDB access
