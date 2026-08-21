# 2. Get RAGBench running

This chapter takes a fresh clone to a working query. Choose local or cloud models
before the first start; the checked-in configuration uses both.

## Prerequisites

| Requirement | When needed |
|---|---|
| Docker Desktop, OrbStack, or Podman | Always; the stack uses Compose |
| `just` | For the commands in this guide (`brew install just`) |
| Python 3.13 and `uv` | For config inspection, evaluations, and local tests |
| Ollama | When any active model uses the `ollama` provider |
| Disk space | For local models and the reranker cache |

`just up` and `just deploy` run `just preflight`, which checks Docker and Ollama.

Create the local environment used by `just show-config` and the evaluation recipes:

```bash
just setup
```

## Choose local or cloud models

The checked-in `config.yml` selects:

```yaml
active:
  inference: gpt5-mini    # OpenAI
  embedding: nomic-embed  # Ollama
  eval: gpt5-2            # OpenAI judge
  reranker: minilm-l6     # local cross-encoder
```

This configuration needs Ollama and an OpenAI API key. For local generation,
change `active.inference`:

```yaml
active:
  inference: granite4-8b
  embedding: nomic-embed
  eval: gpt5-2
  reranker: minilm-l6
```

Then download the local models:

```bash
ollama pull granite4.1:8b
ollama pull nomic-embed-text
```

Available providers are OpenAI, Anthropic, and Ollama. The configured generation
models include `gemma3-4b`, `qwen35-4b`, `granite4-8b`, `gpt5-mini`,
`gpt56-luna`, `claude-haiku`, `claude-sonnet`, and `claude-opus`.

Configured embedding models are `nomic-embed`, `qwen3-embed-06b`, and
`embeddinggemma` for Ollama, plus `openai-ada`, `openai-3-small`, and
`openai-3-large` for OpenAI.

See [Chapter 3](03-configuration-tour.md) before changing models on an existing
index.

## Create secrets first

Credentials must be files under `secrets/`. Compose mounts each file at
`/run/secrets/<NAME>`; environment variables with the same names are ignored.

| File | Required |
|---|---|
| `POSTGRES_SUPERUSER` | Always |
| `POSTGRES_SUPERPASSWORD` | Always |
| `RAG_SERVER_DB_USER` | Always |
| `RAG_SERVER_DB_PASSWORD` | Always |
| `OPENAI_API_KEY` | When an active model uses OpenAI |
| `ANTHROPIC_API_KEY` | When an active model uses Anthropic |

```bash
mkdir -p secrets
echo -n "ragbench_admin" > secrets/POSTGRES_SUPERUSER
echo -n "$(openssl rand -hex 24)" > secrets/POSTGRES_SUPERPASSWORD
echo -n "ragbench_app" > secrets/RAG_SERVER_DB_USER
echo -n "$(openssl rand -hex 24)" > secrets/RAG_SERVER_DB_PASSWORD
```

`secrets/.env` holds non-secret values used by some `just` recipes. It is separate
from Compose secrets and is not needed by `docker compose up`.

## Cache the reranker

```bash
just init
```

This downloads the active reranker into `.cache/huggingface`. The server runs in
offline Hugging Face mode and exits at startup if the configured model is absent.
For another model, pass its Hugging Face ID:

```bash
just init MODEL=BAAI/bge-reranker-base
```

## Start and check health

```bash
just up
docker compose ps
```

The web app is at <http://localhost:8000>; the eval API is at
<http://localhost:8002>.

Container health checks confirm that HTTP responds. Check dependencies separately:

```bash
curl -s http://localhost:8001/metrics/system \
  | jq '.health_status, .component_status'
```

`health_status` is `healthy` or `degraded`. When hybrid search is enabled,
`component_status.bm25` shows whether keyword search is available. A BM25 failure
silently reduces hybrid retrieval to vector-only.

Useful checks:

```bash
just logs
docker compose logs -f rag-server
just show-config
```

## Ingest a document and ask a question

Use the web app, or call the API:

```bash
curl -F "files=@/path/to/document.pdf" http://localhost:8001/upload

curl -N http://localhost:8001/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "What does this document say about X?"}'
```

Ingestion is asynchronous. Large files, local embeddings, and contextual
retrieval increase processing time.

## Stop without deleting data

```bash
just down
```

This removes containers but preserves:

| Storage | Contents |
|---|---|
| `postgres_data` volume | Documents, chunks, embeddings, chat sessions, and task state |
| `config.yml` | Configuration |
| `data/indexed_documents` | Uploaded source files |
| `.cache/huggingface` | Downloaded models |

`docker compose down -v` deletes the PostgreSQL volume, which now holds the
embeddings as well. There is no built-in backup, so recovery requires
re-ingestion. Host bind mounts remain.

**Next:** [3. Configure the RAG pipeline](03-configuration-tour.md).
