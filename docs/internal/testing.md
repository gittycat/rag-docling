# Testing

RAGBench's test suite spans three tiers — unit, integration, and eval — each with a different
dependency footprint and a different opt-in flag. All three are pytest-based except the eval
tier's day-to-day invocation, which normally runs through the `evals` CLI rather than pytest
directly.

## Categories

### Unit tests

Unit tests live in `services/rag_server/tests/` as flat `test_*.py` files (auth, PII masking,
config, embeddings, LLM factory, chat memory cache, contextual retrieval, worker/task
concurrency, metrics API, privacy posture, API key validation, BM25 query safety, and more).
They run against a local `uv`-managed virtualenv with no Docker services involved; dependencies
are mocked (`mock_models_config`, `reset_config_singleton` fixtures in `tests/conftest.py`).

```bash
just test-unit        # alias: just test
# underlying command:
cd services/rag_server && .venv/bin/pytest tests/ --ignore=tests/integration -v
```

`just setup` (`uv sync --group dev --python 3.13`) must have been run at least once to create the
venv.

### Integration tests

Integration tests live in `services/rag_server/tests/integration/` and exercise the real stack —
Postgres, TEI, and the rag-server HTTP API — through a disposable container that
reuses the `rag-server` service's own image and environment (see "Integration test design"
below). The main compose stack (`just up`) must already be running.

```bash
just test-integration
# underlying command:
docker compose run --rm -e RAG_SERVER_URL=http://rag-server:8001 rag-server \
  .venv/bin/pytest tests/integration -v --run-integration
```

`just test-integration-full` runs the same command with `--run-slow` added, additionally
exercising tests marked `slow` (large-document ingestion, longer polling loops).

### Eval tests

The eval tier measures answer quality rather than code correctness, and its everyday entry point
is the `evals` service's own CLI, not pytest:

```bash
just test-eval         # 5-sample smoke run against the ragbench dataset
# underlying command:
docker compose exec evals .venv/bin/python -m evals.cli eval \
  --tier end_to_end --datasets ragbench --samples 5

just test-eval-full     # all samples, all datasets (ragbench, qasper, hotpotqa, msmarco)
```

`services/evals/tests/` also contains a pytest suite (`test_rag_eval.py`, `test_api.py`,
`test_judge_failures.py`, `test_privacy_posture.py`, `test_config_snapshot.py`) that exercises the
eval framework's own code paths, separately from the CLI-driven smoke runs above. Most of it is
hermetic (no API key, no network) and runs by default; the dataset-loader and integration classes
are marked `eval` and are skipped by default because they download real datasets from HuggingFace
and/or need API keys — there is no `just` recipe for this suite specifically, but it is not a
by-hand-only invocation either: `.forgejo/workflows/ci.yml` runs it (the hermetic subset) on every
push as the `test-evals` job. To run it yourself:

```bash
cd services/evals && uv run pytest tests/ -v            # hermetic subset only
cd services/evals && uv run pytest tests/ --run-eval -v # + dataset-loader/integration tests
```

`TestCitationExtraction` and `TestQueryEndpointIncludeChunks` used to live in
`services/evals/tests/test_rag_eval.py`, skipped because they import `pipelines.inference` from
`services/rag_server`, which is not installed in the evals virtualenv. They now live in
`services/rag_server/tests/test_citation_extraction.py` and run in the `test-rag-server` job
(`docs/suggestions.md` #4.8).

## Pytest markers

`services/rag_server/pyproject.toml` registers three markers, all under `--strict-markers`, and
all skipped by default:

| Marker | Selects | Enabling flag | Default |
|---|---|---|---|
| `integration` | tests requiring Docker services (Postgres, TEI) | `--run-integration` | skipped |
| `slow` | tests taking longer than 30 seconds | `--run-slow` | skipped |
| `eval` | RAG evaluation tests, require an API key for the active eval provider | `--run-eval` (plus optional `--eval-samples=N`) | skipped |

The gating logic lives in `services/rag_server/tests/conftest.py`, which registers the
`--run-integration`, `--run-slow`, `--run-eval`, and `--eval-samples` CLI options and skips the
corresponding tests unless the flag is present. A plain `pytest tests/` run therefore executes
only unmarked unit tests.

`services/evals/pyproject.toml` registers its own `eval` marker (dataset-loader/integration tests
requiring network or API keys), also under `--strict-markers`. The gating logic lives in
`services/evals/tests/conftest.py`, which registers `--run-eval` and skips `eval`-marked tests
unless it's passed — the same pattern as `services/rag_server`, but a separate, smaller
implementation (no `--run-integration`/`--run-slow` equivalent exists on this side).

## Integration test design: no separate test-runner service

Integration tests run inside a disposable container built from the **same service definition as
`rag-server`** (`docker compose run --rm rag-server ...`), not a dedicated `test-runner` service.
The alternative — a parallel compose service just to execute tests — would need to duplicate
rag-server's environment variables, Docker secrets, volume mounts, and network placement by hand,
and every change to rag-server's config would risk drifting out of sync with a second definition
nobody remembers to update. Reusing the `rag-server` service avoids that: the test container gets
the real image, the real secrets mounts, the real `private`/`public` network placement, for free.

The integration `conftest.py` layers two more pieces on top of this:

- A session-scoped `check_services` fixture fails the whole session up front if Postgres, TEI,
  or the rag-server `/health` endpoint aren't reachable. It does more than ping TEI: it also
  reads `/info` and fails if the loaded model is not the expected one, so a stale container
  serving the wrong model is caught up front rather than producing quietly wrong vectors.
  It then drains the task queue (waits up to
  600 seconds for `job_tasks` rows to leave `pending`/`in_progress`) so pre-existing async work
  doesn't interfere with the run.
- When `/run/secrets` exists on disk (i.e. the tests are actually running inside the `rag-server`
  container, as `just test-integration` arranges), the fixtures re-initialize `Settings` from the
  mounted Docker secrets instead of the mock settings unit tests use — this is the mechanism that
  gives integration tests real credentials rather than test doubles.
- The `integration_env` fixture sets integration-specific overrides on top of that — notably
  `ENABLE_CONTEXTUAL_RETRIEVAL=false` (disabled for test speed) alongside
  `ENABLE_HYBRID_SEARCH=true` and `ENABLE_RERANKER=true` — and restores prior environment on
  teardown.

## Fixtures of note

- `sample_pdf`, `corrupted_pdf`, `sample_text_file`, `large_text_file` generate synthetic
  documents on the fly with `fpdf2` — no static fixture files are checked in for these cases.
- `large_public_markdown` and `large_public_pdf` (session-scoped) download real external
  documents over the network (an SDK README, an arXiv paper) for realistic-size testing; both
  `skip` rather than fail if the download fails or the file turns out too small.
- `api_client` is a session-scoped `httpx.Client`; `upload_and_wait` uploads a document and polls
  `/tasks/{batch_id}/status` until it completes; `document_cleanup`/`session_cleanup` collect
  teardown-time deletions; `test_document` composes all of the above into a create-upload-wait-
  yield-delete fixture for an end-to-end round trip.
- `wait_for_task` polls with a 300-second default timeout and tolerates transient 404/500
  responses while workers are still committing progress.
- `reset_config_singleton` (autouse, unit tests) resets the models-config singleton before and
  after every test; `mock_models_config` patches `get_models_config` to a fixed configuration
  (vLLM LLM, TEI embedding, Anthropic eval, reranker enabled) for isolated unit tests.

## `tests/test_bm25_query_safety.py`

There is one BM25 query implementation: `PgSearchBM25Retriever`
(`infrastructure/search/bm25_retriever.py`), wired into hybrid search from
`infrastructure/search/hybrid_retriever.py`, building its SQL with pg_textsearch's
`to_bm25query(...)` function and the `<@>` distance operator.

This file used to assert that the live retriever emitted the SQL shape of a *second*,
uncalled helper (`search_chunks_bm25`, `bm25_search(...)`/`websearch_to_tsquery(...)`) — an
assertion that was false of the running code, so the test was skipped rather than trusted. The
dead helper is gone and the test now asserts against what the live retriever actually emits:
`to_bm25query(:query, 'idx_chunks_bm25')`, with the user's text bound as a parameter and never
interpolated into the SQL string (`docs/suggestions.md` #4.4).

## Import-time side effects

`infrastructure/tasks/task_worker.py` used to call `init_settings()`/`initialize_settings()` at
module scope, which reached the network (an embedding-endpoint reachability probe that
`sys.exit(1)`s on failure — `check_ollama_reachable` then, `check_embedding_endpoint_reachable`
now). Importing it without that endpoint running took down the whole pytest
collection with `INTERNALERROR`/`SystemExit`, and the tests worked around it by patching during
the import. Both calls now happen in `main()`; `test_task_worker_concurrency.py` asserts the
import stays inert (`docs/suggestions.md` #4.9).

## Frontend tests

There is no frontend test framework in `services/webapp`. `package.json` defines only `dev`,
`build`, `preview`, `prepare`, `check`, and `check:watch` scripts — no `test` script, and no
vitest, Playwright, or similar config exists anywhere under `services/webapp`. No `*.test.*` or
`*.spec.*` files exist in `services/webapp/src` either. The only check the frontend has is static
type checking via `svelte-check` (`just`-less: `npm run check` / `npm run check:watch` inside
`services/webapp`), which catches type and template errors but exercises no runtime behavior.
