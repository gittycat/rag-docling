# 4. Evaluation concepts

Before running anything, it is worth understanding what the numbers mean — and,
more importantly, what they do not mean. A metric you misread is worse than no
metric, because it gives you confidence in the wrong direction.

This chapter covers what each metric measures, how it is computed, and where it
misleads. Chapter 5 covers running evaluations; chapter 11 is the honest summary
of what the whole apparatus can and cannot prove.

---

## Why measure at all

The alternative is asking a few questions and judging the answers yourself. That
works exactly until you make a change. Then you are comparing your memory of
yesterday's answers against today's, on questions you chose because they were
interesting, with a mental model of "better" that shifted somewhere in between.

Evaluation replaces that with a fixed set of questions, a fixed scoring
procedure, and a record. It does not make you objective — the judge has its own
biases and your question set encodes your assumptions — but it makes you
*consistent*, and consistency is what lets you attribute a change to a cause.

---

## The two tiers

Every evaluation runs in one of two modes, and choosing the wrong one is the most
common way to get a meaningless result.

### `generation` tier

Passages are handed to the system directly. Retrieval never runs. The system is
asked to answer *given this context*, and only generation quality is measured.

Use this when you are changing the generation model, the prompts, or anything
about how the answer is written. Because retrieval is bypassed, retrieval
variance cannot contaminate the result — you are measuring the generator alone.

### `end_to_end` tier

The evaluation ingests the dataset's passages into the running system as real
documents, then asks questions through the normal query path: retrieve, fuse,
rerank, generate. Documents are cleaned up afterward.

Use this when you are changing anything in retrieval — `top_k`, hybrid search,
the reranker, the embedding model, chunk size. It is the only tier where
retrieval metrics mean anything, because it is the only tier where retrieval runs.

Not every dataset supports both tiers. The compatibility matrix is in chapter 5;
the system will refuse an invalid combination rather than silently producing
nonsense.

**The practical rule:** if the thing you changed happens before the model sees the
context, you need `end_to_end`. If it happens after, `generation` gives you a
cleaner signal.

---

## Retrieval metrics

These ask: *did the system find the right passages?* They need no LLM, they are
fast, and they are deterministic — the same run twice gives the same number. They
are the most trustworthy metrics in the system.

They require **gold passages**: the dataset must declare which passages actually
answer each question.

| Metric | What it measures |
|---|---|
| `recall_at_k` | Of all the gold passages, what fraction appeared in the top *k* retrieved? Computed at k = 1, 3, 5, 10. |
| `precision_at_k` | Of the top *k* retrieved, what fraction were gold? Computed at k = 1, 3, 5. |
| `mrr` | Mean reciprocal rank. 1 divided by the position of the *first* relevant result. First position scores 1.0, second 0.5, third 0.33. |
| `ndcg_at_10` | Normalized discounted cumulative gain. Like MRR but accounts for all relevant results and their positions, weighted by how relevant each is. |

All range 0 to 1, higher is better.

**Which one to watch.** `recall_at_k` at your effective context size is usually
the one that matters. If five chunks reach the model, `recall_at_5` tells you how
often the answer was even available to be found. A high `recall_at_10` with a low
`recall_at_5` is a specific, actionable diagnosis: retrieval is finding the right
passage but ranking it too low, which is precisely what reranking fixes.

**How matching works, and why it matters.** A retrieved chunk counts as gold if
its chunk ID matches exactly — or, failing that, if its text overlaps the gold
passage's text by at least 30% on a Jaccard token measure. That fallback is
necessary because chunk boundaries differ between the dataset and your ingestion,
but it is a fuzzy comparison with a threshold somebody chose. A near-miss chunk
containing half the answer may or may not count. Do not treat these numbers as
having more precision than that.

---

## Generation metrics

These ask: *is the answer any good?* All three require an LLM judge — a separate
model that reads the answer and scores it. That makes them the most useful
metrics and the least reliable ones.

| Metric | What it measures | Needs a reference answer? |
|---|---|---|
| `faithfulness` | Are the claims in the answer supported by the retrieved context? This is the hallucination metric. | No |
| `answer_correctness` | Does the answer convey the same information as the reference answer? | Yes |
| `answer_relevancy` | Does the answer actually address the question asked? | No |

All range 0 to 1, higher is better.

**`faithfulness` is the one to care about most.** It is the only metric that
directly measures whether the system made something up, and it needs no reference
answer — which means it works on your own corpus without you having to write
model answers. A drop in faithfulness is a real problem regardless of what else
improved.

**`answer_correctness` requires you to have written the right answer**, which is
the expensive part of building a golden set. It is also the metric most sensitive
to phrasing: an answer that is correct but structured differently from your
reference may score below one that is wrong but similarly worded.

**The judge is scoring a rubric, loosely.** Each prompt asks for a score on a
0.0 / 0.5 / 1.0 scale with descriptions attached, but the parser accepts any float
between 0 and 1 and clamps out-of-range values. In practice you get a
semi-continuous score against a three-point rubric, which is worth knowing when a
metric moves by 0.03 and you are wondering whether that means anything.

---

## Citation metrics

These ask: *did the answer point at the right sources?*

| Metric | What it measures |
|---|---|
| `citation_precision` | Of the sources cited, what fraction were gold? |
| `citation_recall` | Of the gold passages, what fraction were cited? |
| `section_accuracy` | Fraction of citations where both the document and the specific chunk matched a gold passage. |

**Read this section carefully, because these metrics are the easiest to
misinterpret in the whole system.**

By default, `eval.citation_scope` is set to `retrieved`, which means **every
retrieved chunk is treated as a citation**. Under that setting, citation metrics
are not measuring the model's citing behaviour at all — they are re-measuring
retrieval, with different arithmetic. The system will warn you about this when
citation metrics are enabled, and the warning is worth heeding.

To measure actual citation behaviour you need `eval.citation_scope: explicit`,
which also switches on the prompt instructions telling the model to emit `[1]`,
`[2]`-style references. Only then are you scoring what the model chose to cite.

**Second trap:** when a dataset defines no gold passages, `citation_precision` and
`citation_recall` both return **1.0**. Not zero, not null — a perfect score. The
built-in golden dataset has no gold passages, so a golden-set run will show
flawless citation metrics that mean nothing whatsoever. Never compare citation
scores across datasets with different gold-passage coverage.

---

## Abstention metrics

These ask: *does the system know when to say it doesn't know?*

| Metric | What it measures | Direction |
|---|---|---|
| `unanswerable_accuracy` | Overall accuracy at deciding whether to abstain. | Higher better |
| `abstention_false_positive_rate` | How often it refused a question it could have answered. | **Lower better** |
| `abstention_false_negative_rate` | How often it answered a question it should have refused. | **Lower better** |

The false negative rate is the hallucination-risk metric: the system was given a
question its context could not answer, and it answered anyway. For most operators
this matters more than any accuracy score. A system that confidently invents
answers to unanswerable questions is worse than a system that is merely mediocre.

The two rates trade off. Prompting toward caution lowers false negatives and
raises false positives — you get a system that refuses too readily. Where you want
to sit on that curve is a product decision, not a technical one.

**How abstention is detected:** by matching the answer text against a list of
phrases like "not enough information." This is string matching, not
comprehension. If you change the abstention wording in `prompts.context`, the
metric will not follow — the phrase list lives in code. And note that the
`eval.abstention_phrases` key in `config.yml`, which looks like it controls this,
does not.

---

## Performance metrics

`latency_p50_ms`, `latency_p95_ms`, `latency_avg_ms`, and `cost_per_query`. These
are recorded, not judged.

**Latency measured here is not user-perceived latency.** Evaluations run many
queries concurrently against your server; a real user runs one. Concurrency
inflates the numbers, sometimes considerably. These figures are useful for
*comparing runs* under identical conditions, and misleading as an absolute
statement about what your users experience.

Watch p95 rather than p50 or the average. The tail is what people complain about,
and the average hides it.

**Cost is an estimate.** It is computed from token counts multiplied by rates in
hardcoded tables in the source — not a live pricing feed, and there are two such
tables in different services that have drifted apart. Use it to compare
configurations, not to forecast a bill.

---

## The weighted score

Each run produces one headline number combining everything:

| Objective | Weight |
|---|---|
| Accuracy | 0.30 |
| Faithfulness | 0.20 |
| Citation | 0.20 |
| Retrieval | 0.15 |
| Cost | 0.10 |
| Latency | 0.05 |

**This is an opinion, not a measurement.** Somebody decided that citation quality
matters four times as much as latency. That may be wrong for you. If you are
running a customer-facing assistant where a two-second response is the difference
between use and abandonment, a 0.05 latency weight badly understates your
constraints.

The weights are Python constants in the eval service, not `config.yml` keys, so
adjusting them means editing code.

Two further cautions. The latency and cost components are normalized against
hardcoded thresholds that may not suit your deployment. And because the score
collapses six dimensions into one, two runs with the same weighted score can be
completely different systems — one fast and shallow, one slow and accurate.

**Use the weighted score to sort candidates. Use the individual metrics to
decide.**

---

## What these metrics cannot tell you

This section matters more than the rest of the chapter.

**They cannot tell you whether a difference is real.** The tooling reports raw
differences between runs. It performs no significance testing of any kind — no
confidence intervals, no paired tests, no variance accounting. A per-metric
standard deviation is computed internally and then never shown to you in any
comparison. Chapter 6 covers what to do about this.

**They cannot tell you about questions you did not ask.** Your golden set encodes
your assumptions about what users will ask. Real users will ask things you did not
think of, phrased in ways you did not anticipate. A perfect score on 30 questions
you wrote is evidence about those 30 questions.

**They cannot separate "the answer is wrong" from "the judge is wrong."** When
faithfulness drops, the answer may have degraded — or the judge may have had a bad
day on a batch of borderline cases. There is one judge, no ensemble, and no
inter-rater agreement check.

**They cannot detect that your corpus is the problem.** If the answer is not in
your documents, no configuration will find it. Low scores across the board with
high abstention rates often mean a coverage gap, not a tuning problem.

**They cannot tell you about latency under real load.** See above.

**They do not measure what happens on the second turn.** Every evaluation is
single-turn. The condensation step that rewrites follow-up questions — a genuine
source of failure in conversational use — is never exercised.

**They do not evaluate the abstention wording itself,** only whether an abstention
occurred. A refusal that is technically correct and unhelpfully phrased scores the
same as a good one.

---

## How the judge fails, and what happens then

The judge is an LLM, called once per question per generation metric. It can fail:
API errors, timeouts, or output that cannot be parsed into a score.

Each call is retried up to three times, including when the output is malformed.
If all attempts fail, the sample is **excluded from the average** rather than
scored zero. The metric's `sample_size` shrinks to reflect it.

This is the right behaviour and worth understanding, because the alternative is
badly wrong. Scoring a failed judge call as 0.0 would treat "we could not measure
this" as "the answer was terrible," and a flaky API would look exactly like a
quality regression — sending you off to fix a system that was working fine.

The consequence for you: **check `sample_size` before trusting a metric.** If you
ran 100 questions and faithfulness reports a sample size of 62, the judge failed
38 times, and the score describes an unrepresentative subset — the 62 that
happened to succeed, which is not a random sample.

Other judge failure modes, none of which produce an error:

- **It is not a domain expert.** On specialist content it is scoring plausibility,
  not correctness.
- **Verbosity bias.** Longer, more thorough-sounding answers tend to score better,
  independent of accuracy.
- **Self-preference.** The shipped defaults use OpenAI models for both generation
  and judging. A judge scoring output from its own model family is not a neutral
  referee.
- **Rubric compression.** A three-point rubric asked to produce a continuous score
  yields clustering at 0.0, 0.5, and 1.0, which limits the resolution of any small
  difference you are trying to detect.

Calibration exists to quantify some of this — see chapter 5 — but it currently
covers only faithfulness and context relevance. `answer_correctness` and
`answer_relevancy` are never checked against ground truth at all.

---

**Next:** [5. Running evaluations](05-running-evals.md) — including building a
golden set from your own documents.

Engineering detail: [`docs/internal/eval-framework.md`](../internal/eval-framework.md).
