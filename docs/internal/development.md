# Development

This covers getting the stack running locally, the `just` recipes that drive day-to-day work, config inspection, and where to look when something breaks. For architecture, see `architecture.md`; for the full API surface, see `rag-api.md` and `eval-service-api.md`.

## Prerequisites

- **Python 3.13+** with [uv](https://docs.astral.sh/uv/) as the package manager and runner.
- **Node.js 22+** with npm, for the webapp.
- **Docker** (Docker Desktop, OrbStack, or Podman) — the whole stack runs as Compose services.
- **Ollama**, running on the host, if any active model in `config.yml` uses the `ollama` provider (the default checked-in config does use local Ollama models for inference and embedding). Pull whatever models `config.yml`'s `active:` block points at, e.g.:
  ```bash
  ollama pull gemma3:4b
  ollama pull nomic-embed-text
  ```

## First-time setup

```bash
git clone <repo-url>
cd ragbench

# Local Python venv for unit tests / tooling (uv-managed)
just setup

# Frontend dependencies
cd services/webapp && npm install && cd ..

# Create the Docker secret files referenced in docker-compose.yml under secrets/
# (one raw value per file — OPENAI_API_KEY, ANTHROPIC_API_KEY, POSTGRES_SUPERUSER,
# POSTGRES_SUPERPASSWORD, RAG_SERVER_DB_USER, RAG_SERVER_DB_PASSWORD)

# config.yml is checked into the repo — edit it directly for active models and retrieval settings.
```

`just setup` runs `uv sync --group dev --python 3.13` inside `services/rag_server`. There is no `eval` dependency group in `services/rag_server`'s `pyproject.toml` any more — the eval service has its own, separate `pyproject.toml` and dependency set under `services/evals/`, installed inside its own container image.

If you plan to run the reranker outside of a fresh pull, pre-download its weights into the bind-mounted Hugging Face cache before first `up` so the first query isn't slowed by a model download:

```bash
just init                       # defaults to cross-encoder/ms-marco-MiniLM-L-6-v2
just init MODEL="some/other-model"
```

## Running the stack

```bash
just up      # preflight check, then docker compose up -d
```

`just up` depends on `preflight`, which checks that the Docker daemon is reachable and — only if an active model in `config.yml` uses the `ollama` provider — that Ollama is reachable on `localhost:11434`. This fails fast with a clear message rather than letting the stack start against an unreachable model provider.

To confirm it's working:

```bash
just show-config          # compact: active LLM/embedding/reranker/eval models
curl http://localhost:8001/health    # rag-server trivial liveness check
curl http://localhost:8002/health    # eval service trivial liveness check
```

Then open the webapp at `http://localhost:8000`, upload a document, and ask a question. `just logs` tails every service's logs if something doesn't come up.

```bash
just down    # stop the stack
```

## `just` recipe reference

`justfile` loads non-secret local dev environment variables from `secrets/.env` for every recipe, and suppresses command echoing. `just test` is an alias for `test-unit`.

| Recipe | What it runs | Depends on | Use it for |
|---|---|---|---|
| `build` | `docker compose build` | — | Rebuild all images |
| `preflight` | Checks Docker daemon + conditionally Ollama reachability | — | Sanity check before `up`/`deploy` |
| `up` | `docker compose up -d` | `preflight` | Start the local stack |
| `down` | `docker compose down` | — | Stop the local stack |
| `logs` | `docker compose logs -f` | — | Tail all service logs |
| `setup` | `uv sync --group dev --python 3.13` in `services/rag_server` | — | Create/refresh the local venv for unit tests |
| `init MODEL=...` | Pre-downloads a model (default: the reranker) into the bind-mounted HF cache | — | Avoid a slow first reranker load |
| `clean` | Deletes `__pycache__`, `.pytest_cache`, `*.pyc` under `services/rag_server` | — | Reset local build/test artifacts |
| `test-unit` (alias `test`) | `pytest tests/ --ignore=tests/integration -v` in the local venv | `setup` | Run unit tests, no Docker needed |
| `test-integration` | `pytest tests/integration -v --run-integration`, run inside a disposable container reusing the `rag-server` image | `up` | Run the integration suite |
| `test-integration-full` | Same, plus `--run-slow` | `up` | Integration + slow tests |
| `test-eval` | 5-sample smoke eval via `evals.cli eval --tier end_to_end --datasets ragbench --samples 5` against the live `evals` service | `show-config`, `up` | Quick eval sanity check |
| `test-eval-full` | Full eval run across `ragbench,qasper,hotpotqa,msmarco`, all samples | `show-config`, `up` | Full eval suite |
| `eval +ARGS` | `evals.cli eval {{ARGS}}` | `show-config`, `up` | Custom eval invocation |
| `eval-datasets` | `evals.cli datasets` | `up` | List available eval datasets |
| `eval-calibrate SAMPLES=20` | `evals.cli calibrate --samples {{SAMPLES}}` | `up` | Calibrate the LLM judge against RAGBench TRACe ground truth |
| `eval-compare +ARGS` | `evals.cli compare {{ARGS}}` | `up` | Diff two eval run IDs |
| `show-config` | Prints a compact config banner | — | Quick check of active models |
| `show-config-full` | Prints the full config banner | — | Full config dump |
| `deploy ENV="server"` | `docker compose -f docker-compose.yml -f docker-compose.{{ENV}}.yml up -d --build` | `preflight` | Deploy an overlay tier (`server` or `cloud`) |
| `deploy-down ENV="server"` | Tears down a deployed overlay | — | Stop a deployed overlay |
| `release VERSION` | Tags `vVERSION`, bumps `services/rag_server/pyproject.toml` and `services/webapp/package.json` versions, commits, pushes `main` with tags | — | Cut a release |

### `just` is the only supported interface

A root `Makefile` used to exist alongside the justfile, but it predated the eval service's extraction into `services/evals/` and was never updated — its eval targets pointed at `services/rag_server/tests/test_rag_eval.py`, which no longer exists, and its `test-unit` target carried the same dead `--ignore` flags. It has been deleted; `just` was already a strict superset of everything it did.

`just` correctly targets the separate `evals` service and its CLI for anything eval-related, and it runs integration tests inside a disposable container built from the `rag-server` service definition rather than against the host venv — avoiding the config-drift risk of a second, hand-maintained test-runner environment.

## Config inspection

```bash
just show-config         # compact: LLM, embedding, reranker, eval model, one line each
just show-config-full    # full: adds base URLs, timeouts, retrieval settings, PII masking config
```

Both recipes call `print_config_banner()`, which renders from the `ModelsConfig` object: LLM, embedding, reranker, retrieval (top-k, hybrid search + RRF k, contextual retrieval), eval/judge, and PII masking sections.

**Neither recipe prints `database.*` or `chat_memory.*` configuration.** Those sections exist in `config.yml` but are consumed by separate settings paths not wired into `print_config_banner()` — to check connection-pool sizing or chat-memory cache bounds, read `config.yml` directly (see `configuration-reference.md` and `database.md`).

## Common development loops

- **Backend code change, no rebuild needed for tests:** edit under `services/rag_server`, run `just test-unit` against the local venv — no Docker involved.
- **Backend code change, needs the running stack:** `docker compose build rag-server && just up` to pick up the change, or run `.venv/bin/uvicorn main:app --reload --port 8001` directly against a stack whose other services (`postgres` in particular) are already up via `just up`.
- **Frontend change:** `cd services/webapp && npm run dev` for hot-reload against a live backend (proxies `/api/*` to `http://localhost:8001` in dev). `npm run check` runs `svelte-check` — there is no frontend test framework or `test` npm script; type-checking is the only automated frontend check.
- **Ingestion/retrieval change:** `just up`, upload a test document through the webapp or `curl`, then `just test-eval` for a fast 5-sample sanity check before a full `just test-eval-full`.
- **Config-only change:** edit `config.yml`, then `just show-config` to confirm it parsed as expected before restarting affected services.

## Troubleshooting pointers

- **Docker build fails** on the PyTorch CPU wheel: the Dockerfile needs `--index-strategy unsafe-best-match` for `uv`'s PyTorch CPU index resolution — this is already set, but if you're modifying dependency resolution, keep it.
- **Reranker slow on first query:** it downloads its model weights (tens of MB) into the bind-mounted Hugging Face cache on first use unless pre-fetched with `just init`.
- **`task-worker` looks stuck:** check `docker compose logs task-worker` — it auto-restarts, and stuck tasks are reset after an hour by the worker's own claim-timeout logic.
- **Eval-related commands fail with a missing-file error:** you're likely running something by hand against a stale path — use the `just eval*` recipes, which target the current `services/evals` layout.
- **Ollama unreachable at `up`/`deploy`:** `preflight` should catch this before the stack starts, but if you bypass it, uploads will surface a dedicated "Ollama unreachable" error in the webapp; chat queries surface only a generic connection-interrupted error for the same underlying cause.
- **Config change not taking effect:** `config.yml` is bind-mounted read-write into `rag-server`/`task-worker` and read-only into `evals`; most values are picked up via mtime-based auto-reload, but check `configuration-reference.md` for the handful of values that require a restart.
