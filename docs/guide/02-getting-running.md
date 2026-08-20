# 2. Getting running

Fresh clone to working chat session. The one decision to make before first boot is
[local vs cloud models](#choose-local-or-cloud-models-before-first-boot) — get it
wrong and the stack will not start.

## Prerequisites

| Need | Why |
|---|---|
| **Docker** | Docker Desktop, OrbStack, or Podman. The stack is Compose-only; there is no non-Docker path. |
| **`just`** | The command runner used throughout (`brew install just`). Every recipe has an underlying `docker compose` form. |
| **Ollama** | Only if you run any local model. Required for the default `nomic-embed` embedding. |
| **Disk headroom** | Local models and the reranker download into a bind-mounted cache on first fetch. |

`just preflight` runs automatically before `just up` and `just deploy`. It checks
that Docker is reachable and — only when `active.inference` or `active.embedding`
points at an `ollama` provider — that Ollama answers on `localhost:11434`.

## Create secrets first

Credentials come exclusively from Docker Compose **secrets**: files under
`secrets/`, mounted at `/run/secrets/<NAME>`. Environment variables of the same
name are deliberately ignored. Compose refuses to start a container whose secret
file is missing.

| File | Required |
|---|---|
| `secrets/POSTGRES_SUPERUSER` | Always |
| `secrets/POSTGRES_SUPERPASSWORD` | Always |
| `secrets/RAG_SERVER_DB_USER` | Always |
| `secrets/RAG_SERVER_DB_PASSWORD` | Always |
| `secrets/OPENAI_API_KEY` | Only if an OpenAI model is active (inference, embedding, or eval judge) |
| `secrets/ANTHROPIC_API_KEY` | Only if an Anthropic model is active |

The four Postgres files are needed even for a fully local deployment — the
database is not optional and the image has no default credentials.

```bash
mkdir -p secrets
echo -n "ragbench_admin" > secrets/POSTGRES_SUPERUSER
echo -n "$(openssl rand -hex 24)" > secrets/POSTGRES_SUPERPASSWORD
echo -n "ragbench_app" > secrets/RAG_SERVER_DB_USER
echo -n "$(openssl rand -hex 24)" > secrets/RAG_SERVER_DB_PASSWORD
```

Leading and trailing whitespace and null bytes are stripped on read, so the exact
file ending does not matter.

Separately, `just` reads `secrets/.env` for non-secret local values used by some
recipes. That is a plain dotenv file, unrelated to Docker secrets, and
`docker compose up` does not need it.

## Choose local or cloud models before first boot

The checked-in `config.yml` ships with **cloud inference active**:

```yaml
active:
  inference: gpt5-mini    # OpenAI — needs secrets/OPENAI_API_KEY
  embedding: nomic-embed  # Ollama — local, needs Ollama running
  eval: gpt5-2            # OpenAI — needs secrets/OPENAI_API_KEY
  reranker: minilm-l6     # local cross-encoder
```

Start as-is without `secrets/OPENAI_API_KEY` and the rag-server and evals
containers fail their provider validation at boot.

**For a fully local start**, point `active.inference` at an Ollama-backed model:

```yaml
active:
  inference: granite4-8b  # or gemma3-4b, qwen35-4b
  embedding: nomic-embed  # already local
  eval: gpt5-2            # judging can stay cloud, or use a local model
  reranker: minilm-l6
```

Then pull the models:

```bash
ollama pull granite4.1:8b
ollama pull nomic-embed-text
```

### Models available out of the box

| Key | Provider | Model | Notes |
|---|---|---|---|
| `gemma3-4b` | Ollama | `gemma3:4b` | Small, fast |
| `qwen35-4b` | Ollama | `qwen3.5:4b` | 256K context, ~3.4 GB |
| `granite4-8b` | Ollama | `granite4.1:8b` | Apache-2.0, 128K context, tuned for RAG |
| `gpt5-mini` | OpenAI | `gpt-5-mini` | Shipped default |
| `gpt56-luna` | OpenAI | `gpt-5.6-luna` | |
| `claude-haiku` | Anthropic | `claude-haiku-4-5` | Cheapest Anthropic option |
| `claude-sonnet` | Anthropic | `claude-sonnet-5` | |
| `claude-opus` | Anthropic | `claude-opus-5` | |

Embedding models: `nomic-embed`, `qwen3-embed-06b`, `embeddinggemma` (all local);
`openai-ada`, `openai-3-small`, `openai-3-large` (cloud).

Only OpenAI, Anthropic, and Ollama are wired. Adding another provider means
touching six places in the code plus the compose secret declarations —
`config.yml` carries a commented template listing them.

## Pre-fetch the reranker

```bash
just init
```

This downloads the active reranker (default `cross-encoder/ms-marco-MiniLM-L-6-v2`)
into `.cache/huggingface`, bind-mounted into rag-server and task-worker. Pass a
different Hugging Face id with `just init MODEL=<id>` if you changed
`active.reranker`.

Do not skip this. With reranking enabled (the default), rag-server checks at
startup that the model is in the local cache and **exits with a `RuntimeError` if
it is not** — `HF_HUB_OFFLINE=1` is set, so there is no silent live download and
no degraded start. Skip `just init` and the container boots, dies on this check,
and never passes its healthcheck.

## Start and confirm health

```bash
just up            # preflight + docker compose up -d
docker compose ps  # watch for healthy
```

Docker healthchecks on rag-server and evals only confirm the process answers HTTP.
For the real dependency check:

```bash
curl -s http://localhost:8001/metrics/system | jq '.health_status, .component_status'
```

`health_status` is `healthy` or `degraded`; `component_status` carries per-component
postgres/bm25/ollama results. `bm25` appears only when hybrid search is enabled —
`unavailable` there means the `pg_textsearch` extension or index cannot be queried,
which silently reduces every hybrid query to vector-only.

```bash
just logs                        # all services
docker compose logs -f rag-server  # one service
just show-config                 # which models are actually active
```

Web UI: **http://localhost:8000**. Eval API: **http://localhost:8002**.

## Ingest and ask

```bash
# Upload — or use http://localhost:8000/upload
curl -F "files=@/path/to/document.pdf" http://localhost:8001/upload

# Ask — or use http://localhost:8000/chat
curl -N http://localhost:8001/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "What does this document say about X?"}'
```

Ingestion is asynchronous through the task worker; the Upload page polls task
status. Give it time — embedding and (if enabled) contextual retrieval both cost
real wall-clock time per document. `-N` disables curl buffering so you see the SSE
stream arrive.

## Stopping, and what survives

```bash
just down    # docker compose down — containers only
```

| Survives `down` | What it holds |
|---|---|
| `postgres_data` (volume) | Document metadata, chat sessions, task queue |
| `chroma_data` (volume) | Vector index |
| `./config.yml` (bind mount) | Your configuration |
| `./data/indexed_documents` (bind mount) | Original uploaded files |
| `./.cache/huggingface` (bind mount) | Downloaded model weights |

`docker compose down -v` additionally **destroys** `postgres_data` and
`chroma_data`. There is no backup mechanism for either; recovery means re-ingesting
every document. The bind-mounted host directories are untouched by `-v` — they live
on your filesystem, not in a Docker volume.

---

**Next:** [3. Configuration tour](03-configuration-tour.md).
