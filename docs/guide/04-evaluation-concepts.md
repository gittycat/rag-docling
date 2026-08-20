# 4. Evaluation concepts

What each metric measures, how it is computed, and where it misleads. A metric you
misread is worse than no metric — it gives you confidence in the wrong direction.

Chapter 5 covers running evaluations; chapter 11 is the honest summary of what the
whole apparatus can prove.

---

## Why measure at all

The alternative is asking a few questions and judging the answers yourself. That
works exactly until you make a change. Then you are comparing your memory of
yesterday's answers against today's, on questions you chose because they were
interesting, with a mental model of "better" that shifted in between.

Evaluation replaces that with a fixed question set, a fixed scoring procedure, and
a record. It does not make you objective — the judge has biases and your questions
encode your assumptions — but it makes you *consistent*, and consistency is what
lets you attribute a change to a cause.

---

## The two tiers

Choosing the wrong tier is the most common way to get a meaningless result.

| Tier | What runs | Use when you changed |
|---|---|---|
| `generation` | Passages handed to the model directly. **Retrieval never runs.** | The generation model, prompts, anything about how the answer is written |
| `end_to_end` | Dataset passages ingested as real documents, then queried through the full path: retrieve → fuse → rerank → generate. Documents cleaned up afterward. | `top_k`, `top_n`, hybrid search, the reranker, the embedding model, chunk size |

**The rule:** if the thing you changed happens *before* the model sees its context,
you need `end_to_end`. If it happens *after*, `generation` gives a cleaner signal
because retrieval variance cannot contaminate it.

Retrieval metrics mean nothing in the `generation` tier, because retrieval does not
run. Invalid tier/dataset combinations are rejected before the run starts — the
compatibility matrix is in chapter 5.

---

## Retrieval metrics

*Did the system find the right passages?* No LLM needed, fast, and deterministic —
the same run twice gives the same number. **The most trustworthy metrics here.**

They require **gold passages**: the dataset must declare which passages actually
answer each question.

| Metric | What it measures |
|---|---|
| `recall_at_k` | Of all gold passages, what fraction appeared in the top *k*? Computed at k = 1, 3, 5, 10. |
| `precision_at_k` | Of the top *k* retrieved, what fraction were gold? Computed at k = 1, 3, 5. |
| `mrr` | Mean reciprocal rank — 1 ÷ position of the *first* relevant result. 1st = 1.0, 2nd = 0.5, 3rd = 0.33. |
| `ndcg_at_10` | Like MRR but accounts for all relevant results, their positions, and how relevant each is. |

All range 0–1, higher is better.

**Which one to watch.** `recall_at_k` at your effective context size. If 5 chunks
reach the model, `recall_at_5` tells you how often the answer was even available. A
high `recall_at_10` with a low `recall_at_5` is a specific, actionable diagnosis:
retrieval finds the right passage but ranks it too low — precisely what reranking
fixes.

**How matching works.** A retrieved chunk counts as gold if its chunk ID matches
exactly, or failing that, if its text overlaps the gold passage by at least 30% on
a Jaccard token measure. That fallback is necessary because chunk boundaries differ
between dataset and ingestion, but it is a fuzzy comparison with a threshold
somebody chose. A near-miss chunk holding half the answer may or may not count.
Do not read more precision into these numbers than that.

---

## Generation metrics

*Is the answer any good?* All three need an LLM judge, which makes them the most
useful metrics and the least reliable.

| Metric | What it measures | Needs a reference answer? |
|---|---|---|
| `faithfulness` | Are the answer's claims supported by the retrieved context? **The hallucination metric.** | No |
| `answer_correctness` | Does the answer convey the same information as the reference? | Yes |
| `answer_relevancy` | Does the answer address the question asked? | No |

**`faithfulness` matters most.** It is the only metric that directly measures
whether the system made something up, and it needs no reference answer — so it
works on your own corpus without writing model answers. A drop is a real problem
regardless of what else improved.

**`answer_correctness` requires you to have written the right answer**, the
expensive part of a golden set. It is also the metric most sensitive to phrasing:
an answer that is correct but structured differently from your reference may score
below one that is wrong but similarly worded.

**The judge scores a rubric, loosely.** Each prompt asks for 0.0 / 0.5 / 1.0 with
descriptions attached, but the parser accepts any float in range and clamps
outliers. You get a semi-continuous score against a three-point rubric — worth
remembering when a metric moves by 0.03 and you wonder whether that means anything.

---

## Citation metrics

*Did the answer point at the right sources?*

| Metric | What it measures |
|---|---|
| `citation_precision` | Of the sources cited, what fraction were gold? |
| `citation_recall` | Of the gold passages, what fraction were cited? |
| `section_accuracy` | Fraction of citations where both document and specific chunk matched a gold passage. |

**These are the easiest metrics in the system to misinterpret.**

By default `eval.citation_scope` is `retrieved`, which means **every retrieved
chunk counts as a citation**. Under that setting these metrics are not measuring
citing behaviour at all — they re-measure retrieval with different arithmetic. The
system warns you when citation metrics are enabled; heed it.

To measure real citation behaviour set `eval.citation_scope: explicit`, which also
switches on the prompt instructions telling the model to emit `[1]`, `[2]`-style
references. Only then are you scoring what the model chose to cite.

**With no gold passages, these report `n/a`** — not 0.0, not 1.0. Earlier versions
returned a perfect 1.0, so an unannotated run displayed flawless citation scores
that meant nothing. That is fixed, but still: never compare citation scores across
datasets with different gold-passage coverage.

---

## Abstention metrics

*Does the system know when to say it doesn't know?*

| Metric | What it measures | Direction |
|---|---|---|
| `unanswerable_accuracy` | Overall accuracy at deciding whether to abstain | Higher better |
| `abstention_false_positive_rate` | How often it refused a question it could have answered | **Lower better** |
| `abstention_false_negative_rate` | How often it answered a question it should have refused | **Lower better** |

The false negative rate is the hallucination-risk metric: the context could not
answer, and the system answered anyway. For most operators this matters more than
any accuracy score — a system that confidently invents answers is worse than one
that is merely mediocre.

The two rates trade off. Prompting toward caution lowers false negatives and raises
false positives. Where you sit on that curve is a product decision.

**How abstention is detected:** case-insensitive substring matching against
`eval.abstention_phrases` in `config.yml`. This is string matching, not
comprehension. Keep the phrases short — a full sentence with terminal punctuation
only matches that exact wording and misses paraphrases. Narrowing the list makes
the model look worse at abstaining without anything having changed, so treat edits
there as a scoring change.

---

## Performance metrics

`latency_p50_ms`, `latency_p95_ms`, `latency_avg_ms`, `cost_per_query`. Recorded,
not judged.

**Eval latency is not user-perceived latency.** Evaluations run many queries
concurrently; a real user runs one. Concurrency inflates the numbers, sometimes
considerably. Useful for *comparing runs* under identical conditions, misleading as
an absolute statement about user experience. Watch p95, not p50 or the average —
the tail is what people complain about.

**Cost is an estimate** from token counts times hardcoded rate tables in the
source. There are two such tables in different services and they have drifted.
Compare configurations with it; do not forecast a bill.

---

## The weighted score

Each run produces one headline number, configured under `eval.scoring` in
`config.yml`:

```yaml
eval:
  scoring:
    weights:
      accuracy: 0.30        # answer correctness + abstention
      faithfulness: 0.20    # grounding in retrieved context
      citation: 0.20        # citation precision / recall / section accuracy
      retrieval: 0.15       # recall, precision, MRR, nDCG
      cost: 0.10            # cost per query
      latency: 0.05         # P50 latency
    latency_threshold_ms_generation: 5000
    latency_threshold_ms_end_to_end: 30000
    max_cost_per_query_usd: 0.10
```

**This is an opinion, not a measurement.** Somebody decided citation quality
matters four times as much as latency. If you run a customer-facing assistant where
two seconds decides use versus abandonment, a 0.05 latency weight badly understates
your constraints.

Unlike earlier versions, you can change it — the weights and both normalization
thresholds are config keys. Objectives with no data in a run are dropped and their
weight redistributed, so the weights are relative and need not sum to 1.

Two cautions. **Editing this block is a scoring change** — runs across the edit are
not comparable. And because the score collapses six dimensions into one, two runs
with the same weighted score can be completely different systems: one fast and
shallow, one slow and accurate.

**Use the weighted score to sort candidates. Use the individual metrics to decide.**

---

## What these metrics cannot tell you

- **Whether a difference is real, on its own.** `compare` does report paired
  bootstrap confidence intervals (chapter 5), but a wide interval on a small
  question set is still uninformative.
- **Anything about questions you did not ask.** Your golden set encodes your
  assumptions. A perfect score on 30 questions is evidence about those 30
  questions.
- **Whether the answer is wrong or the judge is wrong.** One judge, no ensemble, no
  inter-rater agreement check.
- **That your corpus is the problem.** If the answer is not in your documents, no
  configuration finds it. Low scores across the board with high abstention often
  mean a coverage gap, not a tuning problem.
- **How the system handles a second turn.** Every evaluation is single-turn. The
  condensation step that rewrites follow-up questions is never exercised.

---

## How the judge fails, and what happens then

The judge is an LLM called once per question per generation metric. It can fail:
API errors, timeouts, unparseable output.

Each call is retried up to three times. If all attempts fail, the sample is
**excluded from the average** rather than scored zero, and the metric's
`sample_size` shrinks.

That is the right behaviour. Scoring a failed call as 0.0 would treat "we could not
measure this" as "the answer was terrible," and a flaky API would look exactly like
a quality regression.

**The consequence: check `sample_size` before trusting a metric.** If you ran 100
questions and faithfulness reports 62, the judge failed 38 times, and the score
describes the 62 that happened to succeed — not a random sample.

Failure modes that produce no error at all:

| Mode | Effect |
|---|---|
| **Not a domain expert** | On specialist content it scores plausibility, not correctness |
| **Verbosity bias** | Longer, more thorough-sounding answers score better independent of accuracy |
| **Self-preference** | The shipped defaults use OpenAI for both generation and judging. A judge scoring its own family is not neutral — the runner now warns and records this on the run. |
| **Rubric compression** | A three-point rubric yields clustering at 0.0, 0.5, 1.0, limiting resolution on small differences |

Calibration quantifies some of this — see chapter 5. It covers all four judge
prompts, but with different strength: faithfulness and context relevance are
checked against RAGBench ground truth, while `answer_correctness` and
`answer_relevancy` get a weaker discrimination test.

---

**Next:** [5. Running evaluations](05-running-evals.md) — including building a
golden set from your own documents.

Engineering detail: [`docs/internal/eval-framework.md`](../internal/eval-framework.md).
