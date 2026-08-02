# CI/CD and deployment

RAGBench runs its own CI on a self-hosted Forgejo instance, and deploys via Docker Compose
overlays rather than a separate deployment tool. This document covers the CI pipeline as it
actually exists today, the five compose files and what each is for, the deploy and release
recipes, and what operational concerns are simply not addressed anywhere in the repo.

## Forgejo CI pipeline

The pipeline is a single workflow file, `.forgejo/workflows/ci.yml`. Every job in it is always-on;
there is no gated/opt-in job.

**Triggers:**
- `push` on every branch (`branches: ['**']`)
- `pull_request` targeting `main`
- `workflow_dispatch` (manual, no inputs)

**Jobs:**

| Job | Runs when | Container | What it does |
|---|---|---|---|
| `test-rag-server` ("RAG Server Tests") | always | `ghcr.io/astral-sh/uv:python3.13-bookworm-slim` | Checks out the repo, `uv sync` in `services/rag_server`, then `uv run pytest tests/ -v --tb=short`. `tests/integration` self-skips without `--run-integration`. |
| `test-evals` ("Evals Tests") | always | same base image | Checks out the repo, `uv sync` in `services/evals`, then `uv run pytest tests/ -v --tb=short`. Dataset-loader/integration tests marked `eval` self-skip without `--run-eval`. |
| `docker-build` ("Docker Build") | always | — | Builds the `rag-server` and `webapp` Docker images (tagged with the commit SHA) and prints their sizes; does not push either image anywhere |

Forgejo branch protection (which jobs are required to pass before a merge) is configured in the
Forgejo instance itself, not as code in this repository, so it is not visible here. The workflow
file itself does not mark any job `required` — that gating, if it exists, lives entirely in
Forgejo's own server-side settings.

### History: the eval job used to target a path that no longer existed

Previously this workflow had a gated `test-eval` job (`workflow_dispatch` with `run_eval: true`,
or `[eval]` in the commit message) plus stale `--ignore` flags on the core job. Both referenced
`services/rag_server/tests/test_rag_eval.py` and a `--group eval` dependency group, none of which
existed anymore — the eval framework had been extracted into `services/evals/`, and its tests
moved wholesale to `services/evals/tests/`. The job was broken as committed and never actually
ran anything real. The root `Makefile` had the identical stale reference and has since been
deleted (`just` was already a strict superset of its targets).

That job has been **removed**, not repaired — the real end-to-end eval (`just test-eval`) needs
docker compose plus a running rag-server, which a stateless CI runner isn't set up for here.
`services/evals/tests/` is genuinely a hermetic unit-test suite (no API key, no eval run needed)
distinct from that end-to-end path, so it was promoted into the always-on `test-evals` job
instead of staying tied to the removed eval-run job. Two test classes in that suite —
`TestCitationExtraction` and `TestQueryEndpointIncludeChunks` in
`services/evals/tests/test_rag_eval.py` — are skipped with an explicit reason: they import
`pipelines.inference` from `services/rag_server`, which is not installed in the `evals` service's
own virtualenv, so they fail with `ModuleNotFoundError` regardless of any flag. That's a real,
separate defect (tests exercising the wrong service from the wrong service) recorded in
`docs/suggestions.md`, not something this CI fix addressed.

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
