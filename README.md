# Locally Hosted RAG System

A locally hosted RAG (Retrieval-Augmented Generation) system for intelligent document research. Upload your private documents, ask questions in natural language, and get AI-powered answers with source citations—all running privately on your machine.

## Project Goal

Create an optimized RAG pipeline for local machines that balances accuracy with performance. Since consumer laptops can't run top-tier models, this project helps you find the best combination of small models and techniques for your documents.



## Features

- **Private & Local**: Runs entirely on your machine—no data leaves your computer
- **Multiple Document Formats**: PDF, DOCX, TXT, Markdown, HTML, PowerPoint, Excel
- **Conversational Q&A**: Ask follow-up questions and get contextual answers
- **Source Citations**: Every answer includes references to source documents
- **ChatGPT-like Interface**: Clean, familiar web interface
- **Smart Search**: Combines keyword and semantic search for better accuracy
- **Real-time Progress**: See document processing status as it happens

## What You Need

- **Docker** (Docker Desktop, OrbStack, or similar)
- **Ollama** for running AI models locally
- **~4GB RAM** for the AI models
- **~2GB disk space** for models and data

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

### 3. Start the Application

```bash
docker compose up
```

That's it! Open your browser to **http://localhost:8000**

## How to Use

### 1. Upload Your Documents

1. Click the **Admin** button
2. Click **Upload Documents**
3. Select your files (PDF, DOCX, TXT, etc.)
4. Wait for processing to complete

### 2. Ask Questions

1. Type your question in the main chat interface
2. Get AI-generated answers with source citations
3. Ask follow-up questions to dig deeper

### 3. Manage Your Data

- **View all documents** in the Admin section
- **Delete documents** you no longer need
- **Clear chat history** to start fresh

## Configuration

The system works out-of-the-box with sensible defaults. Advanced users can modify settings in `docker-compose.yml` to change models, adjust retrieval parameters, or enable/disable features. See [DEVELOPMENT.md](DEVELOPMENT.md) for details.


## Need Help?

- **Troubleshooting**: See [DEVELOPMENT.md](DEVELOPMENT.md) for common issues
- **API Reference**: Full endpoint documentation in [DEVELOPMENT.md](DEVELOPMENT.md)
- **Technical Details**: Architecture and implementation in [docs/](docs/)

## What's Next

- **Better Evaluation**: Easier testing of different models and features (in progress with DeepEval)
- **Cloud Deployment**: Option to run online with proper security and privacy
- **More Formats**: Additional document types and export options

## License

MIT License

