# 2. Get RAGBench running

This chapter takes a fresh clone to a working query. Choose local or cloud models
before the first start; the checked-in configuration uses both.

## Prerequisites


- Docker Desktop, OrbStack or Podman

- Just task runner: `brew install just`
- Python 3.13+ and uv `brew install uv`

No separate local-model installer is needed: embedding inference runs as the
`tei` Docker Compose service, self-hosting `Qwen/Qwen3-Embedding-0.6B`.

Create the local environment used by `just show-config` and the evaluation recipes:

```bash
just setup
```

## Choose local or cloud models

The checked-in `config.yml` selects:

```yaml
active:
  inference: gpt5-mini    # OpenAI
  embedding: qwen3-embed  # self-hosted TEI
  eval: gpt5-2            # OpenAI judge
  reranker: minilm-l6     # local cross-encoder
```

Embedding already runs locally out of the box — `qwen3-embed` points at the
in-Compose `tei` service, nothing to install. This configuration needs only an
OpenAI API key, for generation and the eval judge. Laptop Compose has no local
LLM option. For a confidential corpus, use the separate AWS private mode in
[Chapter 12](12-private-aws-demo.md).

Available providers are OpenAI, Anthropic, `tei` (embedding only, self-hosted),
and `vllm` (the VPC-private AWS mode). The configured generation models include
`gpt5-mini`, `gpt56-luna`, `claude-haiku`, `claude-sonnet`, `claude-opus`, and
the AWS-mode-only `qwen35-9b`.

The only configured embedding model is `qwen3-embed` (`tei`, self-hosted), plus
`openai-ada`, `openai-3-small`, and `openai-3-large` for OpenAI.

See [Chapter 3](03-configuration-tour.md) before changing models on an existing
index. **Switching the active embedding model is a breaking change**: it always
invalidates every stored vector (dimension and/or model differ), and there are
no schema migrations for it — `services/postgres/init.sql` only runs on a
volume's first boot. Changing embedding models on a database that already has
documents means `docker compose down -v` (drops the Postgres volume) and
re-ingesting everything from scratch.

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

## Cache the reranker and warm the embedding weights

```bash
just init
```

This downloads the active reranker into `.cache/huggingface`, and also pulls
the `tei` image and warms its embedding weights into the `tei_data` volume so
`docker compose up` isn't the first time either download happens. The server
runs in offline Hugging Face mode and exits at startup if the configured
reranker model is absent. For another reranker model, pass its Hugging Face ID:

```bash
just init MODEL=BAAI/bge-reranker-base
```

If you skip `just init`, the first `docker compose up` against an empty
`tei_data` volume downloads `Qwen/Qwen3-Embedding-0.6B`'s weights (~1.2GB) from
HuggingFace itself — measured at **204 seconds, cold, on a fast connection**
(image pull, ~170s of weight download, ~18s warmup) before `tei` reports
healthy. That is comfortably inside the compose healthcheck's `start_period:
300s`, so it looks slow but is not stuck — see
[10. Troubleshooting](10-troubleshooting.md) if it's taking noticeably longer.

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
