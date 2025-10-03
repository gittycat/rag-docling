# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local RAG (Retrieval Augmented Generation) system with two FastAPI services using Docling + LangChain for document processing, ChromaDB for vector storage, and Ollama for LLM inference.

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
2. Docling parses (PDF/DOCX/PPTX/XLSX/HTML) → extracts text, tables, layout
3. HybridChunker splits with token-aware semantic boundaries
4. LangChain OllamaEmbeddings generates vectors (nomic-embed-text, 768-dim)
5. Stored in ChromaDB via LangChain Chroma wrapper
6. Query → retrieval → LLM (llama3.2) generates answer

**Key Implementation Pattern:**
- Documents stored as chunks with `document_id` metadata
- Each chunk has ID: `{doc_id}-chunk-{i}`
- Deletion removes all chunks with matching `document_id`

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

### Docling + LangChain Integration

**Document Processing** (`services/rag_server/core_logic/document_processor.py`):
- Uses `DoclingLoader` from `langchain-docling`
- `ExportType.MARKDOWN` for full text extraction
- `ExportType.DOC_CHUNKS` with HybridChunker for automatic chunking
- HybridChunker tokenizer: `sentence-transformers/all-MiniLM-L6-v2` (compatible with nomic-embed-text)

**Embeddings** (`services/rag_server/core_logic/embeddings.py`):
- LangChain `OllamaEmbeddings` wrapper (not ChromaDB's native function)
- Model: `nomic-embed-text`
- URL from `OLLAMA_URL` env var

**Vector Store** (`services/rag_server/core_logic/chroma_manager.py`):
- Uses `langchain-chroma.Chroma` wrapper
- Returns vectorstore instance (not raw ChromaDB collection)
- `add_documents()` uses `add_texts()` method
- `query_documents()` uses `similarity_search_with_score()` then converts to ChromaDB format for backward compatibility
- Direct ChromaDB access via `._collection` for deletion/listing

### Prompt Engineering Strategies

**LLM Prompt Construction** (`services/rag_server/core_logic/llm_handler.py`):
- Four configurable strategies via `PROMPT_STRATEGY` env var
- All use XML structure (optimal for Llama 3.2)
- Designed to reduce hallucination and improve context grounding

**Available Strategies:**

1. **fast** - Minimal instructions for quick responses
   - Use case: Simple documents, speed-critical applications
   - Features: Basic context grounding, minimal overhead
   - Trade-off: Less rigorous hallucination prevention

2. **balanced** (default) - Good accuracy/speed balance
   - Use case: General purpose RAG applications
   - Features: Clear grounding rules, explicit "I don't know" fallback, numbered context IDs
   - Trade-off: Recommended starting point

3. **precise** - Strong anti-hallucination with step-by-step reasoning
   - Use case: Applications requiring high accuracy
   - Features: Explicit 5-step instructions, citation requirements, defensive "err on side of don't know"
   - Trade-off: Slightly slower, more verbose responses

4. **comprehensive** - Maximum accuracy with chain-of-thought
   - Use case: Complex documents, critical accuracy requirements
   - Features: Multi-step reasoning process, self-critique, mandatory citations
   - Trade-off: Slowest, generates longest responses

**Configuration:**
```yaml
# In docker-compose.yml
environment:
  - PROMPT_STRATEGY=balanced  # Change to: fast, balanced, precise, comprehensive
```

**Best Practices:**
- Start with `balanced` and adjust based on observed hallucination rates
- Use `fast` for high-volume, low-stakes queries
- Use `comprehensive` for technical documentation or legal documents
- Monitor response quality and adjust strategy accordingly

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
  - `ollama pull llama3.2`
  - `ollama pull nomic-embed-text`

**Environment Variables:**
- Web App: `RAG_SERVER_URL=http://rag-server:8001`
- RAG Server: `CHROMADB_URL=http://chromadb:8000`, `OLLAMA_URL=http://host.docker.internal:11434`, `LLM_MODEL=llama3.2`

### Testing Patterns

**Mocking Strategy:**
- DoclingLoader mocked to return `MagicMock` documents with `page_content`
- LangChain components mocked via `@patch` decorators
- Chroma vectorstore mocked with `._collection` attribute for underlying ChromaDB access

**Test Structure:**
- `test_embeddings.py`: LangChain OllamaEmbeddings initialization
- `test_document_processing.py`: Docling parsing + HybridChunker
- `test_chroma_collection.py`: LangChain Chroma wrapper operations
- `test_llm_integration.py`: Ollama LLM responses
- `test_document_api.py`, `test_upload_api.py`: FastAPI endpoints

## API Endpoints

**RAG Server** (port 8001):
- `POST /query`: RAG query with context retrieval + LLM generation
- `GET /documents`: List all indexed documents (grouped by document_id)
- `POST /upload`: Upload documents (supports multiple files)
- `DELETE /documents/{document_id}`: Delete document and all chunks

**Supported Formats:**
`.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`, `.adoc`

## Key Files

- `services/rag_server/core_logic/rag_pipeline.py`: Main RAG query flow
- `services/rag_server/core_logic/document_processor.py`: Docling + HybridChunker
- `services/rag_server/core_logic/chroma_manager.py`: LangChain Chroma wrapper
- `services/rag_server/core_logic/embeddings.py`: LangChain OllamaEmbeddings
- `services/rag_server/main.py`: FastAPI endpoints
- `docker-compose.yml`: Service orchestration with network isolation

## Common Issues

**Ollama not accessible:** Check `host.docker.internal` resolves correctly. Verify with:
```bash
docker compose exec rag-server curl http://host.docker.internal:11434/api/tags
```

**ChromaDB connection fails:** ChromaDB on private network only. RAG server must be on same network.

**Docker build fails with certifi error:** Ensure `--index-strategy unsafe-best-match` is in Dockerfile RUN command.

**Tests fail with ModuleNotFoundError:** Use `.venv/bin/pytest` directly instead of `uv run pytest` to avoid path issues.
