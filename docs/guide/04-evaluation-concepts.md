# 4. Evaluation concepts

An evaluation runs a fixed set of questions, records the answers and scores them. It lets you compare configurations against the same evidence instead of relying on memory or a few hand-picked examples.

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

## Claim grounding metrics

Citation metrics ask whether a cited chunk is one of the gold passages. They do
not ask whether that chunk supports the sentence citing it, so a citation can be
"correct" while pointing at a passage that says something else. Faithfulness has
the mirror problem: one judgement over the whole answer, which cannot say which
sentence drifted and never looks at citations at all.

This group splits the answer into sentence-level claims, reads the `[1]` markers
attached to each one, and judges the pairs.

| Metric | Meaning | Better direction |
|---|---|---|
| `claim_groundedness` | Fraction of claims the retrieved context supports | Higher |
| `citation_entailment` | Fraction of citations whose passage supports the claim citing it | Higher |
| `claim_citation_support` | Fraction of cited claims backed by something they cite | Higher |
| `uncited_claim_rate` | Fraction of claims that cite nothing | Lower |

Read the first three alongside the fourth: an answer that cites one sentence
perfectly and leaves nine uncited scores 1.0 on all three.

Two things to know before turning it on:

- **It costs.** One judge call per claim, plus one per claim-citation link, on top
  of the three per question the generation metrics use. It is off by default —
  tick "Claim grounding" in the dashboard's run panel, or pass `--groundedness`
  to `python -m evals.cli eval`. Capped at 5 claims per answer and 2 citations per
  claim; the cap is reported per question when it bites.
- **It needs `eval.citation_scope: explicit`.** Under the default `retrieved` the
  model is never asked to emit `[1]` markers, so the two citation metrics are
  `n/a` and `uncited_claim_rate` is 1.0 for every answer.

The `groundedness` objective is weighted `0.0` in `config.yml`, so these metrics
are reported without changing your headline score. Raising that weight is a
scoring change: runs from before and after are not comparable.

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
| `cost_per_query` | Estimated API cost from token counts — answer generation **and** judging |
| `ingestion_cost_per_document` | Estimated ingestion cost per document — contextual enrichment plus embedding (`end_to_end` only) |
| `ingestion_latency_per_document_ms` | Wall-clock ingestion time per document, with a stage breakdown (`end_to_end` only) |

Eval queries run concurrently, so latency is useful for like-for-like comparisons,
not as an absolute user-experience measurement. Cost uses hardcoded price tables;
use it to compare configurations, not forecast a bill. The two ingestion metrics
read persisted per-document stage records, so they need documents ingested during
the run — they are how [Recipe 4](07-experiment-cookbook.md) (contextual
retrieval on or off) prices contextual retrieval.

## The weighted score

`eval.scoring` combines seven objectives into one score:

```yaml
eval:
  scoring:
    weights:
      accuracy: 0.30
      faithfulness: 0.20
      citation: 0.20
      groundedness: 0.0     # claim grounding — reported, not scored
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
