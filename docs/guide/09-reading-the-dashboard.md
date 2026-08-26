# 9. Read the dashboard

Open <http://localhost:8000/analytics>. The Analytics page has **Health**,
**Experiments**, and **System** tabs.

It loads system and eval data on open. Active-run status polls every five seconds;
auto-refresh reloads all data every 30 seconds. A failed background refresh leaves
the previous values on screen without a stale-data warning.

## Health tab

The default tab shows the latest run and its change from the previous run.

| Panel | What to check |
|---|---|
| Weakest-link verdict | Client-side summary of the weakest metric group |
| Weighted score | Configured multi-objective score; do not treat it as overall truth |
| Retrieval and generation | Weakest metric in each group, not fixed headline metrics |
| Cost and p95 latency | Comparison values; cost is estimated and latency uses eval concurrency |
| Config under test | Recorded model, retrieval, reranking, and chunk settings |
| Latency | p50, average, and p95 for the full query; no stage breakdown |
| Weighted-score breakdown | Weight, effective share, score, and contribution by objective |
| Metric breakdown | Values, thresholds, standard deviation, sample size, and distributions |

Distribution views help distinguish consistent scores from averages produced by a
mix of very good and very bad answers.

## Experiments tab

| Panel | Behaviour |
|---|---|
| History | Sparklines for weighted score, faithfulness, correctness, p95 latency, and cost |
| Run selector | Up to 50 recent runs; select up to four |
| Comparison | The oldest selected run is baseline A, regardless of click order |
| Config diff | Highlights values that differ from A; `Unknown` is not treated as a change |
| Export | CSV or JSON for selected runs and their comparison |
| Run evaluation | Starts, queues, tracks, and cancels evaluations |

The comparison table shows point differences only. It does not show paired
confidence intervals, McNemar tests, or multiple-comparison correction.

## System tab

This tab reads live RAG-server metrics:

- component health for PostgreSQL, TEI, and BM25 when enabled;
- active generation, embedding, reranker, and judge models; and
- document count, chunk count, `top_k`, and final `top_n`.

Model reference URLs returned by the API are not rendered.

## Use the CLI when you need

- statistical comparison: `just eval-compare <a> <b>`;
- an unsupported tier, dataset mix, or YAML eval config;
- per-question answers and retrieved chunks;
- runs outside the 50 most recent or filtering by dataset and tier; or
- judge calibration and dataset management.

The dashboard has no stage-level latency because the eval harness records only the
full query span.

**Next:** [10. Troubleshoot](10-troubleshooting.md).
