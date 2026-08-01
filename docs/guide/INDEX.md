# RAGBench operator guide

For people running RAGBench on their own infrastructure and for anyone evaluating
whether its answers are good.

This guide teaches one workflow: **measure a baseline → change one thing →
re-measure → decide whether the change was worth it.** Everything else supports
that loop.

If you read only two chapters, read
[6. The tuning workflow](06-tuning-workflow.md) and
[11. Limits and caveats](11-limits-and-caveats.md). The first is the method; the
second is what it can and cannot establish.

---

## Chapters

| # | Chapter | What it covers |
|---|---|---|
| 1 | [What this does](01-what-this-does.md) | The system model, and one question traced end to end |
| 2 | [Getting running](02-getting-running.md) | Deploy, ingest, first query, confirm health |
| 3 | [Configuration tour](03-configuration-tour.md) | Every knob that matters, grouped by what it moves |
| 4 | [Evaluation concepts](04-evaluation-concepts.md) | What each metric means — and what it cannot tell you |
| 5 | [Running evaluations](05-running-evals.md) | Datasets, **building a golden set from your own corpus**, running and reading results |
| 6 | [The tuning workflow](06-tuning-workflow.md) ★ | The core loop, and how to tell a real difference from noise |
| 7 | [Experiment cookbook](07-experiment-cookbook.md) ★ | Eight concrete experiments, each with what to change and how to measure |
| 8 | [Privacy and PII](08-privacy-and-pii.md) | How masking works, its threat model, its limits, and its cost |
| 9 | [Reading the dashboard](09-reading-the-dashboard.md) | Every panel, and what the dashboard cannot do |
| 10 | [Troubleshooting](10-troubleshooting.md) | Symptom → cause → check → fix |
| 11 | [Limits and caveats](11-limits-and-caveats.md) ★ | An honest account of what these evaluations prove |

---

## Reading paths

### "I just want it running"

[2. Getting running](02-getting-running.md) →
[10. Troubleshooting](10-troubleshooting.md) when something breaks.

Read the model-selection section of chapter 2 carefully. The checked-in
configuration has cloud models active, which is the most common first-run failure.

### "I want better answers"

[1. What this does](01-what-this-does.md) →
[4. Evaluation concepts](04-evaluation-concepts.md) →
[5. Running evaluations](05-running-evals.md) →
[6. The tuning workflow](06-tuning-workflow.md) →
[7. Experiment cookbook](07-experiment-cookbook.md)

Build a golden set first (chapter 5). Without your own questions you are tuning
against someone else's corpus. Then work the cookbook in the order it suggests —
verify keyword search works, then test reranking, then `top_k`.

Most RAG quality problems are retrieval problems. Resist upgrading the generation
model first.

### "I want to cut cost"

[3. Configuration tour](03-configuration-tour.md) (the cost section) →
[7. Experiment cookbook](07-experiment-cookbook.md) recipes 2, 4 and 5 →
[6. The tuning workflow](06-tuning-workflow.md)

The big levers are provider choice, whether contextual retrieval runs at ingestion
(one LLM call per chunk), and `retrieval.top_k`, which sets prompt size on every
query. Measure what quality you lose before committing — a cheaper configuration
that answers badly is not cheaper.

### "I want to verify privacy"

[8. Privacy and PII](08-privacy-and-pii.md) →
[3. Configuration tour](03-configuration-tour.md) (the privacy section)

Start with the distinction at the top of chapter 8: running local models is a
structural guarantee, and PII masking is a mitigation. They are not equivalent.
Chapter 8's verification section shows how to check masking yourself rather than
trusting the configuration.

### "I need to judge whether these numbers mean anything"

[4. Evaluation concepts](04-evaluation-concepts.md) →
[11. Limits and caveats](11-limits-and-caveats.md) →
[6. The tuning workflow](06-tuning-workflow.md) (step 4)

Short version: there is no significance testing anywhere in the tooling, sample
sizes are usually small, and there is one judge with documented biases. Chapter 6's
noise-floor technique is the practical workaround. Chapter 11 covers how to report
results honestly.

### "I'm evaluating whether to adopt this"

[1. What this does](01-what-this-does.md) →
[11. Limits and caveats](11-limits-and-caveats.md) →
[`docs/suggestions.md`](../suggestions.md)

Chapter 11's closing section on what the system is genuinely good for, and the
backlog of known defects, are the most useful pages for that decision.

---

## Conventions

**Commands** are given as `just` recipes where one exists, with the underlying
`docker compose` form where it does not.

**Numbers in examples are illustrative** unless explicitly stated otherwise. This
system ships with no measured before/after benchmarks, and none are invented here.
Where an external published figure is cited, its source is named.

**Sections headed "Recommendations (not currently implemented)"** describe general
practice that RAGBench does not do. They are separated so they cannot be mistaken
for features.

**Known defects are documented as defects** rather than omitted. Where a
configuration key does nothing, or a metric is misleading by default, the guide
says so.

---

## Related documentation

- [`docs/internal/`](../internal/INDEX.md) — engineering reference: how the system
  is built and why.
- [`docs/suggestions.md`](../suggestions.md) — known defects and improvement
  proposals found while writing this guide.
- [`README.md`](../../README.md) and [`OVERVIEW.md`](../../OVERVIEW.md) — project
  overview and quick start.
