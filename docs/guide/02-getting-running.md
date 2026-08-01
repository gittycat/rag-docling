# Getting running

This chapter gets you from a fresh clone to a working chat session: prerequisites,
the secrets you must create by hand, the one config decision you must make before
the first boot, starting the stack, and what survives when you tear it down.

## Prerequisites

You need:

- **Docker** — Docker Desktop, OrbStack, or Podman. The stack is defined entirely
  in Docker Compose files; there is no non-Docker way to run it.
- **`just`** — the command runner used for every recipe in this guide (`brew install just`
  or your platform's equivalent). Every `just` recipe has an underlying `docker compose`
  command; this guide gives both where it matters.
- **Ollama**, only if you plan to run any local model — the checked-in models are
  Ollama-backed for local inference/embedding (`gemma3-4b`, `llama3-8b`, `nomic-embed`).
  Not required if you intend to run cloud models only.
- Disk and memory headroom for whichever models you choose — local inference models
  and the reranker are downloaded into a bind-mounted cache the first time you fetch them.

`just preflight` (run automatically by `just up` and `just deploy`) checks that the
Docker daemon is reachable, and — only if `config.yml`'s `active.inference` or
`active.embedding` currently points at an `ollama` provider — that Ollama answers on
`localhost:11434`. If Ollama isn't running and you need it, start it with the Ollama
app or `ollama serve`.

## Secrets you must create before first start

The base stack reads credentials exclusively from Docker Compose **secrets** —
files under `secrets/`, mounted into containers at `/run/secrets/<NAME>`. The
application does not accept these values as plain environment variables. Before
your first `docker compose up` (or `just up`), the following files must exist:

| File | Used by | Required even for an all-local start? |
|---|---|---|
| `secrets/POSTGRES_SUPERUSER` | postgres | Yes |
| `secrets/POSTGRES_SUPERPASSWORD` | postgres | Yes |
| `secrets/RAG_SERVER_DB_USER` | postgres, rag-server, task-worker | Yes |
| `secrets/RAG_SERVER_DB_PASSWORD` | postgres, rag-server, task-worker | Yes |
| `secrets/OPENAI_API_KEY` | rag-server, task-worker, evals | Only if you select an OpenAI model anywhere (inference, embedding, or eval judge) |
| `secrets/ANTHROPIC_API_KEY` | rag-server, task-worker, evals | Only if you select an Anthropic model anywhere |

Docker Compose secrets are declared as `file: secrets/<NAME>` — if the file is
missing, the container that needs it will fail to start (Compose refuses to mount
a secret whose source file doesn't exist). Even for a fully local, Ollama-only
deployment, you still need the four Postgres/database secret files — the database
is not optional, and Postgres has no default credentials baked into the image.

Create them as flat text files with no trailing formatting concerns beyond
whitespace (the app strips leading/trailing whitespace and null bytes when it
reads them), for example:

```bash
mkdir -p secrets
echo -n "ragbench_admin" > secrets/POSTGRES_SUPERUSER
echo -n "$(openssl rand -hex 24)" > secrets/POSTGRES_SUPERPASSWORD
echo -n "ragbench_app" > secrets/RAG_SERVER_DB_USER
echo -n "$(openssl rand -hex 24)" > secrets/RAG_SERVER_DB_PASSWORD
```

Only add `secrets/OPENAI_API_KEY` and/or `secrets/ANTHROPIC_API_KEY` if the model
you're about to activate needs them (see below).

Separately, `just` itself (not Docker) reads `secrets/.env` for non-secret local
values used by `just` recipes — this is a plain dotenv file, unrelated to the
Docker secrets above. It is not required for `docker compose up` to work, only
for some `just` recipes that assume it exists.

## Choosing local vs. cloud models before first boot

This is the single most common first-run failure, so read this section before you
run anything.

The checked-in `config.yml` ships with **cloud models active**:

```yaml
active:
  inference: gpt5-mini
  embedding: nomic-embed
  eval: gpt5-2
  reranker: minilm-l6
```

`active.inference` is `gpt5-mini` (OpenAI) and `active.eval` is `gpt5-2` (also
OpenAI) — both `requires_api_key: true`. If you start the stack as-is without an
`OPENAI_API_KEY` secret file, the rag-server and evals containers will fail to
validate their provider requirements at boot.

`active.embedding` is already `nomic-embed`, which is Ollama-backed and local —
you do not need to change this one for a local-only start, but you do need Ollama
running and reachable (see Prerequisites).

**If you want a fully local, no-cloud-API-key start**, edit `config.yml` before
your first `up` and change `active.inference` to an Ollama-backed key — the two
defined in the checked-in file are `gemma3-4b` and `llama3-8b`:

```yaml
active:
  inference: gemma3-4b   # was gpt5-mini
  embedding: nomic-embed  # already local — no change needed
  eval: gpt5-2            # can stay cloud, or point at a local model if you add one
  reranker: minilm-l6
```

Before this will work you also need the models pulled into Ollama:

```bash
ollama pull gemma3:4b
ollama pull nomic-embed-text
```

If instead you want to keep cloud inference, create the matching secret file
(`secrets/OPENAI_API_KEY` or `secrets/ANTHROPIC_API_KEY`) before starting.

**A warning about three model choices that will fail at boot regardless of what
secret files you create**: selecting `gemini-pro`, `deepseek-chat`, or
`moonshot-v1` as `active.inference` (or `active.eval`) will pass YAML validation
but fail at container boot. The application code knows how to read
`GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, and `MOONSHOT_API_KEY`, but **no compose
file declares any of these three as a Docker secret** — there is no
`secrets: GOOGLE_API_KEY: file: secrets/GOOGLE_API_KEY` entry anywhere in
`docker-compose.yml` or its overlays. Picking one of these three models is not
currently a supported path without hand-editing the compose file yourself to add
the secret declaration and mount, in addition to creating the secret file.
Everything else in `models.inference` and `models.eval` (`gemma3-4b`, `llama3-8b`,
`gpt5-mini`, `claude-sonnet`, `claude-opus`) is fully wired.

## Pre-fetching the reranker

Before your first `up`, run:

```bash
just init
```

This runs a disposable rag-server container that downloads the active reranker
model (default `cross-encoder/ms-marco-MiniLM-L-6-v2`) into `.cache/huggingface`,
which is bind-mounted into both `rag-server` and `task-worker`. `just init MODEL=...`
lets you pass a different Hugging Face model id if you've changed
`active.reranker`.

This step matters because rag-server checks at startup whether the reranker
model is present in the local Hugging Face cache, and **fails fast with a
`RuntimeError` if it is not** — the container will not silently fall back to
downloading it live, and it will not come up in a degraded state. If reranking is
enabled (`reranker.enabled: true`, the default) and you skip `just init`, the
container starts, then dies on this check, and the compose healthcheck for
rag-server will never pass. The error message it logs points back at running
`just init`.

## Starting the stack

```bash
just up
```

This runs `preflight` (the Docker/Ollama sanity check above) and then
`docker compose up -d`, bringing up `postgres`, `chromadb`, `rag-server`,
`task-worker`, `webapp`, and `evals`.

## Confirming health

```bash
docker compose ps
```

Watch for all services reaching `healthy` (rag-server and evals both have Docker
healthchecks; postgres has a real `pg_isready` check). Note that rag-server's and
evals' Docker healthchecks only confirm the process is answering HTTP — they do
not verify Postgres/ChromaDB/Ollama connectivity from inside the app. For that,
once the stack is up:

```bash
curl http://localhost:8001/metrics/system
```

The `health_status` field (`"healthy"` or `"degraded"`) and the `component_status`
object (per-component postgres/ollama checks) are the real dependency check.

Tail logs at any point with:

```bash
just logs
```

or `docker compose logs -f <service>` for a single service.

Open the web UI at **http://localhost:8000**. The eval service API answers
directly at **http://localhost:8002**.

You can also sanity-check which models are actually active before or after
starting:

```bash
just show-config
```

## Ingesting your first documents

Use the Upload page in the web UI (`http://localhost:8000/upload`), or the
underlying API directly:

```bash
curl -F "files=@/path/to/your/document.pdf" http://localhost:8001/upload
```

Ingestion runs asynchronously through the task worker; the Upload page polls
task status for you. Give it a moment — contextual retrieval (if enabled) and
embedding generation both take real wall-clock time per document.

## Asking a first question

From the chat page (`http://localhost:8000/chat`), or directly:

```bash
curl -N http://localhost:8001/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "What does this document say about X?"}'
```

(`-N` disables curl's output buffering so you see the SSE stream as it arrives.)

## Stopping, and what persists

```bash
just down
```

is `docker compose down` — it stops and removes containers but leaves named
volumes and bind-mounted host directories intact. On the next `just up`, your
documents, chat history, and vector index are all still there.

What persists across a plain `down`:

- **`postgres_data`** (named volume) — all relational state: document metadata,
  chat sessions/history, the task queue.
- **`chroma_data`** (named volume) — the vector index.
- **`./config.yml`** (host bind mount) — your configuration.
- **`./data/indexed_documents`** (host bind mount) — the original uploaded source
  files.
- **`./.cache/huggingface`** (host bind mount) — downloaded model weights,
  including whatever `just init` fetched.

What `docker compose down -v` additionally destroys — the `-v` flag removes named
volumes:

- **`postgres_data`** — every document record, chat session, and the task queue.
  Gone.
- **`chroma_data`** — the entire vector index. Recoverable only by re-ingesting
  every document from scratch (a full re-embed of the corpus).

The bind-mounted host directories (`data/indexed_documents`, `config.yml`,
`.cache/huggingface`) are **not** touched by `-v` — they live on the host
filesystem, not in a Docker-managed volume, and survive until you delete them
yourself.
