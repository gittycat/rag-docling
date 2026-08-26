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
HTTP, not that its dependencies (Postgres, TEI) are reachable.
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
`GET /health` against the TEI embedding service, and reports both an
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
| `GET /metrics/system` | Model config, retrieval config, `document_count`, `chunk_count`, `health_status`, and `component_status` (`postgres`, `bm25`, `vector_store`, `tei`) — the one endpoint that actually checks dependencies, described above. |
| `GET /metrics/models` | Per-model detail (LLM, embedding, reranker, eval): name, provider, parameter count, disk size (read live from TEI's `/info` for the embedding model), context window, a reference URL, and a load/availability status. |
| `GET /metrics/retrieval` | Current retrieval configuration: hybrid search (BM25 + vector + RRF) on/off, contextual retrieval on/off, reranker enabled/model/`top_n`, `top_k`. |

A module docstring in `metrics.py` says evaluation-specific endpoints "moved
to `/metrics/eval/*`" and points at `api/routes/eval.py` for eval runs,
baselines, comparisons, and recommendations. **That file does not exist** in
`services/rag_server/api/routes/` — eval now lives entirely in the separate
`evals` service (port 8002, see `eval-service-api.md`). The docstring is
stale.

Two more endpoints live in `api/routes/health.py` rather than `metrics.py`:
`GET /models/info` (current LLM/embedding/reranker model, hosting type, and
cost-per-1M-token rates — see "Pricing" below for where those rates come
from) and `GET /config` (currently just `max_upload_size_mb`, read from the
`MAX_UPLOAD_SIZE` env var).

## Pricing

Per-1M-token rates live in one module per service: `services/evals/evals/pricing.py`
and `services/rag_server/services/pricing.py`. The services share no Python package,
so the rate table and its matching logic are duplicated the same way `LLMProvider`
is. rag-server carries only the resolution half (`resolve_rates` and its helpers);
the eval service adds the cost-computation functions on top.

The rate tables are kept identical by hand and currently agree — same rates for every
shared model, with one legacy `gpt-3.5-turbo` entry only rag-server still carries.
This replaced three independent tables (`cost_tracker.py`, an inline dict in
`health.py`, and `evals/config.py`) that had drifted to different values for the same
models. A divergence check belongs in CI; there is not one yet.

`resolve_rates(model, input_per_1m=None, output_per_1m=None)` returns a `ModelRates`
with a `source` of `"table"` (matched the static roster), `"injected"` (rates passed
by the caller), or `None` when the model is **unpriced**.

Unpriced is a real state, not zero. An open-weight model served from vLLM has an HF
repo id (`Qwen/Qwen3-32B-AWQ`) that matches no static entry, and reporting it as
free would make self-hosting win any cost comparison by default. Unpriced models are
excluded from cost scoring and surface as `null` with `cost_rate_source: "unpriced"`
on `GET /models/info`.

To price a self-hosted endpoint, inject the amortized rate — GPU instance price
divided by measured throughput — via the `cost_per_1m_input_tokens` /
`cost_per_1m_output_tokens` overrides that the eval runner already plumbs through.
A rate of zero must be declared explicitly (as the TEI embedder is in
`EMBEDDING_COSTS`); it is never inferred from a missing entry.

Judge tokens count. `CostPerQuery` attributes generation and judge usage separately;
an eval run's judge calls are usually where the token volume actually sits.

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

- Add a request/correlation ID generated at the edge (webapp or rag-server
  ingress) and threaded through logging calls and any outbound calls to
  task-worker/evals, so a single request's log lines can be joined across
  services.
- Fix or remove the stale `/metrics/eval/*` docstring in `metrics.py`.
