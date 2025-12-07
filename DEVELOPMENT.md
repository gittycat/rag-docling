# Development Guide

This guide contains detailed technical information for developers working on this RAG system.

## API Documentation

### Authentication
- None at this point. This application is meant to run locally.

### Core Endpoints

#### POST /upload
Upload documents for indexing (async via Celery).

**Request:**
```bash
curl -X POST http://localhost:8001/upload \
  -F "files=@document.pdf"
```

**Response:**
```json
{
  "status": "queued",
  "batch_id": "abc-123",
  "tasks": [
    {
      "task_id": "task-1",
      "filename": "document.pdf"
    }
  ]
}
```

**Supported Formats:** `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`, `.adoc`

#### GET /tasks/{batch_id}/status
Get upload batch progress.

**Response:**
```json
{
  "batch_id": "abc-123",
  "total": 2,
  "completed": 1,
  "total_chunks": 25,
  "completed_chunks": 10,
  "tasks": {
    "task-1": {
      "status": "completed",
      "filename": "document.pdf",
      "chunks": 5
    },
    "task-2": {
      "status": "processing",
      "filename": "document2.pdf"
    }
  }
}
```

#### POST /query
Search documents and get AI-generated answer.

**Request:**
```json
{
  "query": "What is the main topic?",
  "session_id": "user-123",
  "n_results": 5
}
```

**Response:**
```json
{
  "answer": "Based on the documents...",
  "sources": [
    {
      "document_name": "file.pdf",
      "excerpt": "The main topic is...",
      "full_text": "...",
      "path": "/docs/file.pdf",
      "distance": 0.15
    }
  ],
  "query": "What is the main topic?",
  "session_id": "user-123"
}
```

#### GET /documents
List all indexed documents (grouped by document_id).

**Response:**
```json
{
  "documents": [
    {
      "id": "doc-123",
      "file_name": "document.pdf",
      "file_type": ".pdf",
      "path": "/docs",
      "chunks": 5,
      "file_size_bytes": 102400
    }
  ]
}
```

#### DELETE /documents/{document_id}
Delete a document and all its chunks.

**Response:**
```json
{
  "status": "success",
  "message": "Document deleted successfully",
  "deleted_chunks": 5
}
```

#### GET /chat/history/{session_id}
Get conversation history for a session.

**Response:**
```json
{
  "session_id": "user-123",
  "messages": [
    {
      "role": "user",
      "content": "What is the main topic?"
    },
    {
      "role": "assistant",
      "content": "Based on the documents..."
    }
  ]
}
```

#### POST /chat/clear
Clear chat history for a session.

**Request:**
```json
{
  "session_id": "user-123"
}
```

#### GET /health
Health check endpoint.

#### GET /models/info
Get current model configuration.

**Response:**
```json
{
  "llm_model": "gemma3:4b",
  "embedding_model": "nomic-embed-text:latest",
  "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
  "ollama_url": "http://host.docker.internal:11434",
  "enable_reranker": true,
  "enable_hybrid_search": true,
  "enable_contextual_retrieval": true
}
```

## Configuration

All settings are defined in the [docker-compose.yml](docker-compose.yml).
Again, this application is run locally. No authentication is used for ChromaDB.

### Environment Variables

**RAG Server (docker-compose.yml):**

**Core Settings:**
- `CHROMADB_URL`: ChromaDB endpoint (default: `http://chromadb:8000`)
- `OLLAMA_URL`: Ollama endpoint (default: `http://host.docker.internal:11434`)
- `EMBEDDING_MODEL`: Embedding model (default: `nomic-embed-text:latest`)
- `LLM_MODEL`: LLM model (default: `gemma3:4b`)
- `REDIS_URL`: Redis endpoint (default: `redis://redis:6379/0`)

**Retrieval Configuration:**
- `RETRIEVAL_TOP_K`: Number of nodes to retrieve before reranking (default: `10`)
- `ENABLE_RERANKER`: Enable cross-encoder reranking (default: `true`)
- `RERANKER_MODEL`: Reranker model (default: `cross-encoder/ms-marco-MiniLM-L-6-v2`)

**Phase 2 Features:**
- `ENABLE_HYBRID_SEARCH`: Enable BM25 + Vector search (default: `true`)
- `RRF_K`: Reciprocal Rank Fusion k parameter (default: `60`)
- `ENABLE_CONTEXTUAL_RETRIEVAL`: Enable Anthropic contextual retrieval (default: `true`)

**Logging:**
- `LOG_LEVEL`: Logging level (default: `DEBUG` for rag-server, `INFO` for celery-worker)

**Evaluation (DeepEval with Anthropic):**
- `ANTHROPIC_API_KEY`: Anthropic API key for LLM-as-judge evaluation (required for eval)
- `EVAL_MODEL`: Claude model for evaluation (default: `claude-sonnet-4-20250514` - cost-effective)

### Docker Compose Networks

- **public**: RAG server (exposed to host on port 8001)
- **private**: ChromaDB, Redis, Celery Worker (internal only)

## Implementation Details

### Document Processing Pipeline

1. **Upload**: Documents uploaded via `/upload` endpoint
2. **Async Processing**: Celery worker processes each file
3. **Docling Parsing**: DoclingReader extracts text, tables, structure
4. **Contextual Enhancement**: LLM adds document context to each chunk
5. **Structural Chunking**: DoclingNodeParser creates nodes preserving hierarchy
6. **Embedding**: Each chunk embedded with context (nomic-embed-text)
7. **Storage**: Nodes stored in ChromaDB with metadata
8. **BM25 Refresh**: BM25 index updated with new nodes

### Query Processing Pipeline

1. **Query Received**: User query + optional session_id
2. **Memory Loading**: Previous conversation loaded from Redis
3. **Query Condensation**: Standalone question created if conversational
4. **Hybrid Retrieval**:
   - BM25 retriever finds keyword matches
   - Vector retriever finds semantic matches
   - RRF merges results (k=60)
5. **Reranking**: Cross-encoder reranks top-k nodes
6. **Top-n Selection**: Best 5-10 nodes selected as context
7. **LLM Generation**: Answer generated using context + memory
8. **Memory Update**: Conversation saved to Redis (1-hour TTL)
9. **Response**: Answer + sources returned

### Key Features

- **Document Structure Preservation**: Maintains headings, sections, tables as separate nodes
- **Hybrid Retrieval**: BM25 (exact matching) + Vector (semantic understanding)
- **Contextual Enhancement**: Document context embedded with chunks
- **Two-Stage Precision**: Reranking refines hybrid search results
- **Conversational Memory**: Redis-backed chat history with session management
- **Data Protection**: Automated backups, startup persistence verification
- **Async Processing**: Celery handles document uploads in background
- **Progress Tracking**: Real-time upload progress via Redis

## Phase 2 Implementation

### Hybrid Search (BM25 + Vector + RRF)

Combines sparse (keyword) and dense (semantic) retrieval for 48% improvement in retrieval quality:

- **BM25 Retriever**: Excels at exact keywords, IDs, names, abbreviations
- **Vector Retriever**: Excels at semantic understanding, contextual meaning
- **RRF Fusion**: Reciprocal Rank Fusion with k=60 (optimal per research)
  - Formula: `score = 1/(rank + k)`
  - No hyperparameter tuning required

**How it works:**
1. Query runs through both BM25 and Vector retrievers
2. Results merged using RRF (k=60)
3. Top-k combined results passed to reranker
4. Final top-n results returned as context

**Auto-initialization:**
- BM25 index pre-loads at startup if documents exist
- Auto-refreshes after document uploads/deletions

### Contextual Retrieval (Anthropic Method)

Adds document-level context to chunks before embedding for 49% reduction in retrieval failures:

**The Problem:**
```
Original Chunk: "The three qualities are: natural aptitude, deep interest, and scope."
Query: "What makes great work?"
Result: ❌ MISSED (no direct term match)
```

**The Solution:**
```
Enhanced Chunk: "This section from Paul Graham's essay 'How to Do Great Work'
discusses the essential qualities for great work. The three qualities are:
natural aptitude, deep interest, and scope."
```

**Implementation:**
1. For each chunk, LLM generates 1-2 sentence context
2. Context prepended to original chunk text
3. Enhanced chunk embedded (context embedded once at indexing time)
4. Query-time: Zero overhead (context already embedded)

**Performance:**
- 49% reduction in retrieval failures
- 67% reduction when combined with reranking

See `docs/PHASE2_IMPLEMENTATION_SUMMARY.md` for complete details.

## Known Issues & Fixes

### DoclingReader/DoclingNodeParser Integration (FIXED)

**Issue**: Document upload fails with Pydantic validation error if DoclingReader export format is not specified.

**Root Cause**: DoclingReader defaults to MARKDOWN export, but DoclingNodeParser requires JSON format.

**Fix**: Always use JSON export in `document_processor.py`:
```python
reader = DoclingReader(export_type=DoclingReader.ExportType.JSON)
```

### ChromaDB Metadata Compatibility (FIXED)

**Issue**: ChromaDB rejects complex metadata types (lists, dicts) from Docling.

**Fix**: Filter metadata to flat types (str, int, float, bool, None) using `clean_metadata_for_chroma()` function before insertion.

### CondensePlusContextChatEngine Integration (FIXED)

**Issue**: Custom hybrid retriever integration with CondensePlusContextChatEngine failing.

**Fix**: Pass retriever directly to `CondensePlusContextChatEngine.from_defaults()`:
```python
chat_engine = CondensePlusContextChatEngine.from_defaults(
    retriever=retriever,  # Not query_engine
    memory=memory,
    node_postprocessors=create_reranker_postprocessors(),
    ...
)
```

## Troubleshooting

### Ollama Connection Issues

```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# Check models are available
ollama list

# Pull missing models
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

### ChromaDB Connection Issues

```bash
# Check ChromaDB logs
docker compose logs chromadb

# Restart ChromaDB
docker compose restart chromadb
```

### View Service Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f rag-server
docker compose logs -f celery-worker
docker compose logs -f redis
```

### Reset Database

```bash
# Stop services
docker compose down

# Remove ChromaDB volume
docker volume rm rag-docling_chroma_db_data

# Restart
docker compose up -d
```

## Roadmap

### Completed (Phase 1 - 2025-10-13)
- [x] Redis-backed chat memory (conversations persist across restarts)
- [x] ChromaDB backup/restore automation
- [x] Reranker optimization (top-n selection)
- [x] Startup persistence verification
- [x] Dependency updates (ChromaDB 1.1.1, FastAPI 0.118.3, Redis 6.4.0)

See `docs/PHASE1_IMPLEMENTATION_SUMMARY.md` for details.

### Completed (Phase 2 - 2025-10-14)
- [x] Hybrid search (BM25 + Vector + RRF) - 48% retrieval improvement
- [x] Contextual retrieval (Anthropic method) - 49% fewer failures
- [x] Auto-refresh BM25 after uploads/deletes
- [x] End-to-end testing and validation

See `docs/PHASE2_IMPLEMENTATION_SUMMARY.md` for details.

### Planned (Phase 3+)
- [ ] Parent document retrieval (sentence window)
- [ ] Query fusion (multi-query generation)
- [ ] DeepEval evaluation framework
- [ ] Expanded golden QA dataset (50+ test cases)
- [ ] Production monitoring dashboard
- [ ] Support for additional file formats (CSV, JSON)
- [ ] Multi-user support with authentication
- [ ] Export search results

See `docs/RAG_ACCURACY_IMPROVEMENT_PLAN_2025.md` for future plans.

## Testing

The project follows Test-Driven Development (TDD) methodology:

- **60 total tests** (all passing)
  - 33 RAG server core tests (Docling processing, embeddings, LlamaIndex integration, LLM, pipeline, API)
  - 27 evaluation tests (RAGAS metrics, dataset loading, report generation)

Run all tests:
```bash
# RAG Server core tests
cd services/rag_server && .venv/bin/pytest -v

# RAG Server evaluation tests
cd services/rag_server && .venv/bin/pytest tests/evaluation/ -v
```
