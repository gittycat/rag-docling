# 11. Limits and caveats

An evaluation produces evidence about a specific system under specific conditions.
It does not produce a universal quality score.

## What a good score means

A good score means that this configuration answered this question set, against
this corpus, under this judge and scoring method, at this time.

It does not prove that:

- real users will ask similar questions;
- the corpus contains every answer they need;
- the same provider model will behave identically later;
- the judge is correct; or
- the tested configuration is the best possible one.

## Statistical limits

`eval-compare` uses paired bootstrap confidence intervals for pairable metrics.
Binary metrics also receive McNemar’s exact test, and Benjamini–Hochberg correction
is applied across the metric family.

These tools reduce overconfidence; they do not compensate for a small dataset.

- A wide interval remains uninformative.
- Runs with fewer than 100 paired questions are flagged `underpowered`.
- Aggregate-only metrics such as p50 latency cannot be paired.
- One score per question does not characterize repeated judge or model variation;
  measure an unchanged baseline again with `--no-judge-cache`.
- Looking across many metrics creates chance winners. Choose the primary metric
  before running the comparison.

Use “no detectable difference” when an interval includes zero. Do not claim the
configurations are equal.

## Judge limits

Faithfulness, correctness, and relevancy come from one LLM judge.

- There is no second judge or inter-rater agreement measure.
- Judges can prefer verbose answers and their own model family.
- A general judge is not a domain expert.
- The three-point rubric limits resolution for small effects.
- Failed calls reduce `sample_size`; they are excluded, not scored zero.

The default configuration uses OpenAI for generation and judging. The runner warns
about this family pairing, but a warning does not remove the bias. For important
decisions, calibrate the judge, use a judge from another provider, and review a
sample of answers manually.

## Dataset limits

Public benchmarks test their documents and questions, not yours. Your golden set
tests the questions you chose to write and can become stale or overfit after many
tuning cycles.

The local golden dataset supports only `generation`. Even with gold-passage
annotations, it does not execute retrieval. Custom end-to-end evaluation against
your existing corpus is not built in.

Retrieval and citation scores require gold evidence. Without it, the metric is
`n/a`. With `eval.citation_scope: retrieved`, citation metrics count every
retrieved chunk and therefore mostly re-measure retrieval.

## Coverage limits

| Missing coverage | Consequence |
|---|---|
| Multi-turn evaluation | Follow-up question condensation is never tested |
| User-load latency | Eval concurrency does not match one interactive user |
| Stage-level timing | Only total query latency is recorded |
| Live provider pricing | Cost estimates can drift from actual bills |
| Streaming evaluation | Streaming-only failures and PII behaviour are not scored |
| Corpus coverage metric | Low scores cannot distinguish missing content from poor retrieval |

PII masking quality is not measured automatically. Create an explicit masking-on
versus masking-off generation experiment.

## Reproducibility limits

Runs record active models and retrieval settings from the RAG server. Unknown
values remain `Unknown`, and query caching is refused when the server config is
insufficient.

Still, exact reproduction is not guaranteed:

- `config.yml` can reload during a run;
- cloud providers may update a model behind a stable name;
- temperature zero reduces but does not remove nondeterminism;
- judge caching makes a rerun non-independent by default; and
- query-cache keys do not include the indexed corpus.

Freeze configuration and corpus during an experiment, keep the seed fixed, and
record changes outside the run file.

## What RAGBench is good at

| Use | Why it is useful |
|---|---|
| Catching large regressions | Large failures are visible even on modest sets |
| Comparing substantially different configurations | Large effects exceed normal noise more clearly |
| Measuring annotated retrieval | Metrics are deterministic and need no judge |
| Exposing cost and latency trade-offs | Approximate comparisons beat intuition |
| Enforcing a repeatable process | Fixed questions and saved runs reduce tuning by anecdote |
| Testing hallucination and abstention | These failures are easy to miss in casual testing |

## Report results responsibly

Always state:

- dataset, tier, corpus, sample size, and seed;
- baseline and candidate configurations;
- the primary metric chosen in advance;
- point difference and confidence interval;
- whether the comparison was underpowered;
- repeat-run noise, if measured;
- judge model and any family pairing;
- metrics that regressed; and
- latency and cost trade-offs.

Do not present the weighted score as overall quality. Its weights encode a product
choice, and editing them makes older scores incomparable.

## Known missing capabilities

- ensemble judges and agreement reporting;
- multi-turn evaluation;
- significance results in the dashboard;
- configurable RRF source weights; and
- custom end-to-end evaluation against an existing corpus.

See [`docs/suggestions.md`](../suggestions.md) for proposed improvements.

**Back to:** [Guide index](INDEX.md).

Implementation detail:
[`docs/internal/eval-framework.md`](../internal/eval-framework.md).
