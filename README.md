# RAG System - Local Document Search with AI

A privacy-first, local RAG (Retrieval Augmented Generation) system that enables natural language search across your documents using AI.

## Features

- **Natural Language Search**: Ask questions in plain English and get AI-powered answers
- **Multi-Format Support**: Process txt, md, pdf, and docx files
- **Local Deployment**: All data stays on your machine
- **Modern Web Interface**: Clean, responsive UI with Tailwind CSS
- **Document Management**: Admin interface for viewing and managing indexed documents
- **Test-Driven Development**: Comprehensive test coverage (47 tests)

## Technology Stack

- **Frontend**: FastAPI + Jinja2 + Tailwind CSS
- **RAG Server**: Python + FastAPI
- **Vector Database**: ChromaDB
- **LLM**: Ollama (llama3.2)
- **Embeddings**: nomic-embed-text (768 dimensions)
- **Document Processing**: MarkItDown
- **Orchestration**: Docker Compose
- **Package Management**: uv

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
└────────┬────────┘
         │
    ┌────┴────┬──────────┐
    │         │          │
┌───▼───┐ ┌──▼──┐  ┌───▼────┐
│ChromaDB│ │Ollama│ │MarkIt  │
│ (8000) │ │(11434)│ │ Down   │
└────────┘ └──────┘ └────────┘
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
   ollama pull llama3.2
   ollama pull nomic-embed-text
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
│       │   ├── embeddings.py       # Ollama embeddings
│       │   ├── document_processor.py  # File processing
│       │   ├── chroma_manager.py   # Vector DB
│       │   ├── llm_handler.py      # LLM integration
│       │   └── rag_pipeline.py     # End-to-end pipeline
│       ├── tests/             # Test suite (26 tests)
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

## Testing

The project follows Test-Driven Development (TDD) methodology:

- **47 total tests**
  - 21 web app tests (UI, routing, templates)
  - 26 RAG server tests (embeddings, documents, LLM, pipeline, API)

Run all tests:
```bash
# RAG Server
cd services/rag_server && uv run pytest -v

# Web App
cd services/fastapi_web_app && uv run pytest -v
```

## Roadmap

- [ ] File upload via web interface
- [ ] Support for additional file formats (CSV, JSON, HTML)
- [ ] Real-time document indexing
- [ ] Multi-user support with authentication
- [ ] Document chunking strategies
- [ ] Query history and bookmarking
- [ ] Export search results
- [ ] Performance metrics dashboard

## License

MIT License

## Version

0.1.0
