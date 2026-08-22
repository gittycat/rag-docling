# RAGBench operator guide

This guide is for technical users who are new to retrieval-augmented generation
(RAG) and evaluation.

It follows one workflow:

1. Understand the pipeline.
2. Run it with a known configuration.
3. Change one setting.
4. Evaluate the same questions again.
5. Compare the runs and keep only measured improvements.

## Read in order

| # | Chapter | Outcome |
|---|---|---|
| 1 | [RAGBench concepts](01-overview.md) | Understand ingestion, retrieval, generation, and the tuning loop |
| 2 | [Get RAGBench running](02-getting-running.md) | Start the stack, ingest a document, and ask a question |
| 3 | [Configure the RAG pipeline](03-configuration-tour.md) | Choose models, retrieval, reranking, chunking, and related settings |
| 4 | [Evaluation concepts](04-evaluation-concepts.md) | Choose an evaluation tier and understand the metrics |
| 5 | [Run evaluations](05-running-evals.md) | Build a question set, run an eval, and inspect its result |
| 6 | [Compare configurations](06-tuning-workflow.md) | Establish a baseline, control variables, and decide whether a change helped |
| 7 | [Experiment recipes](07-experiment-cookbook.md) | Test common changes with the right tier and metrics |
| 8 | [Privacy and PII](08-privacy-and-pii.md) | Choose a privacy posture and verify masking |
| 9 | [Read the dashboard](09-reading-the-dashboard.md) | Interpret health, experiment, and system panels |
| 10 | [Troubleshoot](10-troubleshooting.md) | Diagnose startup, ingestion, query, and eval failures |
| 11 | [Limits and caveats](11-limits-and-caveats.md) | Report what an evaluation can and cannot establish |

Chapters 1–7 form the main tutorial. Chapters 8–11 are operating references.

## Short paths

- **Run the system:** [Chapter 2](02-getting-running.md), then
  [Chapter 10](10-troubleshooting.md) if needed.
- **Improve answer quality:** [Chapters 3–7](03-configuration-tour.md).
- **Reduce cost or latency:** review the trade-offs in
  [Chapter 3](03-configuration-tour.md), then use the matching recipe in
  [Chapter 7](07-experiment-cookbook.md).
- **Review privacy:** [Chapter 8](08-privacy-and-pii.md).
- **Judge whether a result is credible:** [Chapter 6](06-tuning-workflow.md), then
  [Chapter 11](11-limits-and-caveats.md).

## Conventions

- Commands use `just` recipes when available.
- Example scores are illustrative unless explicitly sourced.
- The guide calls out known limitations instead of hiding them.

## Related documentation

- [`docs/internal/`](../internal/INDEX.md) — implementation details.
- [`docs/suggestions.md`](../suggestions.md) — known defects and proposed work.
- [`README.md`](../../README.md) and [`OVERVIEW.md`](../../OVERVIEW.md) — project
  overview and quick start.
