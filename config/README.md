# Configuration Directory

This directory contains YAML-based configuration for the RAG system.

## Setup

1. Copy the example file:
   ```bash
   cp models.yml.example models.yml
   ```

2. Edit `models.yml` to configure:
   - LLM provider and model
   - Embedding model
   - Evaluation model
   - Reranker settings
   - Retrieval parameters

## Configuration Structure

### LLM Configuration

Configure your main language model:

```yaml
llm:
  provider: ollama  # Options: ollama, openai, anthropic, google, deepseek, moonshot
  model: gemma3:4b
  base_url: http://host.docker.internal:11434
  timeout: 120
  keep_alive: 10m  # Ollama only
```

### Embedding Configuration

Configure the embedding model for vector representations:

```yaml
embedding:
  provider: ollama
  model: nomic-embed-text:latest
  base_url: http://host.docker.internal:11434
```

### Evaluation Configuration

Configure the model used for DeepEval metrics:

```yaml
eval:
  provider: anthropic
  model: claude-sonnet-4-20250514
  # Citation scope for evaluation:
  # - retrieved: treat all retrieved chunks as citations
  # - explicit: only use explicitly cited chunks (if provided by the server)
  citation_scope: retrieved
  # Citation format for explicit citations
  # - numeric: uses [1], [2] style references mapped to source order
  citation_format: numeric
  # Abstention phrases used to detect "no answer" responses
  abstention_phrases:
    - "I don't have enough information to answer this question."
    - "I do not have enough information to answer this question."
    - "I don't have enough information to answer the question."
    - "I do not have enough information to answer the question."
    - "Not enough information to answer."
    - "Insufficient information to answer."
```

**Note:** Requires `ANTHROPIC_API_KEY` in `secrets/.env`

### Reranker Configuration

Configure the reranker for improving retrieval quality:

```yaml
reranker:
  enabled: true
  model: cross-encoder/ms-marco-MiniLM-L-6-v2
  top_n: 5
```

### Retrieval Configuration

Configure hybrid search and retrieval parameters:

```yaml
retrieval:
  top_k: 10                          # Number of nodes to retrieve
  enable_hybrid_search: true         # BM25 + Vector with RRF fusion
  rrf_k: 60                          # Reciprocal Rank Fusion parameter
  enable_contextual_retrieval: false # Anthropic contextual retrieval (slower)
```

## Provider-Specific Notes

### Ollama (Local)
- Runs on host machine at `http://host.docker.internal:11434`
- No API key required
- `keep_alive`: `-1` (forever), `0` (unload immediately), `10m` (10 minutes)

### OpenAI
- Requires `LLM_API_KEY` in `secrets/.env`
- Set `base_url: https://api.openai.com/v1`
- Popular models: `gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo`

### Anthropic
- Requires `LLM_API_KEY` in `secrets/.env`
- Set `base_url: https://api.anthropic.com`
- Popular models: `claude-sonnet-4-20250514`, `claude-opus-4-20250514`

### Google (Gemini)
- Requires `LLM_API_KEY` in `secrets/.env`
- Popular models: `gemini-2.0-flash`, `gemini-1.5-pro`

### DeepSeek
- Requires `LLM_API_KEY` in `secrets/.env`
- Popular models: `deepseek-chat`, `deepseek-reasoner`

### Moonshot (Kimi)
- Requires `LLM_API_KEY` in `secrets/.env`
- Auto-configures `base_url: https://api.moonshot.cn/v1`
- Popular models: `moonshot-v1-8k`, `moonshot-v1-32k`

## Docker Volume Mounting

This directory is mounted as read-only in Docker containers:
- Path: `/app/config/models.yml`
- Mode: Read-only (`:ro`)
- Used by: `rag-server` and `celery-worker`

## Validation

The system validates configuration on startup:
- Required fields must be present
- API keys checked for cloud providers
- Model names cannot be empty
- Provider must be a valid option

See `services/rag_server/infrastructure/config/models_config.py` for implementation.
