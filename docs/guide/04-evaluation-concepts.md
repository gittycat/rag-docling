# 4. Evaluation concepts

An evaluation runs a fixed question set, records the answers, and scores defined
properties. It lets you compare configurations against the same evidence instead
of relying on memory or a few hand-picked examples.

Evaluation does not remove judgement. Your dataset defines what is tested, and an
LLM judge can be biased or wrong.

## Choose the evaluation tier

| Tier | What runs | Use it for |
|---|---|---|
| `generation` | The dataset supplies context directly; retrieval does not run | Generation model, prompts, answer style, abstention |
| `end_to_end` | Documents are ingested, retrieved, reranked, and passed to generation | Embeddings, hybrid search, `top_k`, reranking, chunking, contextual retrieval |

Rule of thumb: use `end_to_end` for changes made before context reaches the model.
Use `generation` for changes to how the model uses that context.

A retrieval change tested in `generation` can produce a valid-looking result even
though the changed code path never ran.

## Retrieval metrics

Retrieval metrics ask whether the system found and ranked known relevant passages.
They need gold-passage annotations and an `end_to_end` run. They do not need an LLM
judge, so they are fast and deterministic.

| Metric | Meaning |
|---|---|
| `recall_at_k` | Fraction of all gold passages present in the top *k* results |
| `precision_at_k` | Fraction of the top *k* results that are gold |
| `mrr` | Reciprocal rank of the first relevant result, averaged over questions |
| `ndcg_at_10` | Ranking quality across all relevant results, including graded relevance |

All range from 0 to 1; higher is better.

Watch `recall_at_k` at the effective context size. If five chunks reach the model,
`recall_at_5` tells you how often the answer was available. High `recall_at_10`
with low `recall_at_5` means the passage was found but ranked too low.

Matching first uses exact chunk IDs, then falls back to at least 30% Jaccard token
overlap. The fallback accommodates different chunk boundaries but is approximate.

## Generation metrics

Generation metrics ask whether the answer uses its context well. They require an
LLM judge.

| Metric | Meaning | Reference answer required? |
|---|---|---|
| `faithfulness` | Whether answer claims are supported by context | No |
| `answer_correctness` | Whether the answer matches the expected answer | Yes |
| `answer_relevancy` | Whether the answer addresses the question | No |

Faithfulness is the main hallucination measure. Correctness is useful but sensitive
to the quality and wording of the reference answer.

The judge prompt describes a 0.0, 0.5, or 1.0 rubric, although the parser accepts
and clamps any value in that range. Small score changes may exceed the rubric’s
useful resolution.

## Citation metrics

| Metric | Meaning |
|---|---|
| `citation_precision` | Fraction of cited sources that are gold |
| `citation_recall` | Fraction of gold passages that were cited |
| `section_accuracy` | Fraction of citations matching both the document and chunk |

Interpret them according to `eval.citation_scope`:

- `retrieved` treats every retrieved chunk as a citation, so the metrics mostly
  re-measure retrieval.
- `explicit` asks the model to emit numbered citations and scores those choices.

Without gold passages, citation metrics are `n/a`. Do not compare citation scores
across datasets with different annotation coverage.

## Abstention metrics

Abstention means refusing to answer when the context is insufficient.

| Metric | Better direction |
|---|---|
| `unanswerable_accuracy` | Higher |
| `abstention_false_positive_rate` — refused an answerable question | Lower |
| `abstention_false_negative_rate` — answered an unanswerable question | Lower |

False negatives are the greater hallucination risk. False positives and false
negatives usually trade off, so choose the balance your product needs.

The evaluator detects abstention by substring matching
`eval.abstention_phrases`. Editing that list changes scoring and makes earlier runs
incomparable.

## Performance metrics

| Metric | Use |
|---|---|
| `latency_p50_ms` | Typical eval query |
| `latency_p95_ms` | Slow-tail experience |
| `latency_avg_ms` | Mean and per-question comparison data |
| `cost_per_query` | Estimated API cost from token counts |

Eval queries run concurrently, so latency is useful for like-for-like comparisons,
not as an absolute user-experience measurement. Cost uses hardcoded price tables;
use it to compare configurations, not forecast a bill.

## The weighted score

`eval.scoring` combines six objectives into one score:

```yaml
eval:
  scoring:
    weights:
      accuracy: 0.30
      faithfulness: 0.20
      citation: 0.20
      retrieval: 0.15
      cost: 0.10
      latency: 0.05
    latency_threshold_ms_generation: 5000
    latency_threshold_ms_end_to_end: 30000
    max_cost_per_query_usd: 0.10
```

The weights express a product preference, not an objective definition of quality.
Objectives without data are omitted and their weight is redistributed. Edit the
weights before an experiment; changing them makes weighted scores from earlier
runs incomparable.

Use the weighted score to scan candidates. Use individual metrics to decide.

## Judge reliability

Judge-dependent metrics have four important limits:

- One model judges every answer; there is no ensemble or agreement measure.
- LLM judges can prefer longer answers and their own model family.
- A general judge may assess plausible specialist content as correct.
- Failed judge calls are excluded instead of scored zero.

Always compare a judged metric’s `sample_size` with the run’s `question_count`.
A smaller sample means some calls failed and the average covers only the survivors.
Calibrate the judge when you change `active.eval`.

## What a metric cannot establish alone

A point score cannot tell you whether a change caused a real improvement, whether
untested questions behave the same way, or whether the judge was correct. The next
two chapters show how to run comparable evaluations and interpret uncertainty.

**Next:** [5. Run evaluations](05-running-evals.md).

Implementation detail:
[`docs/internal/eval-framework.md`](../internal/eval-framework.md).
