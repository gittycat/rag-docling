# 9. Reading the dashboard

The Analytics page is a read-only window onto eval runs and live system state, plus
one control: you can start and cancel runs from it.

Open **http://localhost:8000/analytics**. Three tabs — **Health**, **Experiments**,
**System** — selected via `?tab=`. Older names (`overview`, `scorecard`, `trends`,
`compare`) redirect to `health` or `experiments`.

**Refresh behaviour.** The page loads `GET /api/metrics/system` and
`GET /api/eval/dashboard` on open, and polls `GET /api/eval/runs/active` every 5
seconds regardless of tab to drive the live-job indicator. With auto-refresh on,
all three refresh every 30 seconds. The first load shows a spinner; after that
background refreshes are silent — **a failed background refresh leaves the last
values on screen with no indication they are stale.**

A sticky header spans all tabs: system name and version, health dot, document and
chunk counts, the two most recent runs' score badges, and the live-job strip.

---

## Health tab

The default landing tab. Fetches the two most recent runs (for deltas) and full
detail of the latest.

| Panel | Shows |
|---|---|
| **Weakest-link verdict** | A sentence rolling up the run's weakest metric across groups. Computed client-side, not an API field. |
| **Weighted score** | `weighted_score.score`, with a delta against the previous run |
| **Retrieval** / **Generation** | The single *weakest* metric in that group — not a named headline metric. On a `generation`-tier run the Retrieval panel reads "n/a (generation tier)". |
| **Cost / query** | Average per-query cost in USD, with a delta |
| **Latency p95** | 95th-percentile end-to-end query latency, with a delta |
| **Config under test** | LLM, embedding model, reranker (only if enabled), `top_k`, hybrid search (with RRF `k` appended), contextual retrieval, chunk size/overlap. Prefers the run's own recorded config, falling back to live system config only where the run recorded nothing. |
| **Latency panel** | Three bars — p50, average, p95 — in seconds, also printed as text. One end-to-end number per query; there is no retrieval-vs-generation breakdown, because the harness times a single span around the whole query. |
| **Weighted score breakdown** | Per objective: configured weight, effective share after redistribution, score, contribution, and contribution as a share of total. Objectives with no data are listed underneath. |
| **Metric breakdown** | Full per-group metric list (retrieval, generation, citation, abstention), each as a percentage with a threshold band (shape plus colour), `± std_dev` where present, and sample size `n`. Metrics carrying per-question scores get a **dist** toggle expanding a histogram with min/p25/median/p75/max. |

That histogram earns its place: an average of 0.7 where every question scored 0.7
looks nothing like one where half scored 1.0 and half scored 0.4.

---

## Experiments tab

Combines trends, comparison, and run control.

| Panel | Shows |
|---|---|
| **Metric history sparklines** | Five trend charts (weighted score, faithfulness, answer correctness, latency p95, average cost) across recent runs, oldest to newest. Independent of your selection below — always all recent runs. |
| **Run selector** | Checklist of up to 50 recent runs with name, model, date, score badge. Select up to 4. No search box, no dataset or tier filter — you scroll. |
| **Comparison table** | Grouped headline → retrieval → generation → citation → abstention → cost/speed. Each cell shows the raw value plus a coloured delta against baseline. **The oldest selected run is always baseline "A"**, regardless of click order. "Hide unchanged rows" filters rows where every run is within a small threshold of A. |
| **Config diff** | One column per selected run, baseline A first. Cells differing from A are marked `~` and highlighted; settings the runner never captured render as `Unknown` and are never reported as a change. Unchanged settings hidden by default. |
| **Export** | Selected runs and the comparison result as CSV or JSON. The JSON export is the only place fields the panels drop — `total_cost_usd`, `cost_model`, per-run `dashboard_metrics` — actually reach you, since it dumps the API response objects verbatim. |
| **Run evaluation** | Start and cancel runs; see [chapter 5](05-running-evals.md#from-the-dashboard). The tab's empty state points here when no runs exist. |

---

## System tab

Reads only `GET /api/metrics/system` — no eval-service call.

| Panel | Shows |
|---|---|
| **Component status** | One row per backend dependency (postgres, ollama, bm25 when hybrid search is on), with status dot and badge. Same `component_status` object that feeds the header health dot. |
| **Models table** | One row per role (LLM, embedding, reranker if enabled, eval judge if configured): name, provider, parameter count, disk size, load status |
| **Index statistics** | Document count, chunk count, configured `top_k`, and final post-rerank `top_n` |

The API returns a `reference_url` and `description` for every model in that table;
neither is rendered, so there is no link-out to model documentation.

---

## What the dashboard cannot do

| Limit | Use instead |
|---|---|
| **No significance testing displayed.** The CLI and API compute paired bootstrap intervals, McNemar's test, and BH correction — the analytics UI shows point deltas only. | `just eval-compare <a> <b>` |
| **No stage-level latency.** The harness times one span around the whole query. | Nothing — the data does not exist |
| **No search or filter in the run selector.** You scroll the 50 most recent. | The CLI, or read `data/eval_runs/` directly |
| **Fields fetched but never drawn:** the run's `metadata.seed`, the descriptive/research-note fields on hybrid search, contextual retrieval and the reranker, `pipeline_description`, the `evaluation_metrics` glossary, and the server's own response `timestamp` (the header shows your browser clock). | The raw API response |

---

## When to drop to the CLI

- **A tier, dataset mix, or judge setting the panel does not expose**, or scripting
  a sweep: `just eval --tier <tier> --datasets <names> --samples <n>`.
- **Significance testing on a comparison** — `just eval-compare`.
- **A YAML config file** (`--config`); the dashboard form covers only the flags in
  chapter 5.
- **An individual question's response**, not just the distribution: read the run
  JSON in `data/eval_runs/`, or export a `review-*` format.
- **Runs outside the 50 most recent**, or filtering by dataset or tier.
- **Judge calibration**, listing datasets, or anything else under `evals.cli` —
  `just eval-calibrate`, `just eval-datasets` are CLI-only.

---

**Next:** [10. Troubleshooting](10-troubleshooting.md).
