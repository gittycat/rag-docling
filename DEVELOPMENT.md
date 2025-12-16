# Development Guide

Complete technical reference for developers working on this RAG system. Covers architecture, API, configuration, testing, and deployment.

## Table of Contents

- [Architecture](#architecture)
- [Development Setup](#development-setup)
- [CI/CD](#cicd)
- [API Documentation](#api-documentation)
- [Configuration](#configuration)
- [Evaluation & Testing](#evaluation--testing)
- [Implementation Details](#implementation-details)
- [Troubleshooting](#troubleshooting)
- [RAG Observability](#rag-observability)
- [Roadmap](#roadmap)

## Architecture

### System Overview

```text

     ┌──────────────┐              ┌────────────────────────────────────┐
     │   End User   │              │   Ollama                           │
     │   (browser)  │              │                                    │
     └──────┬───────┘              │   • LLM: gemma3:4b                 │
            │                      │   • Embeddings: nomic-embed-text   │
            │                      └──────────────────┬─────────────────┘
            │                                         │ :11434 (localhost)
            │                                         │
            │         EXTERNAL NETWORK                │
            │         (host or cloud)                 │
   =========│=========================================│===================
            │         INTERNAL NETWORK                │
            │    (docker-compose priv network)        │
            │                                         │
            │ :8000                                   │
   ┌────────▼────────┐                                │
   │     WebApp      │ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│ ─ ─ ─ ─ ─ ─ ─ ┐
   │   (SvelteKit)   │                                │               │
   │                 │                                │               │
   └────────┬────────┘                                │               │
            │                                         │               │
            │ :8001                                   │               │
   ┌────────▼───────────────────────────────┐         │               │
   │            RAG Server (FastAPI)        │─────────┘               │
   │                                        │                         │
   │  ┌──────────────────────────────────┐  │                         │
   │  │  Docling + LlamaIndex            │  │                         │
   │  │  • Hybrid Search (BM25+Vector)   │  │                         │
   │  │  • Reranking                     │  │                         │
   │  │  • Contextual Retrieval          │  │                         │
   │  └──────────────────────────────────┘  │                         │
   └───────┬────────────────┬───────────────┘                         │
           │                │                                         │
           │                │ Celery task queue                       │
           │                │                                         │
   ┌───────▼──────┐  ┌──────▼──────┐  ┌─────────────────────┐         │
   │   ChromaDB   │  │    Redis    │  │    Celery Worker    │◄────────┘
   │  (Vectors)   │  │  (Broker +  │  │  (Async document    │
   │              │  │   Memory)   │  │   processing)       │
   └──────────────┘  └─────────────┘  └──────────┬──────────┘
                                                 │                       
   ┌─────────────────────────────────────────────▼────────────────┐
   │         Shared Volume: /tmp/shared (File Transfer)           │
   └──────────────────────────────────────────────────────────────┘

```

### Technology Stack

**Frontend:**
- SvelteKit 2.0 - Modern web framework
- Tailwind CSS 4 - Utility-first styling
- DaisyUI 5 - UI components and themes
- TypeScript - Type-safe JavaScript

**Backend:**
- Python 3.13 - Latest stable Python
- FastAPI 0.118+ - Modern async API framework
- LlamaIndex 0.14+ - RAG orchestration framework
- Docling 2.53+ - Document parsing

**Data Layer:**
- ChromaDB 1.1+ - Vector database
- Redis 6.4+ - Message broker & cache
- Celery 5.5+ - Async task queue

**AI Models (via Ollama):**
- gemma3:4b - Question answering (3B params)
- nomic-embed-text - Document embeddings (137M params)
- cross-encoder/ms-marco-MiniLM-L-6-v2 - Reranking (22M params)

**Development Tools:**
- uv - Fast Python package manager
- Docker Compose - Container orchestration
- pytest - Testing framework
- DeepEval - RAG evaluation framework

## Development Setup

### Prerequisites

1. **Python 3.13+** with [uv package manager](https://docs.astral.sh/uv/)
2. **Docker** (Docker Desktop, OrbStack, or Podman)
3. **Ollama** running on host machine

### Local Development

```bash
# Clone repository
git clone https://github.com/gittycat/rag-docling.git
cd rag-docling

# Install RAG server dependencies
cd services/rag_server
uv sync                    # Core dependencies
uv sync --group eval       # Add evaluation tools

# Install frontend dependencies
cd ../../services/webapp
npm install

# Start infrastructure
docker compose up chromadb redis -d

# Run RAG server locally (for debugging)
cd ../rag_server
.venv/bin/uvicorn main:app --reload --port 8001

# Run frontend locally (for debugging)
cd ../webapp
npm run dev
```

#### Svelte Web development
Use the prompt in `SVELTE_PROMPT.md` when requesting a tasks to be performed 
on the web frontend requiring Svelte or SvelteKit knowledge.

### Running Tests

This project uses [mise](https://mise.jdx.dev/) for task management. See `.mise.toml` for all tasks.

```bash
# Install dev dependencies
mise run dev

# Unit tests (32 tests, mocked, fast)
mise run test

# Integration tests (25 tests, requires docker compose up -d)
mise run test:integration

# Evaluation tests (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
mise run test:eval

# List all tasks
mise tasks

# Frontend tests
cd services/webapp
npm test
```

### Code Quality

```bash
# Python formatting (if using)
cd services/rag_server
.venv/bin/ruff format .
.venv/bin/ruff check .

# Frontend linting
cd services/webapp
npm run lint
```

## CI/CD

### Forgejo Setup

This project uses **Forgejo** - a lightweight, self-hosted Git service with integrated CI/CD (Actions). Forgejo provides GitHub-compatible workflows while keeping everything local.

**Why Forgejo:**
- Self-hosted (privacy & control)
- GitHub Actions syntax (95% compatible)
- Lightweight (~512MB RAM)
- Integrated CI/CD (no separate tools)

For complete setup instructions, see **[Forgejo CI/CD Setup Guide](docs/FORGEJO_CI_SETUP.md)**.

### Quick Start

```bash
# 1. Start Forgejo server and runner
docker compose -f docker-compose.ci.yml up -d

# 2. Access Web UI (first-time setup)
open http://localhost:3000
# Complete installation wizard and create admin account

# 3. Register the runner (get token from http://localhost:3000/admin/actions/runners)
docker exec -it forgejo-runner \
  forgejo-runner register \
  --instance http://forgejo:3000 \
  --token <YOUR_REGISTRATION_TOKEN> \
  --name docker-runner \
  --labels docker:docker://node:20,docker:docker://python:3.13

# 4. Restart runner to activate
docker compose -f docker-compose.ci.yml restart forgejo-runner

# 5. Create repository and push code
# In Forgejo Web UI: Create new repository "rag-docling"
git remote add forgejo http://localhost:3000/<username>/rag-docling.git
git push forgejo main
```

### CI Pipeline

The CI pipeline (`.forgejo/workflows/ci.yml`) runs automatically on every push and pull request.

**Jobs:**

1. **Core Tests** (always runs)
   - Duration: ~30 seconds
   - Tests: 32 unit tests (mocked)
   - Command: `pytest tests/ --ignore=tests/integration --ignore=tests/evaluation --ignore=tests/test_rag_eval.py`

2. **Evaluation Tests** (optional, off by default)
   - Duration: ~2-5 minutes
   - Tests: 27 DeepEval tests
   - Requires: `ANTHROPIC_API_KEY` secret
   - Triggers:
     - Manual workflow dispatch (Web UI button)
     - Commit message containing `[eval]`

3. **Docker Build** (always runs)
   - Duration: ~5-10 minutes
   - Verifies both `rag-server` and `webapp` images build successfully

### Running Evaluation Tests in CI

Eval tests are **OFF by default** to avoid unnecessary API costs.

**Method 1 - Commit Message Flag:**
```bash
git commit -m "feat: improve retrieval [eval]"
git push forgejo main
```

**Method 2 - Manual Trigger:**
1. Go to repository **Actions** tab in Forgejo
2. Select **CI** workflow
3. Click **Run workflow**
4. Check **Run evaluation tests**
5. Click **Run**

### Configuring Secrets

To run evaluation tests, add your Anthropic API key:

1. Repository **Settings** → **Secrets and Variables** → **Actions**
2. Click **New secret**
3. Name: `ANTHROPIC_API_KEY`
4. Value: `sk-ant-...`
5. Click **Add secret**

### Viewing CI Results

1. Go to repository in Forgejo
2. Click **Actions** tab
3. Select a workflow run to see:
   - Job status (✓ passed, ✗ failed)
   - Detailed logs
   - Test results
   - Build artifacts

### Managing Forgejo

```bash
# View logs
docker compose -f docker-compose.ci.yml logs -f forgejo
docker compose -f docker-compose.ci.yml logs -f forgejo-runner

# Stop CI infrastructure
docker compose -f docker-compose.ci.yml down

# Backup Forgejo data
docker exec forgejo forgejo dump -c /data/gitea/conf/app.ini
docker cp forgejo:/data/gitea-dump-*.zip ./backups/

# Update Forgejo
docker compose -f docker-compose.ci.yml pull
docker compose -f docker-compose.ci.yml up -d
```

### Customizing the CI Workflow

Edit `.forgejo/workflows/ci.yml` to add more steps:

```yaml
# Add code quality checks
- name: Lint with ruff
  run: |
    cd services/rag_server
    uv run ruff check .

# Add deployment
deploy:
  name: Deploy to Production
  runs-on: ubuntu-latest
  needs: [test, docker-build]
  if: github.ref == 'refs/heads/main'
  steps:
    - name: Deploy
      run: |
        # Your deployment commands
```

**Documentation:**
- **[Complete Forgejo Setup Guide](docs/FORGEJO_CI_SETUP.md)** - Detailed setup, troubleshooting, advanced config
- **[Forgejo Actions Docs](https://forgejo.org/docs/latest/user/actions/)** - Official documentation
- **[GitHub Actions Reference](https://docs.github.com/en/actions)** - Syntax reference (mostly compatible)

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

#### POST /documents/check-duplicates
Check if documents with given file hashes already exist in the system to prevent duplicate uploads.

**Request:**
```json
{
  "files": [
    {
      "filename": "document.pdf",
      "size": 102400,
      "hash": "a9dce56a5f43e8859e03ae59d37704b03e97766a141c5812897d0cc587226325"
    }
  ]
}
```

**Response:**
```json
{
  "results": {
    "document.pdf": {
      "filename": "document.pdf",
      "exists": true,
      "document_id": "doc-123",
      "existing_filename": "document.pdf",
      "reason": "Duplicate of 'document.pdf' (already uploaded)"
    }
  }
}
```

**Note:** Hash is computed using SHA-256 of file content, matching LlamaIndex's document hashing approach.

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

#### GET /config
Get configuration settings for the RAG system.

**Response:**
```json
{
  "max_upload_size_mb": 80
}
```

#### GET /models/info
Get basic model configuration (legacy endpoint).

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

### Metrics & Observability Endpoints

These endpoints provide comprehensive visibility into RAG system configuration, models, and evaluation results for monitoring and optimization.

#### GET /metrics/system
Complete system overview combining models, retrieval config, evaluation metrics, and health status.

**Response:**
```json
{
  "system_name": "RAG-Docling",
  "version": "1.0.0",
  "timestamp": "2025-12-09T10:30:00Z",
  "models": { /* ModelsConfig */ },
  "retrieval": { /* RetrievalConfig */ },
  "evaluation_metrics": [ /* MetricDefinition[] */ ],
  "latest_evaluation": { /* EvaluationRun or null */ },
  "document_count": 15,
  "chunk_count": 234,
  "health_status": "healthy",
  "component_status": {
    "chromadb": "healthy",
    "redis": "healthy",
    "ollama": "healthy"
  }
}
```

#### GET /metrics/models
Detailed information about all models with sizes and references.

**Response:**
```json
{
  "llm": {
    "name": "gemma3:4b",
    "provider": "Ollama",
    "model_type": "llm",
    "is_local": true,
    "size": {
      "parameters": "4B",
      "disk_size_mb": 2400,
      "context_window": 8192
    },
    "reference_url": "https://ollama.com/library/gemma3",
    "description": "Google Gemma 3 4B - Lightweight, efficient LLM",
    "status": "loaded"
  },
  "embedding": {
    "name": "nomic-embed-text:latest",
    "provider": "Ollama",
    "model_type": "embedding",
    "is_local": true,
    "size": {
      "parameters": "137M",
      "context_window": 8192
    },
    "reference_url": "https://ollama.com/library/nomic-embed-text",
    "status": "available"
  },
  "reranker": {
    "name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "provider": "HuggingFace",
    "model_type": "reranker",
    "is_local": true,
    "size": {
      "parameters": "22M",
      "disk_size_mb": 80
    },
    "reference_url": "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2",
    "status": "available"
  },
  "eval": {
    "name": "claude-sonnet-4-20250514",
    "provider": "Anthropic",
    "model_type": "eval",
    "is_local": false,
    "size": {
      "context_window": 200000
    },
    "reference_url": "https://docs.anthropic.com/en/docs/about-claude/models",
    "status": "available"
  }
}
```

#### GET /metrics/retrieval
Retrieval pipeline configuration with research references.

**Response:**
```json
{
  "retrieval_top_k": 10,
  "final_top_n": 5,
  "pipeline_description": "Query -> Hybrid Retrieval (BM25 + Vector + RRF) -> Reranking -> Top-N Selection -> LLM",
  "hybrid_search": {
    "enabled": true,
    "fusion_method": "reciprocal_rank_fusion",
    "rrf_k": 60,
    "research_reference": "https://www.pinecone.io/learn/hybrid-search-intro/",
    "improvement_claim": "48% improvement in retrieval quality (Pinecone benchmark)",
    "bm25": {
      "enabled": true,
      "description": "Sparse text matching using BM25 algorithm",
      "strengths": ["Exact keyword matching", "IDs and abbreviations", "Names and specific terms"]
    },
    "vector": {
      "enabled": true,
      "chunk_size": 500,
      "chunk_overlap": 50,
      "vector_store": "ChromaDB",
      "collection_name": "documents"
    }
  },
  "contextual_retrieval": {
    "enabled": false,
    "description": "LLM generates 1-2 sentence context per chunk before embedding",
    "research_reference": "https://www.anthropic.com/news/contextual-retrieval",
    "improvement_claim": "49% reduction in retrieval failures; 67% with hybrid search + reranking",
    "performance_impact": "~85% slower preprocessing (LLM call per chunk)"
  },
  "reranker": {
    "enabled": true,
    "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "top_n": 5,
    "description": "Cross-encoder model that re-scores retrieved chunks for relevance",
    "reference_url": "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2"
  }
}
```

#### GET /metrics/evaluation/definitions
Definitions for all evaluation metrics.

**Response:**
```json
[
  {
    "name": "contextual_precision",
    "category": "retrieval",
    "description": "Measures whether retrieved chunks are relevant to the query",
    "threshold": 0.7,
    "interpretation": "Score 0-1. Above 0.7 is good. Measures: Are the retrieved chunks actually useful?",
    "reference_url": "https://docs.confident-ai.com/docs/metrics-contextual-precision"
  },
  {
    "name": "contextual_recall",
    "category": "retrieval",
    "description": "Measures whether all relevant information was retrieved",
    "threshold": 0.7,
    "interpretation": "Score 0-1. Above 0.7 is good. Measures: Did we retrieve all the information needed?",
    "reference_url": "https://docs.confident-ai.com/docs/metrics-contextual-recall"
  },
  {
    "name": "faithfulness",
    "category": "generation",
    "description": "Measures whether the answer is grounded in the retrieved context",
    "threshold": 0.7,
    "interpretation": "Score 0-1. Above 0.7 is good. Measures: Is the answer supported by the context?",
    "reference_url": "https://docs.confident-ai.com/docs/metrics-faithfulness"
  },
  {
    "name": "answer_relevancy",
    "category": "generation",
    "description": "Measures whether the generated answer addresses the user's question",
    "threshold": 0.7,
    "interpretation": "Score 0-1. Above 0.7 is good. Measures: Does the answer address the question?",
    "reference_url": "https://docs.confident-ai.com/docs/metrics-answer-relevancy"
  },
  {
    "name": "hallucination",
    "category": "safety",
    "description": "Measures the proportion of hallucinated (unsupported) information",
    "threshold": 0.5,
    "interpretation": "Score 0-1. Below 0.5 is good (lower = less hallucination)",
    "reference_url": "https://docs.confident-ai.com/docs/metrics-hallucination"
  }
]
```

#### GET /metrics/evaluation/history
Historical evaluation runs (supports `?limit=N` parameter).

**Response:**
```json
{
  "runs": [
    {
      "run_id": "a1b2c3d4",
      "timestamp": "2025-12-09T10:00:00Z",
      "framework": "DeepEval",
      "eval_model": "claude-sonnet-4-20250514",
      "total_tests": 10,
      "passed_tests": 8,
      "pass_rate": 80.0,
      "metric_averages": {
        "contextual_precision": 0.85,
        "contextual_recall": 0.78,
        "faithfulness": 0.92,
        "answer_relevancy": 0.88,
        "hallucination": 0.12
      },
      "metric_pass_rates": {
        "contextual_precision": 90.0,
        "contextual_recall": 70.0,
        "faithfulness": 100.0,
        "answer_relevancy": 80.0,
        "hallucination": 80.0
      },
      "retrieval_config": {
        "hybrid_search_enabled": true,
        "contextual_retrieval_enabled": false,
        "reranker_enabled": true,
        "retrieval_top_k": 10
      }
    }
  ],
  "comparison_metrics": [
    "contextual_precision", "contextual_recall", "faithfulness",
    "answer_relevancy", "hallucination"
  ]
}
```

#### GET /metrics/evaluation/summary
Evaluation summary with trends across runs.

**Response:**
```json
{
  "latest_run": { /* EvaluationRun */ },
  "total_runs": 5,
  "metric_trends": [
    {
      "metric_name": "contextual_precision",
      "values": [0.75, 0.78, 0.82, 0.85],
      "timestamps": ["2025-12-01T...", "2025-12-05T...", "2025-12-07T...", "2025-12-09T..."],
      "trend_direction": "improving",
      "latest_value": 0.85,
      "average_value": 0.80
    }
  ],
  "best_run": { /* EvaluationRun with highest composite score */ }
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
2. **Deduplication Check**: Client computes SHA-256 hash, queries backend to skip duplicates
3. **Async Processing**: Celery worker processes each file
4. **Docling Parsing**: DoclingReader extracts text, tables, structure
5. **Contextual Enhancement**: LLM adds document context to each chunk
6. **Structural Chunking**: DoclingNodeParser creates nodes preserving hierarchy
7. **Embedding**: Each chunk embedded with context (nomic-embed-text)
8. **Storage**: Nodes stored in ChromaDB with metadata (including file_hash)
9. **BM25 Refresh**: BM25 index updated with new nodes

### Document Deduplication

Prevents re-uploading identical documents by comparing SHA-256 file hashes before processing:

**How It Works:**
1. **Client-Side Hashing**: Browser computes SHA-256 hash of each file using Web Crypto API (zero server upload for duplicates)
2. **Backend Verification**: `/documents/check-duplicates` endpoint queries ChromaDB metadata for matching `file_hash` values
3. **Smart Filtering**: Duplicate files marked as "skipped" in UI with reason tooltip, only new files uploaded to server
4. **Metadata Storage**: Each document's `file_hash` stored in ChromaDB metadata during processing for future deduplication checks

**Benefits:**
- Saves bandwidth (duplicates never leave browser)
- Prevents redundant processing (no Celery tasks for duplicates)
- User-friendly feedback (clear "Already uploaded" messages in UI)
- Hash persistence across sessions (survives server restarts)

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

## Evaluation & Testing

### Evaluation Framework: DeepEval

**Migrated from RAGAS to DeepEval** (2025-12-07) for better CI/CD integration and self-explaining metrics.

**Key Features:**
- **5 RAG Metrics**: Contextual Precision, Contextual Recall, Faithfulness, Answer Relevancy, Hallucination
- **LLM-as-Judge**: Uses Anthropic Claude Sonnet 4 for evaluation
- **Self-Explaining**: Metrics include reasoning for scores
- **Pytest Integration**: Native assert-based testing
- **CLI Tools**: Unified CLI for evaluation, stats, and Q&A generation

#### Quick Start

```bash
# Install evaluation dependencies
cd services/rag_server
uv sync --group eval

# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run pytest evaluation tests (recommended)
mise run test:eval

# Or use the CLI directly for more control
.venv/bin/python -m evaluation.cli eval --samples 5

# Show dataset statistics
.venv/bin/python -m evaluation.cli stats
```

#### Available Commands

```bash
# Evaluation
.venv/bin/python -m evaluation.cli eval              # Full evaluation
.venv/bin/python -m evaluation.cli eval --samples 5   # Quick test
.venv/bin/python -m evaluation.cli eval --no-reason   # Faster (skip explanations)

# Dataset Management
.venv/bin/python -m evaluation.cli stats              # Show statistics

# Q&A Generation
.venv/bin/python -m evaluation.cli generate doc.txt -n 10 -o generated.json
.venv/bin/python -m evaluation.cli generate docs/ --merge  # Expand dataset
```

#### Metrics Explained

- **Contextual Precision**: Are retrieved chunks ranked correctly?
- **Contextual Recall**: Did we retrieve all necessary information?
- **Faithfulness**: Is the answer grounded in the retrieved context?
- **Answer Relevancy**: Does the answer directly address the question?
- **Hallucination**: Does the answer contain information not in the context?

**Documentation:**
- [DeepEval Implementation Summary](docs/DEEPEVAL_IMPLEMENTATION_SUMMARY.md)
- [Quick Start Guide](services/rag_server/evaluation/README.md)

### Unit & Integration Tests

**Test Coverage:**
- **32 Unit Tests**: Document processing, embeddings, LLM integration, ChromaDB, API endpoints (mocked)
- **25 Integration Tests**: Full pipeline with real services (docker required)
- **27 Evaluation Tests**: DeepEval metrics, dataset loading, live RAG evaluation

#### Test Organization

```
tests/
├── conftest.py                          # Shared fixtures, env setup, skip logic
├── test_*.py                            # Unit tests (mocked dependencies)
├── evaluation/                          # Evaluation framework tests
│   ├── test_dataset_loader.py
│   ├── test_data_models.py
│   ├── test_retrieval_eval.py
│   └── test_reranking_eval.py
└── integration/                         # Integration tests (real services)
    ├── conftest.py                      # Service checks, fixtures
    ├── test_document_pipeline.py        # PDF/text processing → ChromaDB
    ├── test_hybrid_search.py            # BM25 + Vector + RRF
    ├── test_async_upload.py             # Celery task completion
    └── test_error_recovery.py           # Graceful degradation
```

#### Running Tests

This project uses [mise](https://mise.jdx.dev/) for task management. See `.mise.toml` for all tasks.

```bash
# Install dev dependencies
mise run dev

# Unit tests only (fast, no services required)
mise run test

# Integration tests (requires docker compose up -d)
mise run test:integration

# List all tasks
mise tasks

# Advanced: Integration + slow tests (large file processing)
cd services/rag_server
.venv/bin/pytest tests/integration -v --run-integration --run-slow

# Advanced: Specific integration test file
.venv/bin/pytest tests/integration/test_document_pipeline.py -v --run-integration

# Advanced: Run with coverage
.venv/bin/pytest --cov=. --cov-report=html --ignore=tests/integration
```

#### Integration Test Categories

| File | Tests | What It Validates |
|------|-------|-------------------|
| `test_document_pipeline.py` | 6 | PDF parsing, text files, metadata, large docs, unsupported formats |
| `test_hybrid_search.py` | 5 | BM25 refresh after upload/delete, RRF fusion, keyword matching |
| `test_async_upload.py` | 5 | Celery task completion, progress tracking, concurrent uploads |
| `test_error_recovery.py` | 9 | Corrupted files, LLM timeout, service failures, graceful degradation |

#### Key Integration Tests

1. **`test_pdf_full_pipeline`**: Upload real PDF → Docling parses → ChromaDB stores → queryable
2. **`test_bm25_refresh_after_upload`**: New document → BM25 refreshed → keyword search finds it
3. **`test_celery_task_completes`**: API upload → Celery processes → status shows completed
4. **`test_corrupted_pdf_handling`**: Invalid PDF → fails cleanly with error, not crash

#### Test Markers

```python
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "integration: Tests requiring docker services",
    "slow: Tests taking > 30s",
    "eval: RAG evaluation tests (require --run-eval and ANTHROPIC_API_KEY)",
]
```

### Golden Dataset

Current dataset: **10 Q&A pairs** from Paul Graham essays (greatwork.html, talk.html, conformism.html)

Breakdown:
- 8 Factual questions (80%)
- 2 Reasoning questions (20%)

**Expanding Dataset:**

```bash
# Generate synthetic Q&A pairs
.venv/bin/python -m evaluation.generate_qa document.txt -n 10 -o generated.json

# Merge with golden dataset
.venv/bin/python -m evaluation.cli generate documents/ --merge
```

Target: **100+ Q&A pairs** for comprehensive evaluation

## RAG Observability

### Why Observability Matters

RAG systems require comprehensive observability to:
- **Diagnose retrieval failures**: Identify whether problems stem from indexing, retrieval, or generation
- **Track quality over time**: Monitor metric trends as you add documents or change configurations
- **Compare configurations**: Understand the impact of enabling/disabling features like hybrid search or reranking
- **Debug production issues**: Correlate user complaints with specific component failures

### Key Metrics to Track

Based on industry best practices (2024-2025), RAG observability should cover:

#### Retrieval Metrics
| Metric | Description | Target |
|--------|-------------|--------|
| **Contextual Precision** | Are the top-k retrieved chunks actually relevant? | > 0.7 |
| **Contextual Recall** | Did we retrieve all necessary information? | > 0.7 |
| **Mean Reciprocal Rank (MRR)** | Is the correct document ranked early? | > 0.5 |
| **Hit Rate** | Did at least one relevant chunk appear in top-k? | > 0.9 |

#### Generation Metrics
| Metric | Description | Target |
|--------|-------------|--------|
| **Faithfulness** | Is the answer grounded in retrieved context? | > 0.7 |
| **Answer Relevancy** | Does the answer address the question asked? | > 0.7 |
| **Hallucination Rate** | What % of answer is unsupported by context? | < 0.5 |

#### Operational Metrics
| Metric | Description |
|--------|-------------|
| **Latency (P50, P95)** | Query response time percentiles |
| **Retrieval Count** | Documents retrieved per query |
| **Embedding Similarity** | Score distribution of retrieved chunks |
| **Cost per Query** | LLM tokens used for generation |

### Observability Best Practices

1. **Component-Level Instrumentation**: Monitor each pipeline stage independently (retriever, reranker, generator)

2. **Unified Dashboards**: Put retrieval precision, generation quality, and latency on the same view to see trade-offs

3. **Trend Detection**: Track metrics over time to catch quality regressions early. Our `/metrics/evaluation/summary` endpoint provides trend analysis (improving/declining/stable)

4. **Configuration Snapshots**: Record which settings were active during each evaluation run to correlate changes with improvements

5. **Automated Quality Checks**: Run periodic evaluations against a golden dataset to detect drift

### Using the Metrics API

```bash
# Get complete system overview
curl http://localhost:8001/metrics/system | jq

# Check model configurations
curl http://localhost:8001/metrics/models | jq

# View retrieval settings with research references
curl http://localhost:8001/metrics/retrieval | jq

# Get evaluation metric definitions
curl http://localhost:8001/metrics/evaluation/definitions | jq

# View evaluation history (last 10 runs)
curl http://localhost:8001/metrics/evaluation/history?limit=10 | jq

# Get summary with trends
curl http://localhost:8001/metrics/evaluation/summary | jq
```

### Saving Evaluation Results

Use the `--save` flag when running evaluations to store results for the metrics API:

```bash
# Run evaluation and save results
.venv/bin/python -m evaluation.cli eval --samples 10 --save

# Results stored in eval_data/results/
# View via GET /metrics/evaluation/history
```

### Research References

- [Evidently AI - RAG Evaluation Guide](https://www.evidentlyai.com/llm-guide/rag-evaluation) - Comprehensive overview of RAG metrics
- [Braintrust - Best RAG Evaluation Tools 2025](https://www.braintrust.dev/articles/best-rag-evaluation-tools) - Tool comparison
- [Patronus AI - RAG Evaluation Best Practices](https://www.patronus.ai/llm-testing/rag-evaluation-metrics) - Enterprise patterns
- [DEV Community - Production RAG in 2024](https://dev.to/hamidomarov/building-production-rag-in-2024-lessons-from-50-deployments-5fh9) - Lessons from 50+ deployments
- [Medium - RAG Observability Strategies](https://medium.com/@support_81201/monitoring-retrieval-augmented-generation-rag-applications-challenges-and-observability-42c042562a43) - Monitoring challenges

## Roadmap

### Completed

**Phase 1** (2025-10-13):
- [x] Redis-backed chat memory
- [x] ChromaDB backup/restore automation
- [x] Reranker optimization (top-n selection)
- [x] Startup persistence verification

**Phase 2** (2025-10-14):
- [x] Hybrid search (BM25 + Vector + RRF) - 48% improvement
- [x] Contextual retrieval (Anthropic method) - 49% fewer failures
- [x] Auto-refresh BM25 after uploads/deletes

**Evaluation Migration** (2025-12-07):
- [x] DeepEval framework integration
- [x] Anthropic Claude as LLM judge
- [x] Pytest integration with custom markers
- [x] Unified CLI for evaluation tasks
- [x] Enhanced dataset loader
- [x] Synthetic Q&A generation

**CI/CD Implementation** (2025-12-07):
- [x] Forgejo self-hosted Git + CI/CD setup
- [x] GitHub Actions-compatible workflows
- [x] Automated core tests on push/PR
- [x] Optional evaluation tests (manual trigger or `[eval]` flag)
- [x] Docker build verification
- [x] Runner configuration and documentation

**Metrics & Observability API** (2025-12-09):
- [x] Comprehensive metrics API endpoints
- [x] Model info with sizes, parameters, and reference URLs
- [x] Retrieval configuration with research references
- [x] Evaluation metrics definitions and history
- [x] Trend analysis (improving/declining/stable)
- [x] Component health monitoring
- [x] CLI integration (`--save` flag for eval results)

### Planned (Phase 3+)

- [ ] Webapp integration for metrics visualization
- [ ] Expand golden dataset to 100+ Q&A pairs
- [ ] Parent document retrieval (sentence window)
- [ ] Query fusion (multi-query generation)
- [ ] Multi-user support with authentication
- [ ] Additional file formats (CSV, JSON)

See [RAG Accuracy Improvement Plan](docs/RAG_ACCURACY_IMPROVEMENT_PLAN_2025.md) for details.
