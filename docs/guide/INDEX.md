# RAGBench operator guide

For people running RAGBench on their own infrastructure, and for anyone judging
whether its answers are good.

The guide teaches one workflow: **measure a baseline → change one thing →
re-measure → decide whether the change was worth it.** Everything else supports
that loop.

If you read only two chapters, read [6. The tuning workflow](06-tuning-workflow.md)
and [11. Limits and caveats](11-limits-and-caveats.md). The first is the method;
the second is what it can and cannot establish.

---

## Chapters

| # | Chapter | Covers |
|---|---|---|
| 1 | [What this does](01-what-this-does.md) | The privacy problem, the system model, one question traced end to end |
| 2 | [Getting running](02-getting-running.md) | Deploy, ingest, first query, confirm health |
| 3 | [Configuration tour](03-configuration-tour.md) | Every knob that matters, grouped by what it moves |
| 4 | [Evaluation concepts](04-evaluation-concepts.md) | What each metric means — and what it cannot tell you |
| 5 | [Running evaluations](05-running-evals.md) | Datasets, **building a golden set**, running and reading results |
| 6 | [The tuning workflow](06-tuning-workflow.md) ★ | The core loop, and telling a real difference from noise |
| 7 | [Experiment cookbook](07-experiment-cookbook.md) ★ | Eight experiments, each with what to change and how to measure |
| 8 | [Privacy and PII](08-privacy-and-pii.md) | How masking works, its threat model, its limits, its cost |
| 9 | [Reading the dashboard](09-reading-the-dashboard.md) | Every panel, and what the dashboard cannot do |
| 10 | [Troubleshooting](10-troubleshooting.md) | Symptom → cause → check → fix |
| 11 | [Limits and caveats](11-limits-and-caveats.md) ★ | What these evaluations actually prove |

---

## Reading paths

**"I just want it running."**
[2. Getting running](02-getting-running.md) →
[10. Troubleshooting](10-troubleshooting.md) when something breaks.

Read chapter 2's model-selection section carefully. The checked-in configuration
has cloud inference active, which is the most common first-run failure.

**"I want better answers."**
[1](01-what-this-does.md) → [4](04-evaluation-concepts.md) →
[5](05-running-evals.md) → [6](06-tuning-workflow.md) →
[7](07-experiment-cookbook.md)

Build a golden set first (chapter 5) — without your own questions you are tuning
against someone else's corpus. Then work the cookbook in the order it suggests:
verify keyword search works, then test reranking, then `top_k`. Most RAG quality
problems are retrieval problems; resist upgrading the generation model first.

**"I want to cut cost."**
[3. Configuration tour](03-configuration-tour.md) (cost section) →
[7. Cookbook](07-experiment-cookbook.md) recipes 2, 4, 5 →
[6. Tuning workflow](06-tuning-workflow.md)

The big levers are provider choice, whether contextual retrieval runs at ingestion
(one LLM call per chunk), and `reranker.top_n`, which sets prompt size on every
query. Measure the quality you lose before committing — a cheaper configuration
that answers badly is not cheaper.

**"I want to verify privacy."**
[8. Privacy and PII](08-privacy-and-pii.md) →
[3. Configuration tour](03-configuration-tour.md) (privacy section)

Start with the distinction at the top of chapter 8: running local models is a
structural guarantee; PII masking is a mitigation. They are not equivalent.
Chapter 8's verification section shows how to check masking yourself.

**"Do these numbers mean anything?"**
[4](04-evaluation-concepts.md) → [11](11-limits-and-caveats.md) →
[6, step 4](06-tuning-workflow.md)

Short version: `eval-compare` reports paired bootstrap confidence intervals,
McNemar's test, and a multiple-comparisons correction — so a delta is no longer a
verdict. But sample sizes are usually small, there is one judge with documented
biases, and none of that is shown in the dashboard. Chapter 6's noise-floor
technique covers what the paired test cannot see.

**"Should we adopt this?"**
[1](01-what-this-does.md) → [11](11-limits-and-caveats.md) →
[`docs/suggestions.md`](../suggestions.md)

Chapter 11's section on what the system is genuinely good for, plus the backlog of
known defects, are the most useful pages for that decision.

---

## Conventions

**Commands** are given as `just` recipes where one exists, with the underlying
`docker compose` form where it does not.

**Numbers in examples are illustrative** unless stated otherwise. This system ships
with no measured before/after benchmarks, and none are invented here. Where an
external published figure is cited, its source is named.

**Known defects are documented as defects** rather than omitted. Where a metric is
misleading by default or a value is not configurable, the guide says so.

---

## Related documentation

- [`docs/internal/`](../internal/INDEX.md) — engineering reference: how the system
  is built and why.
- [`docs/suggestions.md`](../suggestions.md) — known defects and improvement
  proposals, with status.
- [`README.md`](../../README.md) and [`OVERVIEW.md`](../../OVERVIEW.md) — project
  overview and quick start.
