# RAG System - Local Document Search with AI

A privacy-first, local RAG (Retrieval Augmented Generation) system that enables natural language search across your documents using AI.

## Features

- **Natural Language Search**: Ask questions in plain English and get AI-powered answers
- **Advanced Document Processing**: Powered by Docling with superior PDF/DOCX parsing, table extraction, and layout understanding
- **Multi-Format Support**: Process txt, md, pdf, docx, pptx, xlsx, html, and more
- **Intelligent Chunking**: Structural chunking that preserves document hierarchy (headings, sections, tables)
- **Two-Stage Retrieval**: Vector search (top-10) + cross-encoder reranking for better precision
- **Conversational Memory**: Redis-backed chat history that persists across restarts
- **Data Protection**: Automated ChromaDB backups with restore capability
- **Local Deployment**: All data stays on your machine
- **Modern Web Interface**: Clean, responsive UI with Tailwind CSS and dark mode support
- **Document Management**: Admin interface for viewing and managing indexed documents
- **RAG Evaluation**: RAGAS framework integration for measuring retrieval and generation quality
- **Test-Driven Development**: Comprehensive test coverage (60 tests: 33 core + 27 evaluation)

## Technology Stack

- **Frontend**: FastAPI + Jinja2 + Tailwind CSS
- **RAG Server**: Python + FastAPI
- **Vector Database**: ChromaDB with LlamaIndex integration
- **LLM**: Ollama (gemma3:4b for generation, gemma3:4b for evaluation)
- **Embeddings**: LlamaIndex OllamaEmbedding with qwen3-embedding:8b (768 dimensions)
- **Document Processing**: Docling + LlamaIndex DoclingReader/DoclingNodeParser
- **Chunking**: Docling structural chunking (preserves document hierarchy)
- **Reranking**: SentenceTransformer cross-encoder (ms-marco-MiniLM-L-6-v2)
- **Orchestration**: Docker Compose
- **Package Management**: uv
- **Task Queue**: Celery + Redis (async document processing, chat history persistence, progress tracking)

## Architecture

```
┌─────────────────┐
│   Web Browser   │
└────────┬────────┘
         │
┌────────▼────────┐
│  FastAPI Web    │  (Port 8000, Public Network)
│     App         │
└────────┬────────┘
         │
┌────────▼────────┐
│   RAG Server    │  (Port 8001, Private Network)
│                 │
│  ┌──────────┐  │
│  │ Docling  │  │  Advanced document parsing
│  │+LangChain│  │  & HybridChunker
│  └──────────┘  │
└────────┬────────┘
         │
    ┌────┴────┬────────┐
    │         │        │
┌───▼───┐ ┌──▼──┐  ┌──▼──────┐
│ChromaDB│ │Ollama│ │LangChain│
│ (8000) │ │(11434)│ │ Chroma  │
└────────┘ └──────┘ └─────────┘
```

## Prerequisites

1. **Docker & Docker Compose**
   - Docker Desktop or Docker Engine
   - Docker Compose v2+

2. **Ollama** (running on host)
   ```bash
   # Install Ollama
   curl https://ollama.ai/install.sh | sh

   # Pull required models
   ollama pull gemma3:4b           # LLM for generation
   ollama pull qwen3-embedding:8b  # Embeddings (768-dim)
   ```

3. **Python 3.12+** (for local development/testing)
   ```bash
   # Install uv package manager
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

## Quick Start

### 1. Clone and Setup

```bash
cd /path/to/rag-bin2
```

### 2. Configure Secrets (Optional)

```bash
# Create secrets directory
mkdir -p secrets

# Add configuration if needed
echo "your-config-value" > secrets/config_value
```

### 3. Start Services

```bash
docker-compose up -d
```

This will start:
- Web App on http://localhost:8000
- RAG Server on http://localhost:8001 (internal)
- ChromaDB on http://localhost:8002 (internal)

### 4. Access the Application

Open http://localhost:8000 in your browser.

## Usage

### Adding Documents

Currently, documents must be added programmatically via the RAG server API:

```python
import requests

# Add a document
response = requests.post(
    "http://localhost:8001/documents",
    json={
        "file_path": "/path/to/document.pdf",
        "file_name": "document.pdf",
        "file_type": "pdf"
    }
)
```

Future versions will include file upload via the web interface.

### Searching Documents

1. Navigate to http://localhost:8000
2. Enter your question in natural language
3. View AI-generated answer with source citations

### Managing Documents

1. Go to http://localhost:8000/admin
2. View all indexed documents
3. Delete documents as needed

## Development

### Local Testing

#### Web App Tests

```bash
cd services/fastapi_web_app
uv sync
uv run pytest -v
```

#### RAG Server Tests

```bash
cd services/rag_server
uv sync
uv run pytest -v
```

### Project Structure

```
rag-bin2/
├── docker-compose.yml          # Service orchestration
├── secrets/                    # Configuration secrets
├── services/
│   ├── fastapi_web_app/       # Web interface
│   │   ├── main.py            # FastAPI app
│   │   ├── templates/         # Jinja2 templates
│   │   ├── static/            # CSS/JS assets
│   │   ├── tests/             # Test suite (21 tests)
│   │   └── pyproject.toml     # Dependencies
│   └── rag_server/            # RAG backend
│       ├── main.py            # FastAPI app
│       ├── core_logic/        # RAG components
│       │   ├── embeddings.py       # LangChain OllamaEmbeddings
│       │   ├── document_processor.py  # Docling + HybridChunker
│       │   ├── chroma_manager.py   # LangChain Chroma vectorstore
│       │   ├── llm_handler.py      # LLM integration
│       │   └── rag_pipeline.py     # End-to-end RAG pipeline
│       ├── tests/             # Test suite (33 tests)
│       └── pyproject.toml     # Dependencies
└── README.md
```

## API Documentation

### RAG Server Endpoints

#### POST /query
Search documents and get AI-generated answer.

**Request:**
```json
{
  "query": "What is the main topic of the documents?"
}
```

**Response:**
```json
{
  "answer": "Based on the documents...",
  "sources": [
    {
      "document_name": "file.pdf",
      "file_type": "pdf",
      "relevance_score": 0.85
    }
  ]
}
```

#### GET /documents
List all indexed documents.

**Response:**
```json
{
  "documents": [
    {
      "id": "doc-123",
      "file_name": "document.pdf",
      "file_type": "pdf",
      "path": "/docs/document.pdf"
    }
  ]
}
```

#### DELETE /documents/{document_id}
Delete a document from the index.

**Response:**
```json
{
  "status": "success",
  "message": "Document deleted successfully"
}
```

## Configuration

### Environment Variables

**Web App:**
- `RAG_SERVER_URL`: RAG server endpoint (default: `http://rag-server:8001`)

**RAG Server:**
- `CHROMADB_URL`: ChromaDB endpoint (default: `http://chromadb:8000`)
- `OLLAMA_URL`: Ollama endpoint (default: `http://host.docker.internal:11434`)
- `LLM_MODEL`: LLM model to use (default: `llama3.2`)

### Docker Compose Networks

- **public**: Web app (accessible from host)
- **private**: RAG server, ChromaDB (internal only)

## Known Issues & Fixes

### DoclingReader/DoclingNodeParser Integration (FIXED)

**Issue**: Document upload fails with Pydantic validation error if DoclingReader export format is not specified.

**Root Cause**: DoclingReader defaults to MARKDOWN export, but DoclingNodeParser requires JSON format.

**Fix**: Always use JSON export in `document_processor.py`:
```python
reader = DoclingReader(export_type=DoclingReader.ExportType.JSON)
```

**Reference**: See `docs/troubleshooting/2025-10-09-retrieval-fix.md` for complete diagnostic report.

### ChromaDB Metadata Compatibility (FIXED)

**Issue**: ChromaDB rejects complex metadata types (lists, dicts) from Docling.

**Fix**: Filter metadata to flat types (str, int, float, bool, None) using `clean_metadata_for_chroma()` function before insertion.

### Answer Fragmentation with Docling Chunking

**Symptom**: Incomplete answers even when relevant information exists in documents.

**Cause**: Docling creates granular structural chunks (9-27K char range) that can split semantic units across non-contiguous nodes.

**Mitigation**:
1. Enable reranker: `ENABLE_RERANKER=true` (already enabled)
2. Use higher top-k: `RETRIEVAL_TOP_K=10` (already configured)
3. Reranker uses top-n selection to return most relevant 5-10 nodes

**Long-term Solution**: Consider hybrid search (BM25 + Vector) and contextual retrieval (see Phase 2 of RAG Accuracy Improvement Plan).

## Troubleshooting

### Ollama Connection Issues

```bash
# Verify Ollama is running
curl http://localhost:11434/api/tags

# Check models are available
ollama list
```

### ChromaDB Connection Issues

```bash
# Check ChromaDB logs
docker-compose logs chromadb

# Restart ChromaDB
docker-compose restart chromadb
```

### View Service Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f rag-server
docker-compose logs -f fastapi_web_app
```

### Reset Database

```bash
# Stop services
docker-compose down

# Remove ChromaDB volume
docker volume rm rag-bin2_chroma_data

# Restart
docker-compose up -d
```

## Backup & Restore

### ChromaDB Backup

Automated backup scripts are provided to protect against data loss:

```bash
# Manual backup to default location (./backups/chromadb/)
./scripts/backup_chromadb.sh

# Schedule daily backups at 2 AM (add to crontab)
crontab -e
# Add: 0 2 * * * cd /path/to/rag-docling && ./scripts/backup_chromadb.sh >> /var/log/chromadb_backup.log 2>&1
```

**Features**:
- Timestamped backups (`chromadb_backup_YYYYMMDD_HHMMSS.tar.gz`)
- 30-day retention (automatically removes old backups)
- Document count verification
- Health check after restore

### ChromaDB Restore

```bash
# List available backups
ls -lh ./backups/chromadb/

# Restore from specific backup
./scripts/restore_chromadb.sh ./backups/chromadb/chromadb_backup_20251013_020000.tar.gz
```

**Note**: Restore process stops services, replaces data, and verifies health after restart.

See `scripts/README.md` for complete documentation.

## Testing

The project follows Test-Driven Development (TDD) methodology:

- **60 total tests** (all passing)
  - 21 web app tests (UI, routing, templates)
  - 33 RAG server core tests (Docling processing, embeddings, LlamaIndex integration, LLM, pipeline, API)
  - 27 evaluation tests (RAGAS metrics, dataset loading, report generation)

Run all tests:
```bash
# RAG Server core tests
cd services/rag_server && .venv/bin/pytest -v

# RAG Server evaluation tests
cd services/rag_server && .venv/bin/pytest tests/evaluation/ -v

# Web App tests
cd services/fastapi_web_app && uv run pytest -v
```

## Implementation Details

### Document Processing Pipeline

The RAG server uses **Docling + LlamaIndex** for superior document processing:

1. **DoclingReader** (llama-index-readers-docling): Advanced document parsing with:
   - Superior PDF layout understanding
   - Table structure extraction
   - Reading order detection
   - Support for PPTX, XLSX, HTML, and more
   - **Critical**: Must use `export_type=DoclingReader.ExportType.JSON` for compatibility

2. **DoclingNodeParser** (llama-index-node-parser-docling): Structural chunking that:
   - Preserves document hierarchy (headings, sections, tables)
   - Creates one node per structural element
   - Variable node sizes (9 chars to 27KB) based on document structure
   - Metadata extraction for each node

3. **Two-Stage Retrieval**:
   - **Stage 1**: Vector similarity search (top-10 results, high recall)
   - **Stage 2**: Cross-encoder reranking (ms-marco-MiniLM-L-6-v2, high precision)
   - **Top-n selection**: Returns top 5 nodes by default (or half of retrieval_top_k)
   - **Adaptive context**: Returns most relevant nodes based on reranking scores

4. **LlamaIndex Integration**:
   - ChromaVectorStore with VectorStoreIndex
   - Query engine with custom PromptTemplate (4 strategies)
   - Node postprocessors for reranking and filtering

### Key Features

- **Document Structure Preservation**: Maintains headings, sections, tables as separate nodes
- **Two-Stage Retrieval**: Combines recall of vector search with precision of reranking
- **Conversational Memory**: Redis-backed chat history with automatic expiration (1-hour TTL)
- **Data Protection**: Automated backups, startup persistence verification
- **Dynamic Context Window**: Returns top-ranked nodes based on reranking scores

## Roadmap

### Completed (Phase 1 - 2025-10-13)
- [x] Redis-backed chat memory (conversations persist across restarts)
- [x] ChromaDB backup/restore automation
- [x] Reranker optimization (top-n selection)
- [x] Startup persistence verification
- [x] Dependency updates (ChromaDB 1.1.1, FastAPI 0.118.3, Redis 6.4.0)

See `docs/PHASE1_IMPLEMENTATION_SUMMARY.md` for details.

### Planned (Phase 2+)
- [ ] Hybrid search (BM25 + Vector + RRF) - 48% retrieval improvement
- [ ] Contextual retrieval (Anthropic method) - 49% fewer failures
- [ ] Parent document retrieval (sentence window)
- [ ] File upload via web interface
- [ ] Support for additional file formats (CSV, JSON)
- [ ] Multi-user support with authentication
- [ ] Query history and bookmarking
- [ ] Export search results
- [ ] Performance metrics dashboard

See `docs/RAG_ACCURACY_IMPROVEMENT_PLAN_2025.md` for Phase 2 details.

## License

MIT License

## Version

0.1.0
