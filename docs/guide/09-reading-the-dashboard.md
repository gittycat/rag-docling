# Reading the dashboard

The dashboard is the Analytics page in the web UI. It is a read-only window onto
eval runs and live system state — it can show you what's already been measured,
but as you'll see below, it cannot trigger new measurement itself.

## Getting there

Open **http://localhost:8000/analytics**. The page has three tabs — **Health**,
**Experiments**, **System** — selected via a `?tab=` query parameter (older tab
names `overview`, `scorecard`, `trends`, `compare` still redirect to the current
two that absorbed them, `health`/`experiments`, if you have an old bookmark).

The page loads `GET /api/metrics/system` and `GET /api/eval/dashboard` on open,
and separately polls `GET /api/eval/runs/active` every 5 seconds regardless of
which tab is showing, to drive the live-job indicator in the header. If
auto-refresh is enabled, all three refresh again every 30 seconds. The very
first load shows a full-page spinner; after that, background refreshes are
silent — if a background refresh fails, the page just keeps showing the last
values it had, with no visible indication that the data may be stale.

The sticky header above the tabs (system name/version, a health dot, document
and chunk counts, the two most recent runs' score badges, and the live-job strip
when a run is in progress) is common to all three tabs.

## Health tab

This is the default landing tab. It fetches the two most recent eval runs (for
delta comparison) and the full detail of the latest one.

- **Weakest-link verdict banner** — a short sentence rolling up the run's
  weakest metric across groups. This is computed client-side from the run's
  metric list; it is not a single field the API returns.
- **Weighted score** stat panel — the run's overall `weighted_score.score`,
  with a delta against the previous run's `weighted_score`.
- **Retrieval** / **Generation** stat panels — each shows the single *weakest*
  metric within that group, not a named headline metric. If the run's tier is
  `generation` (no retrieval performed), the Retrieval panel reads "n/a
  (generation tier)" instead of a number.
- **Cost / query** stat panel — the run's average per-query cost in USD, with a
  delta against the previous run.
- **Latency p95** stat panel — the 95th-percentile end-to-end query latency for
  the run, with a delta against the previous run.
- **Config under test** chip strip (`ConfigContext`) — a compact summary of what
  was actually running for this eval: LLM, embedding model, reranker model (only
  shown if the reranker was enabled), retrieval `top_k`, whether hybrid search
  was on (with the RRF `k` value appended if so), whether contextual retrieval
  was on, and chunk size/overlap. Each field prefers the run's own recorded
  config and falls back to live system config only if the run didn't record
  that field.
- **Latency panel** — three bars (p50, average, p95 latency), all in seconds,
  also printed as text below the chart. This is explicitly a single end-to-end
  number per query, not a retrieval-vs-generation breakdown: the eval harness
  only times one `perf_counter` span around the whole query, so there is no
  stage-level timing data to draw a waterfall from.
- **Metric breakdown** — the full per-group metric list (retrieval,
  generation, citation, abstention), each metric shown as a percentage with a
  threshold-tinted color. For the **generation** group only, a metric also
  shows a `± std_dev` figure next to its value, when that field is present. See
  "What the dashboard cannot do today" below for why the other three groups
  never show this.

## Experiments tab

This combines a trend view and a run-comparison view.

- **Metric history sparklines** — five small trend charts (weighted score,
  faithfulness, answer correctness, latency p95, average cost) plotted across
  the most recent eval runs, oldest to newest. This strip is independent of
  anything selected below it — it always shows all recent runs regardless of
  which ones you've checked for comparison.
- **Run selector** — a checklist of up to 50 recent runs, each with a run name,
  model, run date, and a score badge. You can select up to 4 runs at once.
  There is no search box, dataset filter, or tier filter — you scroll the list.
- **Comparison table** — for the runs you've selected, a table grouped by
  headline → retrieval → generation → citation → abstention → cost/speed, each
  cell showing the raw metric value plus a colored delta against a baseline.
  The oldest of your selected runs is always treated as baseline "A" —
  everything else is shown as a delta from A, regardless of the order you
  clicked runs in. A "hide unchanged rows" checkbox filters out rows where every
  selected run is within a small threshold of A.
- **Config diff** — a git-style +/-/~ line diff of run configuration. This
  compares exactly two runs: baseline A against the second run you selected
  ("B"). If you've selected 3 or 4 runs, the extra runs (C, D) appear as
  additional columns in the comparison table above, but they get **no config
  diff at all** — there is no way, from this UI, to diff A against C or D, or
  B against C.
- **Export** — the currently selected runs (and the comparison result) can be
  exported as CSV or JSON. The JSON export is the one place where fields the
  on-screen panels drop — like `total_cost_usd`, `cost_model`, per-run
  `dashboard_metrics` — do reach you, since it dumps the full API response
  objects verbatim.
- The tab's own empty state, when no runs exist yet, tells you directly how to
  produce one: *"run an evaluation to compare configurations. Trigger one via
  `POST /api/eval/runs` or the evals CLI."* — this is the dashboard admitting,
  in its own copy, that it has no button to do this itself.

## System tab

This tab reads only `GET /api/metrics/system` — no eval-service call.

- **Component status** — one row per backend dependency (postgres, ollama),
  each with a status dot and badge, drawn from the same `component_status`
  object that also feeds the header's overall health dot.
- **Models table** — one row per configured model role (LLM, embedding,
  reranker if enabled, eval judge if configured): model name, provider,
  parameter count, disk size, and load status. The API also returns a
  `reference_url` and a `description` for every model in this table, but
  neither is rendered anywhere — there's no link-out to model documentation
  from this page.
- **Index statistics tiles** — total document count, total chunk count, the
  configured retrieval `top_k`, and the final post-rerank `top_n`.

A number of fields the API already returns for this tab are simply never drawn
anywhere in the System tab or elsewhere in the app: the descriptive/research-note
fields on hybrid search, contextual retrieval, and the reranker (e.g.
`hybrid_search.description`, `contextual_retrieval.research_reference`,
`reranker.description`), the one-line `pipeline_description` string, the full
`evaluation_metrics` glossary (name/category/description/threshold/
interpretation/reference URL per known metric), and the server's own response
`timestamp` (the header instead shows your browser's local clock).

## What the dashboard cannot do today

Be aware of these limits before you go looking for a control that isn't there:

- **No way to start an eval run from the UI.** `POST /eval/runs` has no caller
  anywhere in the webapp. You must use the CLI (`just eval ...`) or call the
  eval service's API directly.
- **No way to cancel a running eval from the UI**, even though the header shows
  a live progress indicator while one is running. `DELETE /eval/runs/active`
  exists on the API but nothing in the webapp calls it. Cancelling requires a
  direct API call.
- **`std_dev` is only ever shown for generation-group metrics.** The backend
  attaches the same `std_dev` field to retrieval, citation, and abstention
  metrics too, but the component that renders the metric breakdown only reads
  it for the generation group — for the other three groups the field is
  fetched and silently dropped. If you need variance for a retrieval or
  citation metric, read the run's raw JSON (or the API response) instead of
  the dashboard.
- **The weighted score's contributing weights are never displayed.** The API
  computes a full breakdown — `weighted_score.weights`, `.objectives`, and
  `.contributions` (how much each objective moved the final number) — but only
  the final `.score` is ever read client-side. If you need to understand *why*
  a weighted score changed between two runs, the dashboard cannot tell you;
  you need to pull the run detail via the API/CLI and read the weighted-score
  object yourself.
- **Config diff only ever compares baseline A against run B**, even when you
  have 3 or 4 runs selected in the comparison view. The metrics table itself
  does show all selected runs side by side, so numeric comparison across more
  than two runs works — only the git-style config diff is limited to the
  first pair.
- Other things fetched by the API but never surfaced anywhere in the webapp,
  worth knowing about if you go looking for them and can't find them: per-run
  `sample_size` per metric (you can't tell from the UI whether a metric is
  based on 5 questions or 500), the run's `metadata.seed` (reproducibility
  info), per-question `individual_scores` (no distribution/drill-down view of
  a single question's result), and dataset descriptions from
  `GET /eval/datasets` (the endpoint exists but nothing in the webapp calls
  it).

## When to drop to the CLI

Use the `evals` CLI (via `docker compose exec evals ...`, or the `just eval*`
recipes) rather than the dashboard whenever you need to:

- **Start a new eval run.** `just eval --tier <tier> --datasets <names> --samples <n>`,
  or the shorthand recipes `just test-eval` / `just test-eval-full`. There is
  no dashboard button for this.
- **Cancel a stuck or wrong run.** Call `DELETE /eval/runs/active` on the eval
  service directly (`curl -X DELETE http://localhost:8002/eval/runs/active`) —
  the dashboard has no cancel affordance even while showing the run as active.
- **Understand why a weighted score moved.** Pull the run detail
  (`GET /eval/runs/{id}` on the eval service, or `just eval-compare <id> <id>`)
  and read `weighted_score.contributions`/`.weights` directly — the dashboard
  never shows this breakdown.
- **Inspect per-question results or variance for anything outside the
  generation group.** The dashboard's aggregate percentages hide both
  `individual_scores` and (for non-generation groups) `std_dev`; the raw JSON
  or API response has both.
- **Compare more than two runs' configuration.** `just eval-compare <run_id> <run_id>`
  works pairwise; for three-plus runs, fetch each run's `config` object via the
  API and diff them yourself — the dashboard's config diff is hardcoded to
  baseline-vs-second-selection.
- **Calibrate the judge**, list datasets, or do anything else under
  `evals.cli` — none of this is dashboard-reachable; `just eval-datasets`,
  `just eval-calibrate`, etc. are CLI-only.
