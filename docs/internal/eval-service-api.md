# Eval service API reference

The eval service is a separate FastAPI application listening on port 8002
(`services/evals/api/app.py`). Every eval route is mounted under the `/eval`
prefix (`services/evals/api/routes.py`, `router = APIRouter(prefix="/eval")`),
plus a bare `GET /health` outside that prefix. From the browser, the webapp's
server-side proxy forwards `/api/eval/*` to `EVALS_SERVICE_URL` (default
`http://localhost:8002`) with the `/api` prefix stripped, so `/api/eval/runs`
in the browser is `/eval/runs` on the service itself.

Unlike rag-server, this service has **no auth dependency anywhere in its
router**. The webapp's proxy also forwards no bearer token on the eval path.
The eval service is reachable unauthenticated end-to-end, on whatever network
the container is attached to.

All shapes below are the Pydantic models in `services/evals/api/schemas.py`,
matched against the handlers in `services/evals/api/routes.py` and the
dashboard-metric derivation in `services/evals/api/dashboard.py`.

## Job manager semantics

Eval runs are managed by a single in-process `JobManager` (`api/job_manager.py`),
constructed once at startup and shared by the whole router via a module-level
reference set in `init_router(jm)`. Its defining constraints:

- **Exactly one active job, process-wide.** `JobManager.trigger()` checks
  `self._active_job_id` and `self._active_status`; if a job is already
  `"queued"` or `"running"`, it raises `RuntimeError`, which the route maps to
  **HTTP 409** ("An eval job is already running"). There is no queueing of a
  second request — it is rejected outright, and the caller must poll and retry
  once the active job finishes.
- **The job itself runs in a background thread**, not in the FastAPI event
  loop: `trigger()` spawns a daemon `threading.Thread` that calls
  `asyncio.run(runner.run(...))` inside a fresh event loop. This means the
  HTTP request that triggers a run returns immediately (202) while the run
  continues independently; progress is polled via `GET /eval/runs/active`.
- **No database.** There is no persistence layer for eval runs beyond flat
  JSON files under `data/eval_runs/` (one file per completed run, written by
  `EvaluationRunner`). `JobManager` keeps an **in-memory index**
  (`self._run_index: dict[run_id, (filepath, data)]`) mapping run IDs to their
  parsed JSON — this is purely a process-local cache, not a source of truth.
- **The in-memory index is rebuilt from disk on every process restart.**
  `JobManager.index_existing_runs()` runs once at startup (from the FastAPI
  `lifespan` context in `app.py`), globs `data/eval_runs/*.json`, parses each
  file, and populates `_run_index`. A run that failed to write its JSON file
  (e.g. the process crashed mid-write) is simply absent from the index after
  restart — there is no separate durable ledger of "runs that were attempted."
  Corrupt JSON files are skipped with a warning, not surfaced as an error.
- **Cancellation** (`DELETE /eval/runs/active`) sets a `threading.Event` that
  the runner is expected to check between questions; it does not forcibly kill
  the background thread. If no job is active, the endpoint returns 404 rather
  than a no-op success.

## Endpoint reference

| Method & path | Purpose | Request | Response | Notable status codes |
|---|---|---|---|---|
| `POST /eval/runs` | Trigger a new eval run | `TriggerRunRequest { name?, tier="generation", datasets=["ragbench"], samples=100, seed=42, judge_enabled=true }` | `JobCreatedResponse { job_id, status="queued", created_at }`, HTTP 202 | **409** if a job is already active; **422** if `tier`/`datasets` don't map to valid enum values (`ValueError` from constructing `EvalTier`/`DatasetName`) |
| `GET /eval/runs/active` | Poll the currently running (or queued) job | none | `ActiveJobResponse { job_id, status, progress: ProgressInfo }` when a job is active, otherwise a bare JSON `null` with HTTP 200 (no `response_model` is declared on this route, so FastAPI does not wrap or validate the `null` case) | — |
| `DELETE /eval/runs/active` | Cancel the running/queued job | none | `{"status": "cancelled"}` | **404** if no job is currently active |
| `GET /eval/runs` | List completed runs, newest first | Query params `limit` (1–100, default 20), `offset` (default 0) | `RunListResponse { runs: list[RunSummary], total }` | — |
| `GET /eval/runs/compare` | Compare 2+ runs and compute deltas | Query param `ids` — comma-separated run IDs, e.g. `?ids=abc123,def456` | `CompareRunsResponse { runs: list[RunDetailResponse], deltas: dict[str, float \| null] }` — deltas are always **second run minus first run** in the `ids` list, for `duration_seconds`, `weighted_score`, and every named scorecard metric present on either run | **422** if fewer than 2 IDs given; **404** if any ID doesn't resolve to an indexed run |
| `GET /eval/runs/{run_id}` | Full detail for one run | Path param `run_id` | `RunDetailResponse` (see below) | **404** if not indexed |
| `GET /eval/dashboard` | Single-call dashboard summary | none | `DashboardResponse { latest_run: RunSummary \| null, total_runs, active_job: ActiveJobResponse \| null }` | — |
| `GET /eval/datasets` | List built-in datasets and their tier support | none | `list[DatasetInfo { name, description, source_url, supported_tiers }]` | — |
| `GET /health` | Liveness check (outside the `/eval` prefix) | none | `{"status": "ok"}` | Always 200 if the process is up |

Route registration order matters for `/eval/runs/compare`: it is declared
before `/eval/runs/{run_id}` specifically so the literal path segment
`compare` isn't captured by the `{run_id}` path parameter. This is a real
ordering dependency in `routes.py`, not incidental.

### `RunSummary` and `RunDetailResponse` shapes

`RunSummary` (used in `GET /eval/runs` and as `latest_run` in the dashboard):
`id`, `name`, `created_at`, `completed_at`, `tier`, `datasets`,
`question_count`, `error_count`, `duration_seconds`, `weighted_score` (bare
float or `null`), `llm_model`, `dashboard_metrics` (`DashboardMetrics | null`),
`retrieval_funnel` (`RetrievalFunnel | null` — the per-stage recall table plus
ceiling, final, the two losses and the bottleneck),
`metrics` (`dict[metric_name, value]` flattened from the scorecard), `groups`
(`dict[group_name, list[metric_name]]`).

`RunDetailResponse` (used in `GET /eval/runs/{id}` and `/eval/runs/compare`)
carries more: `config` (raw `dict` — the `ConfigSnapshot` captured at run
time), `scorecard` (raw `dict`, untyped — the full per-metric breakdown
including `details.individual_scores` and `details.std_dev` per metric),
`weighted_score` (raw `dict`, not just the score — includes `score`,
`weights`, `contributions`, `objectives`), `metadata` (raw `dict` — includes
`tier`, `samples_per_dataset`, `seed`), and the same `dashboard_metrics`.
`scorecard`, `weighted_score`, `config`, and `metadata` are all typed as bare
`dict` on the Pydantic model — FastAPI validates that they're objects, not
their internal keys.

Inside `config`, the three retrieval fields (`retrieval_top_k`,
`hybrid_search_enabled`, `contextual_retrieval_enabled`) are **nullable**:
`null` means the runner could not reach `/metrics/retrieval` when the run
started, so the setting was never captured. Clients must render that as unknown
rather than coercing it to a default — see the eval-framework notes. `config.additional.retrieval`
holds the full endpoint response (`rrf_k`, reranker `top_n`, `final_top_n`) when
it was captured.

`duration_seconds` is computed by `_extract_duration()`: it uses the stored
`duration_seconds` field if present, otherwise falls back to
`completed_at - created_at` from the run's own timestamps; if either timestamp
is missing or unparsable, it is `null`.

### `DashboardMetrics` (nested in both `RunSummary` and `RunDetailResponse`)

Computed by `compute_dashboard_metrics()` in `api/dashboard.py` from the raw
scorecard, not stored separately: `retrieval_ceiling` and `retrieval_final`
(the two ends of the retrieval funnel — recall@5 of the candidate list, and of
what the model actually saw), `retrieval_bottleneck` (`"ingestion"`, `"rerank"`
or `null`). All three are `null` for `tier="generation"` runs, which retrieve
nothing, and for runs whose questions carry no resolvable gold evidence — `null`
rather than `0.0`, which would read as total retrieval failure. Then
`faithfulness`, `answer_completeness`
(from the `answer_correctness` metric), `answer_relevance` (from
`answer_relevancy`), `latency_p50_seconds`/`latency_p95_seconds`/
`latency_avg_seconds` (converted from the scorecard's millisecond values),
`avg_cost_usd`, `total_cost_usd`, `total_prompt_tokens`,
`total_completion_tokens`, `cost_model` (all five pulled from the
`cost_per_query` metric's `details` dict).

## Dashboard endpoint

`GET /eval/dashboard` is a convenience aggregate, not a distinct data source:
it calls the same `get_latest_run()` / `list_runs(limit=1)` / `get_active_job()`
methods on `JobManager` that the other endpoints use individually, and returns
them together as `DashboardResponse { latest_run, total_runs, active_job }`.
There is no separate dashboard-specific state or caching layer — it reads the
same in-memory run index and active-job state as everything else in this
service.

## Response fields the webapp does not consume

The webapp calls this service through `services/webapp/src/lib/api/evals.ts`.
Cross-referencing what it actually reads against the schemas above (see the
exposure-gap table in `.docwork/facts-webapp.md` for the full inventory across
both services), the following eval-service fields and endpoints are returned
by the API today but never read by any component in the webapp:

- `RunSummary.groups` — declared and fetched, never read anywhere in `src/`.
- `DashboardMetrics.answer_completeness` and `.answer_relevance` — never
  referenced client-side at all.
- `DashboardMetrics.total_cost_usd` and `cost_model` — `total_cost_usd` only
  reaches the user via CSV export, never an on-screen panel; `cost_model` is
  never rendered anywhere, so a displayed cost figure carries no on-screen
  indication of which model it was priced against.
- `RunDetailResponse.scorecard.metrics[].details.individual_scores` — the
  full per-question raw score array is passed through the untyped
  `scorecard` dict but no component reads it; there is no distribution or
  per-question drill-down view anywhere in the UI.
- `RunDetailResponse.scorecard.metrics[].details.std_dev` — read for the
  `generation` metric group only; the identical field on retrieval, citation,
  and abstention metrics is present in every response but never displayed.
- `RunDetailResponse.scorecard.metrics[].sample_size` — typed client-side,
  never read.
- `RunDetailResponse.weighted_score.weights`, `.contributions`, and
  `.objectives` — only `.score` is read anywhere; the weighting recipe and
  the per-objective contribution breakdown are returned on every run-detail
  response and never surfaced.
- `RunDetailResponse.metadata.samples_per_dataset` and `.seed` — both typed
  client-side, neither rendered.
- `DatasetInfo.description`, `.source_url`, `.supported_tiers` — the
  `GET /eval/datasets` endpoint itself has no caller anywhere in `src/`.
- `POST /eval/runs` and `DELETE /eval/runs/active` — no component in the
  webapp calls either endpoint; triggering or cancelling a run is only
  possible via direct API calls or the eval CLI.

This is a factual inventory of what the API returns versus what the frontend
reads, not a prioritized backlog — proposed follow-up work for closing these
gaps is tracked in `docs/suggestions.md`.
