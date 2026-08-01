# 6. The tuning workflow

This is the chapter the rest of the guide exists to support.

The loop is simple to state: measure a baseline, change one thing, measure again,
decide whether the change was real and worth it. Every part of that is easy except
the deciding, and the deciding is where almost all RAG tuning goes wrong.

The core difficulty is this: **RAGBench will happily show you a difference between
two runs and tell you nothing about whether that difference means anything.** The
`compare` command reports raw arithmetic deltas. It performs no significance
testing — no confidence intervals, no paired tests, no variance accounting. A
0.04 improvement measured over 10 questions and a 0.04 improvement measured over
1000 questions are printed identically.

So the judgement is yours. This chapter is about making it well.

---

## Why one variable at a time

If you change the embedding model and `top_k` together and the score improves, you
have learned that the pair is better than the pair. You have not learned which one
helped, whether one hurt, or whether you would do better with one and not the
other.

This is tedious and it is not negotiable. Two changes give you four combinations
and you have tested one of them.

There is one legitimate exception: when two settings are mechanically coupled and
cannot be varied independently. In this system, `retrieval.top_k` is the clearest
case — it sets both the retrieval pool and, through a hardcoded formula, how many
chunks reach the model. You cannot separate those. Note the coupling in your
record rather than pretending you changed one thing.

---

## Step 1: establish a baseline

A baseline is not just a number. It is a number plus everything required to
reproduce it.

**Pin these, and do not change them for the duration of your experiment:**

| What | Why |
|---|---|
| `--datasets` | Different questions, different scores. Obviously. |
| `--samples` | Sample count changes which questions are drawn. |
| `--seed` | Same seed, same questions. **This is the one people forget**, and forgetting it means your two runs asked different questions. |
| `--tier` | `generation` and `end_to_end` are not comparable. |
| Your corpus | If you ingest documents mid-experiment, an `end_to_end` comparison is void. |
| The judge model | Changing `active.eval` changes the grader, not the system. |

Run it, and give it a name you will recognize:

```bash
just eval --tier generation --datasets golden --samples 30 \
  --seed 42 --name "baseline-2026-08-01"
```

**Then record the configuration by hand.** This is not optional, and here is why.

### The config snapshot is partly fabricated

Every saved run contains a `config` block that looks like a record of what you
ran. Three of its fields are not: `retrieval_top_k`, `hybrid_search_enabled`, and
`contextual_retrieval_enabled` are **hardcoded constants** in the eval runner,
written into every run regardless of your actual configuration. The source
comments acknowledge this — the values are not available through the API the
runner queries.

The consequence is severe for this workflow: **a saved run does not reliably tell
you what configuration produced it**, and those three fields cover several of the
most common things you would want to tune. The dashboard's config-diff view
inherits the same problem — it can show "no change" between two runs that differed
in exactly these settings.

So keep your own record. A file, a spreadsheet, a comment in your notes — anything
that captures: what `config.yml` said, which run ID resulted, and what you were
testing. Without it you will have a directory of eight-character run IDs and no
idea what any of them mean.

This is logged as a defect in [`docs/suggestions.md`](../suggestions.md).

### Establish your noise floor

Before you change anything, **run the baseline a second time with nothing
different.**

This is the single most useful thing in this chapter, and almost nobody does it.

Two identical runs will not produce identical numbers. The judge is an LLM;
`temperature=0` reduces variation but does not eliminate it. Judge calls
occasionally fail and get excluded, changing which questions contributed. Latency
varies with load.

The difference between two identical runs is your **noise floor**: the amount a
metric moves for no reason at all. Any change smaller than that is not a result.

You do not need statistics to use this. If faithfulness moved 0.03 between two
runs of the same configuration, then a 0.02 improvement from your clever tuning
change is noise, and you can stop wondering. If the two identical runs came within
0.005 of each other, a 0.04 improvement is worth taking seriously.

Do this once per dataset and sample size. It takes one extra run and it calibrates
every judgement you make afterward.

---

## Step 2: change exactly one thing

Edit `config.yml`. **Wait for the change to take effect before running anything.**

The config loader checks the file's modification time on each access and reloads
when it changes. That means most edits apply without a restart — and it also means
**editing `config.yml` while an evaluation is running will change the system
mid-run.** The first fifty questions get the old configuration and the rest get
the new one, producing a result that describes neither. Make your edit, confirm
it, then start the run.

Some changes need more than a save:

| Change | Requires |
|---|---|
| Most `config.yml` edits | Nothing — auto-reload handles it |
| `active.embedding` | Restart **and a full re-ingest**. Existing vectors came from the old model. |
| Reranker model | Restart, and `just init` to pre-cache the new model |
| `chunk_size` / `chunk_overlap` | A code edit and an image rebuild — these are not in `config.yml` |
| Anything checked at startup | Restart |

Confirm the change landed:

```bash
just show-config-full
```

With two caveats you already know from chapter 3: it prints the *configured*
reranker `top_n`, which is not the value in use, and it omits the `database` and
`chat_memory` sections entirely.

---

## Step 3: re-measure identically

Same command, same everything, new name:

```bash
just eval --tier generation --datasets golden --samples 30 \
  --seed 42 --name "topk-20"
```

Things that quietly break comparability:

- **A different seed.** Different questions.
- **Documents added or removed** between runs, for `end_to_end`.
- **A different judge model.**
- **Running one comparison on a busy machine and the other on an idle one**, if
  you care about the latency numbers.
- **A `config.yml` edit mid-run**, as above.

There is no caching of query responses or judge calls, so every run genuinely
re-executes everything. That is good for validity — you are not comparing against
a stale cached result — and it means runs cost real time and real money each time.

---

## Step 4: decide whether the difference is real

Here is the actual work.

### Look at the right things, in the right order

**First, `sample_size` on every metric you care about.** If judge calls failed,
that metric's average covers fewer questions than you ran — and the ones that
succeeded are not a random subset. A metric with a materially reduced sample size
is not comparable to one without.

**Second, `error_count`.** Failed queries mean a partial run.

**Third, the metric you decided in advance to care about.** Which brings us to the
most important discipline in this chapter.

### Decide what you are measuring before you run

Write down, before starting, which metric would have to move for the change to be
worth keeping.

If you skip this, you will run the comparison, scan fifteen metrics, find the one
that moved most, and construct a story about why that was the real effect all
along. This feels like analysis. It is not.

The arithmetic is unforgiving. If you check twenty metrics and treat each as an
independent test at the conventional 5% threshold, the probability that at least
one moves "significantly" **by pure chance is about 64%** — you are more likely
than not to find a spurious winner. The eval framework reports roughly fifteen to
twenty metrics per run. **Choosing your metric after seeing the results makes a
false conclusion the likely outcome, not a rare accident.**

Pick one primary metric. Look at the others as secondary evidence — particularly
to check that nothing important got worse — but do not let a secondary metric
become the headline after the fact.

### Judge the size of the difference

With your noise floor from step 1, this is mostly arithmetic:

| Difference vs. your noise floor | Read it as |
|---|---|
| Smaller | Nothing happened. |
| Comparable | Nothing you can demonstrate. Do not act on it. |
| Several times larger, in the direction you predicted | A real effect, probably. |
| Large, and consistent across related metrics | A real effect. |

That last row deserves emphasis. **Coherence across metrics is strong evidence.**
If reranking improved `recall_at_5`, `mrr`, `ndcg_at_10`, and `faithfulness`
together, that is a mechanism doing what it should. If exactly one metric moved
while its close relatives sat still, be suspicious — that pattern is what noise
looks like.

### Sample size determines what you can detect

This is not a limitation of RAGBench; it is a property of measurement. Some
grounding, from the general statistics literature rather than from this system:

- Detecting a **large** effect with reasonable confidence takes on the order of
  **15–25** paired questions.
- Detecting a **moderate** effect takes roughly **34** paired questions.
- Detecting a **small** effect takes **150–200 or more**.

The shipped golden dataset has **ten entries.** At that size only a dramatic,
obvious change is distinguishable from chance. This is the strongest practical
argument for the golden-set work in chapter 5: below roughly 30 questions you are
not really measuring, and practitioner guidance converges on 100 or more.

There is also a specific warning in the research literature against the naive fix.
Computing a mean and a standard error and treating the result as a confidence
interval **substantially understates the true uncertainty** on evaluation sets
below a few hundred datapoints. The comfortable-looking error bar is the wrong
size. Do not compute one and trust it.

### Digging out the variance

The framework does compute a per-metric standard deviation across per-question
scores. It stores it in the run JSON and then never shows it to you in any
comparison — the CLI table omits it, the API deltas omit it, and the dashboard
shows it only for generation metrics.

You can retrieve it:

```bash
cat data/eval_runs/<run_id>_*.json | python3 -m json.tool | grep -A3 std_dev
```

A metric with a large standard deviation across questions needs a bigger
difference before you believe it. A metric where nearly every question scores the
same needs less.

### Weigh the cost

A change that improves faithfulness by 0.04 and doubles your latency is not
automatically good. Look at `latency_p95_ms` and `cost_per_query` alongside your
primary metric, remembering from chapter 4 that eval latency is inflated by
concurrency and cost is estimated from hardcoded rate tables.

The weighted score attempts this trade-off for you, with latency weighted at 0.05
and cost at 0.10. If those weights do not match your situation — and for a
latency-sensitive deployment they do not — ignore the weighted score and make the
trade-off yourself.

---

## Step 5: keep it, or revert it, and write it down

Three outcomes:

**Clear improvement, acceptable cost.** Keep it. Record the new baseline. Your
next experiment measures against this.

**No detectable difference.** This is a real result and worth recording. Reverting
to the simpler, cheaper, or faster of the two configurations is usually correct —
if contextual retrieval showed no measurable benefit on your corpus, turning it off
saves substantial ingestion cost for nothing.

**Worse.** Revert. Note what you tried, so you do not try it again in four months.

Write down what you did either way. A one-line record — *what changed, which run
IDs, what moved, what you decided* — takes seconds and is the only thing that stops
the sixth experiment from repeating the second.

---

## Confounds specific to this system

Collected, because each has cost somebody a wrong conclusion:

**The config snapshot is partly hardcoded.** Covered above. Keep your own record.

**`config.yml` auto-reloads on modification.** An edit during a run changes the
system mid-run.

**`reranker.top_n` does nothing.** If you "tuned" it and saw no effect, that is
because the value is ignored — the reranker's output size derives from
`retrieval.top_k`.

**`eval.abstention_phrases` does nothing** for eval scoring. The metrics use a
hardcoded list.

**Citation metrics measure retrieval by default.** With `eval.citation_scope` at
its default of `retrieved`, every retrieved chunk counts as a citation. And on a
dataset with no gold passages — including the golden set — citation precision and
recall both return a meaningless 1.0.

**Retrieval metrics are meaningless in the `generation` tier**, because retrieval
does not run.

**The judge may favour its own family.** The shipped defaults use OpenAI models
for both generation and judging. Judges are documented in the research literature
to score outputs from their own model family more favourably, even when the models
are not identical. If you are comparing an OpenAI generator against a local one
using an OpenAI judge, that comparison is not neutral. Using a judge from a
different vendor than the generator is the standard mitigation.

**Latency is measured under eval concurrency**, not under user conditions.

---

## A worked loop

Deciding whether the reranker earns its latency. **The numbers below are
illustrative — they are not measurements from this system.**

**Set up.** 40 questions from `ragbench`, seed pinned at 42, **`end_to_end`
tier** — this matters, because reranking sits in the retrieval path, and the
`generation` tier bypasses retrieval entirely. Testing a reranker change in the
`generation` tier would measure nothing at all.

Primary metric chosen in advance: `faithfulness`. Secondary: `latency_p95_ms`.
Decision rule written down beforehand — keep reranking if faithfulness improves by
more than twice the noise floor without more than doubling p95 latency.

**Noise floor.** Two identical baseline runs. Faithfulness comes back at 0.81 and
0.83 — a spread of 0.02. So the noise floor is about 0.02, and nothing below 0.04
will be believed.

**Baseline.** `reranker.enabled: true`. Faithfulness 0.82, p95 1400 ms. Run
recorded, config written down by hand.

**Change one thing.** `reranker.enabled: false`. Save, confirm with
`just show-config-full`.

**Re-measure.** Same seed, same dataset, same sample count.

**Compare.**

```bash
just eval-compare <baseline_id> <no_rerank_id>
```

Faithfulness 0.74, p95 900 ms.

**Decide.** Faithfulness dropped 0.08 — four times the noise floor, and in the
predicted direction. `recall_at_5` and `mrr` dropped alongside it, which is the
coherent pattern a real retrieval effect should produce rather than an isolated
mover. Sample sizes matched the question count on both runs, so no judge failures
distorted either.

Latency improved by 500 ms, which is genuine. But the decision rule was set in
advance: a 0.08 faithfulness loss exceeds what that latency saves in this
deployment.

**Keep reranking.** Record: *reranker off, 40q golden, seed 42 — faithfulness
0.82 → 0.74, p95 1400 → 900 ms. Kept reranking. Runs `a1b2c3d4` / `e5f6a7b8`.*

Note what made this decision defensible. It was not the tooling — the tooling
printed two numbers. It was the noise floor, the metric chosen in advance, the
coherence check across related metrics, and the sample-size check.

---

## Recommendations (not currently implemented)

Practices RAGBench does not support today. Listed separately so they are not
mistaken for features.

- **Paired bootstrap confidence intervals.** For a paired design like this one,
  resampling the per-question score differences with replacement and taking the
  2.5th and 97.5th percentiles gives an honest interval on the mean difference,
  without assuming normality. This is the standard tool for exactly this problem
  and would be a modest addition to `compare`.
- **McNemar's test for binary metrics.** For hit/miss metrics like recall@k, the
  informative quantity is the number of questions that *flipped* between
  configurations and in which direction — not the aggregate rate.
- **A minimum sample size before claiming a difference**, with underpowered
  comparisons flagged as indicative only.
- **A multiple-comparisons correction**, or at minimum surfacing the fact that
  scanning twenty metrics makes a spurious winner more likely than not.
- **Cross-family judging.** Using a judge from a different vendor than the
  generation model is the standard mitigation for self-preference bias.

These are recorded as concrete proposals in
[`docs/suggestions.md`](../suggestions.md).

---

**Next:** [7. Experiment cookbook](07-experiment-cookbook.md) — the loop applied to
specific questions.

See also [11. Limits and caveats](11-limits-and-caveats.md) for what none of this
can establish.
