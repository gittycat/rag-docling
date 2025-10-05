# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local RAG system with two FastAPI services using Docling + LlamaIndex for document processing, ChromaDB for vector storage, and Ollama for LLM inference.

## Architecture

**Two-Service Design:**
- `fastapi_web_app` (port 8000): User-facing web interface
- `rag-server` (port 8001): Backend RAG processing service

**Network Isolation:**
- `public` network: Web app accessible from host
- `private` network: Internal services (ChromaDB, RAG server communication)
- Ollama runs on host machine at `http://host.docker.internal:11434`

**Document Processing Flow:**
1. Documents uploaded → `rag-server` `/upload` endpoint
2. DoclingReader parses (PDF/DOCX/PPTX/XLSX/HTML) → DoclingNodeParser creates nodes
3. LlamaIndex OllamaEmbedding generates vectors (qwen3-embedding:8b, 768-dim)
4. Stored in ChromaDB via VectorStoreIndex
5. Query → retrieval (top-k=10) → reranking → threshold filtering → LLM (gemma3:4b) generates answer

**Key Implementation Pattern:**
- Documents stored as nodes with `document_id` metadata
- Each node has ID: `{doc_id}-chunk-{i}`
- Deletion removes all nodes with matching `document_id`
- Two-stage retrieval: High-recall embedding search (top-10) → precision reranking (threshold-based)
- Dynamic context: Returns 0-10 nodes based on relevance scores, not fixed top-k
- Uses query_engine with custom PromptTemplate (4 strategies: fast, balanced, precise, comprehensive)

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
```

### Testing

```bash
# RAG Server tests (33 tests)
cd services/rag_server
uv sync
.venv/bin/pytest -v

# Run single test
.venv/bin/pytest tests/test_document_processing.py::test_chunk_document -v

# Web App tests (21 tests)
cd services/fastapi_web_app
uv sync
uv run pytest -v
```

### Local Development

```bash
# Install dependencies for a service
cd services/rag_server
uv sync

# Add new dependency
uv add package-name

# Update dependencies
uv sync --upgrade
```

## Critical Implementation Details

### Docling + LlamaIndex Integration

**Document Processing** (`services/rag_server/core_logic/document_processor.py`):
- `DoclingReader` from `llama-index-readers-docling` loads documents
- `DoclingNodeParser` from `llama-index-node-parser-docling` creates nodes
- Returns LlamaIndex Node objects

**Embeddings** (`services/rag_server/core_logic/embeddings.py`):
- `OllamaEmbedding` from `llama-index-embeddings-ollama`
- Model: `nomic-embed-text` (parameter: `model_name`)
- URL from `OLLAMA_URL` env var

**Vector Store** (`services/rag_server/core_logic/chroma_manager.py`):
- `ChromaVectorStore` wraps ChromaDB collection
- `VectorStoreIndex.from_vector_store()` creates index
- `index.insert_nodes()` adds documents
- `index.as_retriever()` for retrieval operations
- Direct ChromaDB access via `._vector_store._collection` for deletion/listing

**LLM** (`services/rag_server/core_logic/llm_handler.py`):
- `Ollama` from `llama-index-llms-ollama`
- Returns prompt templates (not direct LLM calls)
- 4 strategies: fast, balanced (default), precise, comprehensive

**RAG Pipeline** (`services/rag_server/core_logic/rag_pipeline.py`):
- `PromptTemplate` wraps strategy-specific template string
- `index.as_query_engine()` with `text_qa_template=qa_prompt`
- Two-stage node postprocessing:
  1. `SentenceTransformerRerank`: Cross-encoder reranks top-10 results
  2. `SimilarityPostprocessor`: Filters nodes below threshold (default: 0.65)
- `query_engine.query()` handles retrieval + reranking + generation
- Returns sources from `response.source_nodes` (dynamic 0-10 nodes)

**Reranking Strategy**:
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80MB, HuggingFace)
- Auto-downloads from HuggingFace on first query (NOT from Ollama)
- Cached in `~/.cache/huggingface/` for subsequent queries
- Combined approach: Rerank ALL retrieved nodes, then apply similarity threshold
- Adaptive context window: Only includes nodes above relevance threshold
- Configurable via env vars: `ENABLE_RERANKER`, `RERANKER_MODEL`, `RERANKER_SIMILARITY_THRESHOLD`, `RETRIEVAL_TOP_K`
- Can be disabled by setting `ENABLE_RERANKER=false`

**Settings** (`services/rag_server/core_logic/settings.py`):
- Global `Settings.llm` and `Settings.embed_model`
- Initialized on app startup via `@app.on_event("startup")`

### Docker Build Issues

**PyTorch CPU Index Problem:**
The Dockerfile uses `--index-strategy unsafe-best-match` because:
- PyTorch CPU index has old package versions (e.g., certifi==2022.12.7)
- Docling requires newer versions from PyPI
- uv's default "first match wins" prevents finding newer versions
- Solution: Allow checking all indexes for best version

```dockerfile
RUN uv sync --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match
```

### Environment Setup

**Prerequisites:**
- Docker & Docker Compose v2+
- Ollama running on host with models:
  - `ollama pull gemma3:4b` (LLM)
  - `ollama pull qwen3-embedding:8b` (embeddings)
- Reranker model auto-downloads from HuggingFace (no manual installation needed)

**Environment Variables:**
- Web App: `RAG_SERVER_URL=http://rag-server:8001`
- RAG Server (required): `CHROMADB_URL`, `OLLAMA_URL`, `EMBEDDING_MODEL`, `LLM_MODEL`, `PROMPT_STRATEGY`
- RAG Server (reranker): `ENABLE_RERANKER=true`, `RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`, `RERANKER_SIMILARITY_THRESHOLD=0.65`, `RETRIEVAL_TOP_K=10`

### Testing

**Mocking:**
- `DoclingReader` and `DoclingNodeParser` mocked to return Node objects
- LlamaIndex components mocked via `@patch`
- VectorStoreIndex mocked with `._vector_store._collection` for ChromaDB access

**Test Files:**
- `test_embeddings.py`: OllamaEmbedding with `model_name` parameter
- `test_document_processing.py`: DoclingReader → DoclingNodeParser
- `test_chroma_collection.py`: VectorStoreIndex operations

## API Endpoints

**RAG Server** (port 8001):
- `POST /query`: query_engine.query() with custom PromptTemplate
- `GET /documents`: List all indexed documents (grouped by document_id)
- `POST /upload`: Upload documents (supports multiple files)
- `DELETE /documents/{document_id}`: Delete document and all nodes

**Supported Formats:**
`.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`, `.adoc`

## Key Files

- `services/rag_server/core_logic/rag_pipeline.py`: query_engine with reranking + PromptTemplate
- `services/rag_server/core_logic/document_processor.py`: DoclingReader + DoclingNodeParser
- `services/rag_server/core_logic/chroma_manager.py`: VectorStoreIndex
- `services/rag_server/core_logic/embeddings.py`: OllamaEmbedding
- `services/rag_server/core_logic/llm_handler.py`: Ollama LLM + PromptTemplate strategies
- `services/rag_server/core_logic/settings.py`: Global Settings initialization
- `services/rag_server/core_logic/env_config.py`: Required and optional env var helpers
- `services/rag_server/main.py`: FastAPI endpoints

## Common Issues

**Ollama not accessible:** Check `host.docker.internal` resolves correctly. Verify with:
```bash
docker compose exec rag-server curl http://host.docker.internal:11434/api/tags
```

**ChromaDB connection fails:** ChromaDB on private network only. RAG server must be on same network.

**Docker build fails with certifi error:** Ensure `--index-strategy unsafe-best-match` is in Dockerfile RUN command.

**Tests fail with ModuleNotFoundError:** Use `.venv/bin/pytest` directly instead of `uv run pytest` to avoid path issues.

**Reranker performance:** First query downloads cross-encoder model from HuggingFace (~80MB). Subsequent queries use cached model from `~/.cache/huggingface/`. Adds ~100-300ms latency per query. Disable with `ENABLE_RERANKER=false` if not needed.

**Tuning reranker threshold:** Lower `RERANKER_SIMILARITY_THRESHOLD` (e.g., 0.5) for broader information, raise (e.g., 0.75) for more precise responses. Monitor "I don't know" frequency - too high means threshold is too strict.
