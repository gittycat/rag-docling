# Observability

RAGBench's observability surface is deliberately thin: two trivial liveness
endpoints, a richer metrics endpoint that actually probes dependencies,
in-memory cost/latency trackers with no persistence, and unstructured text
logging to stdout. There is no external log aggregation, no tracing, and (see
"Logging" below) no way to correlate log lines across a single request.

## Health endpoints

| Endpoint | Service | Checks |
|---|---|---|
| `GET /health` | rag-server | Nothing — returns `{"status": "healthy"}` unconditionally, no dependency checks. |
| `GET /health` | evals | Nothing — returns `{"status": "ok"}` unconditionally, no dependency checks. |

Both are trivial liveness probes: they confirm the process is up and serving
HTTP, not that its dependencies (Postgres, Ollama) are reachable.
Docker's own healthchecks for `rag-server` and `evals` poll exactly these
endpoints (via a Python `urllib` one-liner), so the Docker-level "healthy"
status inherits the same limitation — it verifies the uvicorn process
responds, nothing more. The `postgres` service's Docker healthcheck is the
one real dependency check in the stack: it runs `pg_isready` against the
actual database. `webapp` and `task-worker` have no Docker healthcheck defined
at all.

Real component health lives elsewhere: `GET /metrics/system` (below) actually
issues a `SELECT 1` against Postgres, a BM25 probe query against
`idx_chunks_bm25`, a vector probe against `idx_chunks_embedding`, and a
`GET /api/tags` against Ollama, and reports both an
overall `health_status` (`"healthy"` / `"degraded"`) and a per-component
`component_status` dict. If you need to know whether the system is actually
working, use `/metrics/system`, not `/health`.

The `bm25` component is present only when hybrid search is enabled. It is
`unavailable` when the probe itself fails (missing `pg_textsearch` extension,
dropped index, permissions) and `unhealthy` when the probe succeeds but the
most recent real retrieval failed — BM25 errors never fail a query, they
silently degrade it to vector-only, so this key is the only signal short of
reading logs (`docs/suggestions.md` #4.5).

`vector_store` is the mirror image on the dense side, on the same three-valued
scale, and is always present: with hybrid search off the vector leg is the only
retriever there is. Its probe checks that `idx_chunks_embedding` exists in
`pg_class` and then runs a `<=>` ordering against a probe vector built at
`vector_store.dimension`, so a missing `vector`/`vectorscale` extension, a
dropped diskann index, or a dimension mismatch between `config.yml` and the
column all land as `unavailable`. The index-existence check is not redundant: a
dropped diskann index does not error, it silently turns every vector query into
a sequential scan.

## Metrics API surface

All under `services/rag_server/api/routes/metrics.py`:

| Route | Returns |
|---|---|
| `GET /metrics/system` | Model config, retrieval config, `document_count`, `chunk_count`, `health_status`, and `component_status` (`postgres`, `bm25`, `vector_store`, `ollama`) — the one endpoint that actually checks dependencies, described above. |
| `GET /metrics/models` | Per-model detail (LLM, embedding, reranker, eval): name, provider, parameter count, disk size (queried live from Ollama where applicable), context window, a reference URL, and a load/availability status. |
| `GET /metrics/retrieval` | Current retrieval configuration: hybrid search (BM25 + vector + RRF) on/off, contextual retrieval on/off, reranker enabled/model/`top_n`, `top_k`. |

A module docstring in `metrics.py` says evaluation-specific endpoints "moved
to `/metrics/eval/*`" and points at `api/routes/eval.py` for eval runs,
baselines, comparisons, and recommendations. **That file does not exist** in
`services/rag_server/api/routes/` — eval now lives entirely in the separate
`evals` service (port 8002, see `eval-service-api.md`). The docstring is
stale.

Two more endpoints live in `api/routes/health.py` rather than `metrics.py`:
`GET /models/info` (current LLM/embedding/reranker model, hosting type, and
cost-per-1M-token rates — see "Cost tracker" below for where those rates come
from) and `GET /config` (currently just `max_upload_size_mb`, read from the
`MAX_UPLOAD_SIZE` env var).

## Cost tracker

`services/rag_server/services/cost_tracker.py` tracks token usage and
estimates USD cost for a run. `CostTracker` is a plain dataclass:
`track_query(input_tokens, output_tokens)` accumulates running totals and a
per-query list; `get_metrics(model_name)` returns total input/output/overall
tokens, `estimated_cost_usd`, and `cost_per_query_usd`; `reset()` clears all
of it. State is **in-memory only** — there is no persistence layer backing
the tracker, so counts reset whenever the process restarts.

Pricing comes from a hardcoded per-1M-token lookup table, `TOKEN_PRICING`,
matched by exact model name first and then by prefix (so `gemma3:4b`
normalizes to `gemma3` and matches the Ollama entry). Unknown models fall
back to a conservative `DEFAULT_PRICING` of `{"input": 1.00, "output": 3.00}`
per 1M tokens.

### Two independent, drifting pricing tables

There are **two separate hardcoded pricing tables in the codebase**, neither
sourced from `config.yml` or an external pricing feed, and they do not agree:

- `services/rag_server/services/cost_tracker.py` — `TOKEN_PRICING`, keyed by
  model-name prefix (e.g. `claude-3-5-sonnet`, `gpt-4o`, `deepseek-chat`),
  covering OpenAI, Anthropic, Google, DeepSeek, Moonshot, and zero-cost Ollama
  entries.
- `services/rag_server/api/routes/health.py` — an inline `MODEL_COSTS` dict
  used only by `GET /models/info`, keyed by exact model name (e.g.
  `claude-3-5-sonnet-20241022`) rather than prefix, with a different model
  roster (no Ollama entries at all) and at least one differing rate
  (`deepseek-chat` is `{0.27, 1.10}` here vs `{0.14, 0.28}` in
  `cost_tracker.py`).

A third, also-independent table exists in the `evals` service
(`services/evals/evals/config.py` — `MODEL_COSTS`/`EMBEDDING_COSTS`, used for
eval cost scoring) with yet another set of values for overlapping models.
None of the three tables import from or validate against each other. An
operator relying on the cost figures from one endpoint should not assume they
match what another part of the system reports for the same model.

## Latency tracker

`services/rag_server/services/latency_tracker.py` — `LatencyTracker` is a
plain dataclass that appends each call's `record(latency_ms)` to an in-memory
list (no persistence, cleared on `reset()` or process restart) and computes,
via `get_metrics()`: `avg`, `p50`, `p95`, `min`, `max`, and `total_queries`.
Percentiles are computed by simple index lookup into the sorted list
(`int(n * 0.50)`, `min(int(n * 0.95), n - 1)`), not by interpolation — with
small sample counts this can be noticeably coarser than an interpolated
percentile. There is no measured latency figure checked into the repo for
this tracker to report as a baseline; none is supplied here.

## Logging

Configured centrally for rag-server in `services/rag_server/core/logging.py`
(`configure_logging()`), called once at startup:

- **Level**: from the `LOG_LEVEL` env var, default `INFO`.
- **Format**: `'%(name)s - %(levelname)s - %(message)s'` — no timestamp. A
  `TimestampRemovalFilter` class exists in the same file but its `filter()`
  method unconditionally returns `True` and does nothing; it's vestigial
  (the format string never included `asctime` in the first place, so there
  was nothing for it to strip).
- **Third-party noise reduction**: a `URLShortenerFilter` collapses long URLs
  in `httpx`/`httpcore`/`uvicorn`/`celery` log lines; `httpx`, `httpcore`,
  `filelock`, `urllib3`, and `bm25s` loggers are set to `WARNING`; a
  `HealthCheckFilter` drops any `uvicorn.access` line containing `/health` so
  healthcheck polling doesn't spam the logs.
- **Where logs go**: stdout only, via standard Python logging handlers.
  Docker's default log driver captures them; `docker compose logs -f` (or
  `just logs`) is the only way to view them. There is no file handler, no log
  shipping, and no external log aggregation configured anywhere in the
  compose files.
- **Duplication across services**: the `evals` service does not import
  rag-server's `core/logging.py` — it has its own near-duplicate setup
  inline (own `_HealthCheckFilter`, own `logging.basicConfig` call with the
  same format string, own `LOG_LEVEL` read) in `services/evals/api/app.py`.

The one exception to "no structured logging" is the PII audit logger
(`infrastructure/pii/audit.py`), which emits JSON with an explicit ISO-8601
timestamp field to a dedicated `pii.audit` logger name — see `pii-masking.md`
for what it records. It is unrelated to request tracing; it logs
mask/unmask/leak-detection events, not request lifecycles.

### No request/correlation ID anywhere

There is **no request ID, correlation ID, or trace ID mechanism anywhere in
either service.** Nothing generates one, threads it through a request's
logging calls, or forwards it across the webapp → rag-server → task-worker /
evals boundary. Log lines are unstructured text with no shared key to join
on. In practice this means: given a single user-visible request (a chat
query, a document upload), there is no reliable way to pull together every
log line it produced across processes — the only recourse is inspecting
message content and timestamps by hand across each service's separate log
stream, which does not scale past a handful of concurrent requests.

## Recommendations (not currently implemented)

- Reconcile the pricing tables (`cost_tracker.py`, `health.py`,
  `evals/config.py`) into a single source of truth, or source them from a
  config file / pricing feed instead of three hand-maintained Python dicts.
- Add a request/correlation ID generated at the edge (webapp or rag-server
  ingress) and threaded through logging calls and any outbound calls to
  task-worker/evals, so a single request's log lines can be joined across
  services.
- Fix or remove the stale `/metrics/eval/*` docstring in `metrics.py`.
