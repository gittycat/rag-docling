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
| Retrieval recall | Recall@5 of what the model actually saw, with the candidate-list ceiling beneath it |
| Retrieval bottleneck | Which half of the system is losing evidence: `Ingestion`, `Reranker`, or `None` |
| Retrieval funnel | Recall@5 at each pipeline stage, and the two ways evidence is lost |
| Cost and p95 latency | Comparison values; cost is estimated and latency uses eval concurrency |
| Config under test | Recorded model, retrieval, reranking, and chunk settings |
| Latency | p50, average, and p95 for the full query; no stage breakdown |
| Metric breakdown | Values, thresholds, standard deviation, sample size, and distributions |

Distribution views help distinguish consistent scores from averages produced by a
mix of very good and very bad answers.

### The retrieval funnel

This is the panel to read first, and usually the only one you need before
changing a retrieval setting.

Every ranking metric is computed separately at each stage of the query pipeline —
BM25 and the vector search (which run in parallel), the RRF fusion of the two, and
the cross-encoder rerank — against the same gold evidence. Because each stage can
only pass on what the stage before it found, the drop between two stages tells you
where the evidence went.

That splits every retrieval failure into exactly two kinds, and they point at
opposite halves of the system:

- **Never retrieved** (`1 - ceiling`) — the evidence was not in the candidate list
  at all, so no reranker could have rescued it. The loss is upstream: chunking,
  the embedding model, the BM25/vector balance, retrieval depth (`top_k`), or the
  question wording. Look at `evidence_containment` and `orphaned_evidence_rate` in
  the metric breakdown to tell a chunking problem from a matching problem.
- **Dropped by rerank** (`ceiling - final`) — the candidate list *did* contain the
  evidence and the reranker ranked it below the cutoff. The loss is the reranker
  or `final_top_n`. Raise the cutoff, try a different cross-encoder, or turn
  reranking off and compare.

The funnel names whichever of the two is larger as the bottleneck, and says so in
a sentence under the bars. When both are under 5% it says there is nothing worth
tuning — at that point either move to generation quality or make the question set
harder, because the current set can no longer tell your configurations apart.

Two caveats, both of which make a funnel unreadable rather than wrong:

- A **generation-tier** run retrieves nothing, so the funnel is absent rather than
  zero. The same is true of any run whose questions carry no resolvable gold
  evidence — the panel says which.
- Per-stage scores are only as good as the gold annotations. The shipped
  `golden_qa.json` has no gold passages, so a golden-only run has **no funnel**.
  Public datasets (RAGBench, HotpotQA, MS MARCO) carry the annotations the funnel
  needs. See [11. Limits and caveats](11-limits-and-caveats.md).

`just eval` prints the same funnel at the top of every run report, before the
metric dump, so the CLI and the dashboard tell the same story.

### On the weighted score

Older runs carry a `weighted_score`: a single number blending accuracy,
faithfulness, citation, retrieval, cost, and latency by configured weights. It is
no longer the dashboard headline and should not be used to decide anything. Its
retrieval component averaged `recall@1`, `recall@5`, `mrr`, and `nDCG@10` — a set
metric and rank metrics, in different units — and the weights across objectives
are a statement of preference, not a measurement. It can move without anything
having improved, and improve without moving. Read the funnel and the per-group
metrics instead.

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
