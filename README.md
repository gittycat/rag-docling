# Locally Hosted RAG System

A locally hosted RAG (Retrieval-Augmented Generation) system for intelligent document research. Upload your own private documents, ask questions in plain English, and get AI-powered answers with source citations—all running privately on your machine.

## Project Goal
Obviously no current laptops has the GPU power to use top of the line models and techniques across a full RAG pipeline. This project aims to allow the evaluation of multiple small models and features together to find an optimum pipeline for given set of documents that is still reasonably usable on a local computer.



## Features

### Core Functionality

- **Question Answering**: Local LLM used for interacting with documents.
- **Document Formats**: Currently supports txt, md, pdf, docx, pptx, xlsx, html.
- **Chat History**: Session-based conversation memory persists across restarts
- **Local Deployment**: Can runs entirely on your machine with no external API dependencies
- **Web Interface**: ChagGPT like interface with document management.

### Retrieval Methods

- **Contextual Retrieval**: Document context embedded with chunks for improved accuracy
- **Structure Preservation**: Maintains document hierarchy including headings, sections, and tables
- **Hybrid Search**: BM25 keyword matching combined with vector semantic search
- **Reranking**: Cross-encoder model for result refinement. Uses a small memory loaded model.

### System Capabilities

- **Async Processing**: Background document indexing via Celery task queue
- **Progress Tracking**: Real-time status updates for document uploads
- **Source Attribution**: Results include document excerpts and metadata

## Technology Stack

- **Frontend**: SvelteKit + Tailwind CSS.
- **Backend**: Python + FastAPI
- **Vector Database**: ChromaDB
- **AI Models**: Ollama (local LLM and embeddings)
- **Document Processing**: Docling + LlamaIndex
- **Task Queue**: Celery + Redis
- **Package Management**: uv

## Architecture

```text
                        ┌────────────────────────────────────┐
                        │   External: Ollama (Host Machine)  │
          End User      │   host.docker.internal:11434       │
          (browser)     │   - LLM: gemma3:4b                 │
              │         │   - Embeddings: nomic-embed-text   │
              │         └────────────────────────────────────┘
              │                              │
              │    Public Network (host)     │
--------------│------------------------------│-------------------
              │    Private Network (Docker)  │
              ▼                              │
    ┌─────────────────┐           ┌──────────────────────┐
    │   WebApp        │    HTTP   │   RAG Server         │
    │   (SvelteKit)   │◄─────────►│   (FastAPI)          │
    │   Port: 8000    │           │   Port: 8001         │
    └─────────────────┘           │                      │
                                  │  ┌────────────────┐  │
                                  │  │ Docling        │  │
                                  │  │ + LlamaIndex   │  │
                                  │  │ + Hybrid Search│  │
                                  │  │ + Reranking    │  │
                                  │  └────────────────┘  │
                                  └──────────┬───────────┘
                                             │
                                             │
           ┌─────────────┬───────────────────┼─────────┐
           │             │                   │         │
      ┌────▼─────┐  ┌────▼────┐       ┌──────▼──────┐  │
      │ ChromaDB │  │  Redis  │       │   Celery    │  │
      │ (Vector  │  │(Message │       │   Worker    │  │
      │  DB)     │  │ Broker) │       │  (Async     │  │
      └──────────┘  └─────────┘       │ Processing) │  │
                                      └──────┬──────┘  │
                                             │         │
                                      ┌───────────────────┐
                                      │   Shared Volume   │
                                      │   /tmp/shared     │
                                      │   (File Transfer) │
                                      └───────────────────┘

```

## Prerequisites

1. **Docker container host** (Docker Desktop, OrbStack, or Podman)
2. **Ollama** for running AI models locally
3. **Python 3.13** and [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager

### Installation

```bash
# Install Docker alternative (faster than Docker Desktop)
brew install orbstack

# Install uv package manager
brew install uv

# Install Ollama (recommended method)
curl https://ollama.ai/install.sh | sh

# Pull required models
ollama pull gemma3:4b              # Inference model
ollama pull nomic-embed-text       # Embedding model
```

## Quick Start

### 1. Clone and Setup

```bash
git clone git@github.com:gittycat/rag-docling.git
cd rag-docling
```

### 2. Configure Secrets (Optional)

```bash
# Create secrets directory
mkdir -p secrets

# Add Ollama configuration if needed
echo "OLLAMA_HOST=http://host.docker.internal:11434" > secrets/ollama_config.env
```

### 3. Start Services

```bash
docker compose up
```

Open the WebApp at **<http://localhost:8000>**

## Basic Usage

### Upload Documents

1. Open <http://localhost:8000>
2. Navigate to the Admin section
3. Click "Upload Documents"
4. Select files (PDF, DOCX, TXT, MD, etc.)
5. Monitor progress in real-time

### Ask Questions

1. Use the main page to query your documents

### Manage Documents

- **View Documents**: See all indexed documents in the Admin section
- **Delete Documents**: Remove documents you no longer need
- **Clear Chat**: Start a fresh conversation anytime

## Configuration

Basic configuration is handled through environment variables in `docker-compose.yml`. For most users, the defaults work well.

### Key Settings

- **Models**: Change LLM or embedding models (default: gemma3:4b, nomic-embed-text)
- **Retrieval**: Adjust number of results returned (default: 10)
- **Features**: Enable/disable hybrid search, contextual retrieval, reranking

For detailed configuration options, see [DEVELOPMENT.md](DEVELOPMENT.md).


## Documentation

Most of the extra documentation is for use by the Claude Code environment development.
It includes more in depth search on techniques to improve accuracy.
I will probably migrate to using [Claude Skills](https://support.claude.com/en/articles/12512176-what-are-skills) 
for some of this info in the future.

- **[DEVELOPMENT.md](DEVELOPMENT.md)**: API documentation, configuration details, troubleshooting
- **[CLAUDE.md](CLAUDE.md)**: Project guide for Claude Code development
- **[docs/](docs/)**: Additional guides and implementation details

## Roadmap

TODO: Detail the roadmap.

Overall, the immediate goal is to improve evaluation (make it easier to compare features/models), then migrating the application online which will require security and data privacy improvements.

## License

MIT License

