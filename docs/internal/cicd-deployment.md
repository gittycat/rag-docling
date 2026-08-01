# CI/CD and deployment

RAGBench runs its own CI on a self-hosted Forgejo instance, and deploys via Docker Compose
overlays rather than a separate deployment tool. This document covers the CI pipeline as it
actually exists today (including a broken job), the five compose files and what each is for, the
deploy and release recipes, and what operational concerns are simply not addressed anywhere in
the repo.

## Forgejo CI pipeline

The pipeline is a single workflow file, `.forgejo/workflows/ci.yml`.

**Triggers:**
- `push` on every branch (`branches: ['**']`)
- `pull_request` targeting `main`
- `workflow_dispatch`, with a boolean `run_eval` input (default `false`)

**Jobs:**

| Job | Runs when | Container | What it does |
|---|---|---|---|
| `test` ("Core Tests") | always | `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` | Checks out the repo, `uv sync` in `services/rag_server`, then `uv run pytest tests/ -v --ignore=tests/evaluation --ignore=tests/test_rag_eval.py --tb=short` |
| `test-eval` ("Evaluation Tests") | `workflow_dispatch` with `run_eval: true`, or a commit message containing `[eval]` | same base image | `uv sync --group eval`, then `uv run pytest tests/test_rag_eval.py --run-eval --eval-samples=5 -v --tb=short`, with `ANTHROPIC_API_KEY` from repo secrets |
| `docker-build` ("Docker Build") | always | — | Builds the `rag-server` and `webapp` Docker images (tagged with the commit SHA) and prints their sizes; does not push either image anywhere |

Forgejo branch protection (which jobs are required to pass before a merge) is configured in the
Forgejo instance itself, not as code in this repository, so it is not visible here. The workflow
file itself does not mark any job `required` — that gating, if it exists, lives entirely in
Forgejo's own server-side settings.

### Known breakage: the eval job targets a path that no longer exists

The `test-eval` job and the core `test` job's `--ignore` flags both assume the eval tests still
live under `services/rag_server/tests/`. They don't anymore — the eval framework was extracted
into its own service, and its tests now live at `services/evals/tests/test_rag_eval.py`. As a
result:

- The core `test` job's `--ignore=tests/evaluation --ignore=tests/test_rag_eval.py` flags are
  no-ops: neither path exists under `services/rag_server/tests` today, so nothing is actually
  being excluded.
- The `test-eval` job runs `uv sync --group eval` inside `services/rag_server`, but that
  dependency group no longer exists in `services/rag_server/pyproject.toml` (only `dev` and
  `bench` remain there) — this step is expected to fail.
- Even if dependency sync somehow succeeded, the job's `pytest tests/test_rag_eval.py` target
  does not exist under `services/rag_server/tests` — it was moved wholesale to
  `services/evals/tests/`.

The `Makefile` has the identical stale reference (`test-eval`/`test-eval-full` targets
`services/rag_server/tests/test_rag_eval.py`, and `test-unit` carries the same dead `--ignore`
flags), so this isn't unique to CI — both were written against the pre-extraction layout and
never updated.

**This job is broken as currently committed.** Treat "Evaluation Tests" in Forgejo as
non-functional until the workflow is repointed at `services/evals` and given that service's own
sync/test invocation; don't rely on a green run of this job for anything.

There is also no CI job that builds or tests the `evals` service itself, and no image-push step
anywhere in `.forgejo/` — `docker-build` verifies that the `rag-server` and `webapp` images still
build, nothing more.

## Compose environments

Five compose files exist. The base file plus `.cloud.yml` and `.server.yml` are overlays, applied
together with `docker compose -f docker-compose.yml -f docker-compose.<tier>.yml` (or `just
deploy <tier>`). `.bench.yml` and `.ci.yml` are **standalone stacks** — neither is ever combined
with the base file, and each defines its own complete, self-contained set of services and
networks.

| File | Kind | Purpose |
|---|---|---|
| `docker-compose.yml` | base | The full local/dev stack: `webapp`, `rag-server`, `postgres`, `chromadb`, `task-worker`, `evals`. Everything runs on a `public` bridge network plus a `private` bridge network that is `internal: true` (no gateway, no internet access) — Postgres and ChromaDB sit only on `private`. |
| `docker-compose.bench.yml` | standalone | An ephemeral benchmark stack (`postgres-bench` on `tmpfs`, `rag-server-bench` on host port 8003, `task-worker-bench`), on its own `bench-public`/`bench-private` networks and its own volume names, so a benchmark run never touches dev data. There is no `just` recipe for it — bring it up with `docker compose -f docker-compose.bench.yml up -d` and down with the matching `down`. Everything in it is meant to be thrown away. |
| `docker-compose.ci.yml` | standalone | Forgejo (git host + CI web UI, port 3000, plus SSH on 222) and `forgejo-runner` (mounts the host Docker socket to execute CI jobs, runs as root). Its network is a plain bridge, not isolated. Long-lived infrastructure, independent of the application stack's lifecycle. |
| `docker-compose.cloud.yml` | overlay | Replaces local `build:` with `image:` for `webapp`, `rag-server`, and `task-worker` (pulling `<service>:${VERSION:-latest}` from a registry) so a cloud host runs pre-built images instead of building on the target machine. Also templates `OLLAMA_HOST` into `extra_hosts` so Ollama can run on a separate host. |
| `docker-compose.server.yml` | overlay | Adds a Caddy reverse proxy (TLS termination, `tls internal` self-signed by default, or a real domain via `SERVER_DOMAIN` for automatic Let's Encrypt) and removes direct host port publishing from `webapp`, `rag-server`, and `evals` — only Caddy publishes ports. Adds bearer-token auth (`RAG_SERVER_AUTH_TOKEN`, delivered as a Docker secret) required by clients reaching the server over a network rather than localhost. |

Pushing images to a registry has no `just` recipe. The cloud overlay expects images to already
exist in a registry, but building and publishing them is a manual step today.

Do not look for a `docker-compose.override.yml` — it does not exist in this repository and has
no history in it either. Any documentation that claims it does is stale.

## Deploy recipes

Deployment is `just deploy <env>`, which runs the base file plus the named overlay:

```bash
just deploy server   # docker compose -f docker-compose.yml -f docker-compose.server.yml up -d --build
just deploy cloud    # docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d --build
just deploy-down server   # tear down the same overlay combination
```

`just deploy` runs `preflight` first (checks the Docker daemon is reachable, and conditionally
checks Ollama reachability if `config.yml`'s active model points at it).

## Versioning and release

There is no tag-triggered build or publish pipeline — pushing a `v*` tag does nothing in Forgejo
CI, because `ci.yml` has no `on: push: tags:` trigger. Cutting a release is a single manual local
command:

```bash
just release VERSION
```

This creates an annotated git tag `v<VERSION>`, bumps the version in
`services/rag_server/pyproject.toml` (via `sed`) and `services/webapp/package.json` (via `npm
version`), commits both bumps, and pushes `origin main` along with the tag. Nothing downstream
reacts to that push automatically — building and publishing an image for a given version is a
separate, manual step — no recipe exists for building and publishing a versioned image.

## Not covered

Two things are conspicuously absent anywhere in this repository's compose files, CI workflow, or
justfile:

- **Backups.** No volume-backup mechanism exists for any of the named Docker volumes —
  `postgres_data` (all application state: documents metadata, chat sessions, the task queue),
  `chroma_data` (the vector index), or `forgejo_data` (the entire self-hosted git host: repos,
  users, PRs, Actions run history). There is no `pg_dump` script, no snapshot job, no backup
  service defined in any compose file. If any of these named volumes is lost, its contents are
  gone; the only data that survives independently of Docker volumes is what lives in host bind
  mounts (`data/indexed_documents`, `data/eval_runs`, `config.yml`, the HuggingFace/dataset
  caches), and only because those happen to be bind mounts rather than named volumes, not because
  of any deliberate backup design.
- **Resource limits.** No service in any of the five compose files sets `deploy.resources` or any
  cpu/memory limit. Every container — including the ones with host-facing ports — can consume
  unbounded host resources.

Neither gap is flagged or worked around anywhere else in the codebase; both are simply
unaddressed as of this writing.
