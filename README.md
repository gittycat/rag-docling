# Locally Hosted RAG System

A locally hosted RAG (Retrieval-Augmented Generation) system for intelligent document research. Upload your private documents, ask questions in natural language, and get AI-powered answers with source citations—all running privately on your machine.

## Project Goal

Create an optimized RAG pipeline for local machines that balances accuracy with performance. Since consumer laptops can't run top-tier models, this project helps you find the best combination of small models and techniques for your documents.


## Main Features

- **Private & Local**: Can run entirely on your computer or on-prem data center. Alternatively can make use of frontier models for inference, embedding or reranking.
- **Plug and play models**: Supports multiple local (through Ollama) or online LLM models.
- **Evaluation page**: Multiple evals can be run to evaluate the RAG for accuracy and speed. __This is ongoing work__.
- **ChatGPT-like Interface**: Clean, familiar web interface
- **Multiple Document Formats**: PDF, DOCX, TXT, Markdown, HTML, PowerPoint, Excel
- **Source Citations**: Every answer includes references to source documents

## What You Need

- **Docker** (Docker Desktop, OrbStack, or similar)
- **Ollama** for running AI models locally
- **~4GB RAM** for the AI models
- **~2GB disk space** for models and data
- **just** Task runner. `brew install just`

## Installation

### 1. Install Dependencies

```bash
# Install Ollama
curl https://ollama.ai/install.sh | sh

# Download AI models
ollama pull gemma3:4b              # Question answering model
ollama pull nomic-embed-text       # Document indexing model

# Install Docker (choose one)
# - Docker Desktop: https://www.docker.com/products/docker-desktop/
# - OrbStack (macOS, faster): brew install orbstack
```

### 2. Get the Code

```bash
git clone https://github.com/gittycat/rag-docling.git
cd rag-docling
```

### 3. Configure the System

```bash
# Copy configuration files
cp config/models.yml.example config/models.yml
cp secrets/.env.example secrets/.env
cp secrets/ollama_config.env.example secrets/ollama_config.env

# (Optional) Edit config/models.yml to change models or settings
# (Optional) Add API keys to secrets/.env for cloud providers
```

### 4. Start the Application

```bash
docker compose up
```

That's it! Open your browser to **http://localhost:8000**

## How to Use

### 1. Upload Your Documents

1. Use the "Documents" section. The processing (embeddings creation) is what takes more of the time. A progress bar is shown.

### 2. Ask Questions

1. In the /chat page. Use it like any AI chat interface.

### 3. Manage Your Data (/documents)

- **View all documents** in the Admin section
- **Delete documents** you no longer need
- **Clear chat history** to start fresh

## Configuration

The system uses **YAML-based configuration** for easy customization:

### Quick Start (Using Defaults)
The example configuration files work out-of-the-box with Ollama. Just copy them:

```bash
cp config/models.yml.example config/models.yml
cp secrets/.env.example secrets/.env
cp secrets/ollama_config.env.example secrets/ollama_config.env
```

### Configuration Files (Not in Source Control)

These files must be created from their `.example` templates before running the application:

**`config/models.yml`** - Main configuration:
```yaml
llm:
  provider: ollama                              # ollama, openai, anthropic, google, deepseek, moonshot
  model: gemma3:4b
  base_url: http://host.docker.internal:11434
  timeout: 120
  keep_alive: 10m

embedding:
  provider: ollama
  model: nomic-embed-text:latest
  base_url: http://host.docker.internal:11434

eval:
  provider: anthropic
  model: claude-sonnet-4-20250514

reranker:
  enabled: true
  model: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_n: 5

retrieval:
  top_k: 10
  enable_hybrid_search: true
  rrf_k: 60
  enable_contextual_retrieval: false
```

**`secrets/.env`** - API keys:
```bash
LLM_API_KEY=                  # For cloud providers (not needed for Ollama)
ANTHROPIC_API_KEY=sk-ant-... # For evaluations (required)
```

**`secrets/ollama_config.env`** - Ollama settings:
```bash
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_KEEP_ALIVE=10m         # -1=forever, 0=unload, 10m=10 minutes
```

See `config/README.md` and `secrets/README.md` for detailed documentation.

## Testing

This project uses [just](https://just.systems/man/en/) as a task runner.

```bash
# Install dev dependencies
TODO: complete

# Unit tests (mocked, no services required)
TODO: complete

# Integration tests (requires: docker compose up -d)
TODO: complete

# Evaluation tests (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
TODO: complete

# List all available tasks
TODO: complete
```

## What's Next

TODO: roadmap


