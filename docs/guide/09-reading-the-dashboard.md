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
- **Weighted score breakdown** — the objectives behind the headline number: each
  objective's configured weight, its effective share after weights for
  objectives with no data are redistributed, its score, its contribution, and
  that contribution as a share of the total. Objectives the run produced no data
  for are listed underneath.
- **Metric breakdown** — the full per-group metric list (retrieval,
  generation, citation, abstention), each metric shown as a percentage with a
  threshold band (shape plus color) and, where present, `± std_dev` and the
  sample size `n`. Metrics that carry per-question scores get a **dist** toggle
  that expands a histogram of those scores with min/p25/median/p75/max — an
  average of 0.7 from every question scoring 0.7 looks different here from one
  where half score 1.0 and half score 0.4.

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
- **Config diff** — one column per selected run, baseline A first. Cells that
  differ from A are marked with `~` and highlighted; settings the runner never
  captured render as `Unknown` and are never reported as a change. Unchanged
  settings are hidden by default.
- **Export** — the currently selected runs (and the comparison result) can be
  exported as CSV or JSON. The JSON export is the one place where fields the
  on-screen panels drop — like `total_cost_usd`, `cost_model`, per-run
  `dashboard_metrics` — do reach you, since it dumps the full API response
  objects verbatim.
- **Run evaluation panel** — starts and cancels runs from the UI; see
  [chapter 5](05-running-evals.md#from-the-dashboard). When no runs exist yet,
  the tab's empty state points at this panel.

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

- **No significance testing.** The comparison table shows deltas and the metric
  breakdown shows variance, but nothing tells you whether a difference between
  two runs is larger than the noise. That judgement is still yours to make from
  the std dev and the per-question distributions.
- **No stage-level latency.** The eval harness times one span around the whole
  query, so there is no retrieval-vs-generation breakdown to draw.
- **No search or filtering in the run selector** — you scroll a list of the 50
  most recent runs.
- Other things fetched by the API but never surfaced anywhere in the webapp:
  the run's `metadata.seed` (reproducibility info), and the descriptive fields
  on the System tab's models and pipeline objects (`reference_url`,
  `description`, `pipeline_description`, the `evaluation_metrics` glossary).

## When to drop to the CLI

Use the `evals` CLI (via `docker compose exec evals ...`, or the `just eval*`
recipes) rather than the dashboard whenever you need to:

- **Run a tier, dataset mix, or judge setting the panel does not expose**, or
  script a sweep of runs: `just eval --tier <tier> --datasets <names> --samples <n>`,
  or the shorthand recipes `just test-eval` / `just test-eval-full`.
- **Run against a YAML config file** (`--config`) — the dashboard form only
  covers the flags listed in chapter 5.
- **Inspect an individual question's response**, not just the score
  distribution: read the run JSON in `data/eval_runs`.
- **Diff runs that are not in the 50 most recent**, or filter by dataset/tier —
  the run selector has neither.
- **Compare more than two runs' configuration.** `just eval-compare <run_id> <run_id>`
  works pairwise; for three-plus runs, fetch each run's `config` object via the
  API and diff them yourself — the dashboard's config diff is hardcoded to
  baseline-vs-second-selection.
- **Calibrate the judge**, list datasets, or do anything else under
  `evals.cli` — none of this is dashboard-reachable; `just eval-datasets`,
  `just eval-calibrate`, etc. are CLI-only.
