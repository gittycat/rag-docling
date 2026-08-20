# 6. The tuning workflow

The loop: measure a baseline, change one thing, measure again, decide whether the
change was real and worth it. Every part is easy except the deciding.

The tooling now helps with the deciding. `compare` reports paired bootstrap
confidence intervals, McNemar's test on binary metrics, and a Benjamini-Hochberg
correction across the metric family (chapter 5). That removes the worst failure
mode — treating a raw delta as a result. It does not remove your judgement: a
statistic on ten questions is still uninformative, and the tooling cannot choose
your primary metric for you.

---

## Why one variable at a time

Change the embedding model and `top_k` together, see the score improve, and you
have learned that the pair beats the pair. You have not learned which one helped,
whether one hurt, or whether one alone would do better. Two changes give four
combinations and you have tested one.

Tedious, and not negotiable.

---

## Step 1: establish a baseline

A baseline is a number plus everything needed to reproduce it.

**Pin these for the duration of the experiment:**

| What | Why |
|---|---|
| `--datasets` | Different questions, different scores |
| `--samples` | Sample count changes which questions are drawn |
| `--seed` | Same seed, same questions. **The one people forget** — forgetting it means your two runs asked different questions. |
| `--tier` | `generation` and `end_to_end` are not comparable |
| Your corpus | Ingesting documents mid-experiment voids an `end_to_end` comparison |
| The judge model | Changing `active.eval` changes the grader, not the system |
| `eval.scoring` | Editing weights or thresholds is a scoring change; runs across it are not comparable |

```bash
just eval --tier generation --datasets golden --samples 30 \
  --seed 42 --name "baseline-2026-08-20"
```

The saved run records the models and the retrieval settings it read live from the
RAG server — `retrieval_top_k`, `hybrid_search_enabled`,
`contextual_retrieval_enabled` and the rest are captured from
`GET /metrics/system`, not fabricated. If the server does not report its retrieval
configuration, those fields record as `Unknown` rather than a guess, and query
caching is refused for that run.

Still keep a short note of what you were testing. The config snapshot tells you
what the system was; it does not tell you what question you were asking.

### Establish your noise floor

**Run the baseline a second time with nothing changed.** This is the single most
useful thing in this chapter, and almost nobody does it.

Two identical runs will not produce identical numbers. The judge is an LLM;
`temperature=0` reduces variation without eliminating it. Judge calls occasionally
fail and get excluded, changing which questions contributed. Latency varies with
load.

That difference is your **noise floor** — how much a metric moves for no reason at
all. Anything smaller is not a result.

```bash
just eval --tier generation --datasets golden --samples 30 \
  --seed 42 --no-judge-cache --name "baseline-repeat"
```

**Use `--no-judge-cache` here.** Judge-call caching is on by default, so a plain
re-run reuses identical judge calls and reports an artificially low noise floor —
it measures everything *except* the judge variance you are trying to see.

The noise floor catches run-to-run variance that the paired significance test
cannot: a paired test compares two runs and treats each as a fixed measurement.
Do this once per dataset and sample size; it calibrates every later judgement.

---

## Step 2: change exactly one thing

Edit `config.yml`. **Wait for the change to land before running anything.**

The loader reloads on modification, so most edits apply without a restart — and
that also means **editing `config.yml` during a run changes the system mid-run.**
The first fifty questions get the old configuration and the rest get the new one,
producing a result that describes neither.

| Change | Requires |
|---|---|
| Most `config.yml` edits | Nothing — auto-reload handles it |
| `active.embedding` | Restart **and a full re-ingest** — existing vectors came from the old model |
| Reranker model | Restart, plus `just init` to pre-cache the new model |
| `chunk_size` / `chunk_overlap` | A code edit and image rebuild — these are not in `config.yml` |
| Anything checked at startup | Restart |

Confirm it landed:

```bash
just show-config-full
```

It prints the effective reranker `top_n` alongside the configured value. It omits
the `database` and `chat_memory` sections — read `config.yml` for those.

---

## Step 3: re-measure identically

```bash
just eval --tier generation --datasets golden --samples 30 \
  --seed 42 --name "topn-10"
```

Things that quietly break comparability:

- A different seed — different questions.
- Documents added or removed between `end_to_end` runs.
- A different judge model, or an edited `eval.scoring` block.
- A `config.yml` edit mid-run.
- `--cache-queries` after re-ingesting — the cache key does not cover the corpus.
- Running one comparison on a busy machine and the other on an idle one, if you
  care about latency.

---

## Step 4: decide whether the difference is real

### Look at the right things, in the right order

1. **`sample_size` on every metric you care about.** Judge failures shrink it, and
   the questions that survived are not a random subset. A metric with a materially
   reduced sample size is not comparable to one without.
2. **`error_count`.** Failed queries mean a partial run.
3. **The metric you decided in advance to care about.**

### Decide what you are measuring before you run

Write down, before starting, which metric would have to move for the change to be
worth keeping.

Skip this and you will scan fifteen metrics, find the biggest mover, and construct
a story about why that was the real effect. This feels like analysis. It is not.

The arithmetic is unforgiving. Testing twenty metrics at the conventional 5%
threshold gives a **64% chance** that at least one moves "significantly" by pure
chance (1 − 0.95²⁰). Each run reports roughly fifteen to twenty metrics.
**Choosing your metric after seeing the results makes a false conclusion the likely
outcome, not a rare accident.**

`compare` applies Benjamini-Hochberg across the metric family and marks anything
that fails it `nominal (fails BH)`. Treat those as leads to re-run, not results.

### Read the interval, not the delta

```bash
just eval-compare <baseline_id> <changed_id>
```

| What you see | What it means |
|---|---|
| CI excludes zero, marked `significant` | The comparison established a difference |
| CI spans zero | No difference established, however large the delta looks |
| `underpowered` | Fewer than 100 paired questions. The interval is real but wide; treat as indicative. |
| `nominal (fails BH)` | Excluded zero, did not survive multiple-comparison correction |
| *not tested* | No per-question data — aggregate metrics like P50 latency, or older runs |

Cross-check against your noise floor. The paired test cannot see run-to-run
variance; your noise floor can. If faithfulness moves 0.03 between two *identical*
runs, be sceptical of a 0.02 "significant" improvement no matter what the interval
says.

### Coherence across metrics is strong evidence

If reranking improved `recall_at_5`, `mrr`, `ndcg_at_10`, and `faithfulness`
together, that is a mechanism doing what it should. If exactly one metric moved
while its close relatives sat still, be suspicious — that pattern is what noise
looks like.

### Sample size determines what you can detect

A property of measurement, not a limitation of RAGBench. For a paired test at the
conventional 5% threshold and 80% power:

| Effect size | Paired questions needed |
|---|---|
| Large (d = 0.8) | ~15 |
| Moderate (d = 0.5) | ~34 |
| Small (d = 0.2) | ~199 |

The shipped golden dataset has **ten entries.** At that size only a dramatic change
is distinguishable from chance. Below roughly 30 questions you are not really
measuring; practitioner guidance converges on 100 or more, which is why `compare`
flags anything below that as underpowered.

Do not compute a mean and standard error and treat it as a confidence interval.
On evaluation sets below a few hundred datapoints that **substantially understates
true uncertainty** — the comfortable-looking error bar is the wrong size. The
bootstrap in `compare` exists precisely to avoid that assumption.

### Digging out the variance

The framework computes a per-metric standard deviation across per-question scores.
The dashboard shows it in the metric breakdown; the CLI comparison table does not.

```bash
python3 -m json.tool < data/eval_runs/<run_id>_*.json | grep -A3 std_dev
```

A metric with a large standard deviation across questions needs a bigger difference
before you believe it.

### Weigh the cost

A change that improves faithfulness by 0.04 and doubles latency is not
automatically good. Check `latency_p95_ms` and `cost_per_query` alongside your
primary metric, remembering that eval latency is inflated by concurrency and cost
comes from hardcoded rate tables.

The weighted score attempts this trade-off for you. If its weights do not match
your situation, edit `eval.scoring` — but do that *before* the experiment, not
after seeing results, and remember it makes earlier runs incomparable.

---

## Step 5: keep it, revert it, and write it down

| Outcome | Action |
|---|---|
| **Clear improvement, acceptable cost** | Keep it. Record the new baseline; your next experiment measures against this. |
| **No detectable difference** | A real result. Revert to the simpler, cheaper, or faster configuration — if contextual retrieval showed no measurable benefit, turning it off saves substantial ingestion cost for nothing. |
| **Worse** | Revert. Note what you tried, so you do not try it again in four months. |

A one-line record — *what changed, which run IDs, what moved, what you decided* —
takes seconds and stops the sixth experiment from repeating the second.

---

## Confounds specific to this system

| Confound | Effect |
|---|---|
| **`config.yml` auto-reloads** | An edit during a run changes the system mid-run |
| **Judge caching is on by default** | A re-run reuses identical judge calls, hiding judge variance. Use `--no-judge-cache` for noise-floor runs. |
| **Citation metrics measure retrieval by default** | With `eval.citation_scope: retrieved`, every retrieved chunk counts as a citation |
| **Retrieval metrics are meaningless in `generation` tier** | Retrieval does not run |
| **The judge may favour its own family** | Shipped defaults use OpenAI for both generation and judging. The runner warns and records this on the run; using a judge from a different vendor is the standard mitigation. |
| **Latency is measured under eval concurrency** | Not under user conditions |
| **Changing `eval.abstention_phrases` is a scoring change** | Narrowing the list makes the model look worse at abstaining without anything having changed |

---

## A worked loop

Deciding whether the reranker earns its latency. **The numbers below are
illustrative — they are not measurements from this system.**

**Set up.** 40 questions from `ragbench`, seed 42, **`end_to_end` tier** — this
matters, because reranking sits in the retrieval path and the `generation` tier
bypasses retrieval entirely. Primary metric chosen in advance: `faithfulness`.
Secondary: `latency_p95_ms`. Decision rule written down beforehand: keep reranking
if faithfulness improves by more than twice the noise floor without more than
doubling p95 latency.

**Noise floor.** Two identical baseline runs with `--no-judge-cache`. Faithfulness
comes back 0.81 and 0.83 — a spread of 0.02. Nothing below 0.04 will be believed.

**Baseline.** `reranker.enabled: true`. Faithfulness 0.82, p95 1400 ms.

**Change one thing.** `reranker.enabled: false`. Save, confirm with
`just show-config-full`.

**Re-measure.** Same seed, dataset, sample count.

```bash
just eval-compare <baseline_id> <no_rerank_id>
```

Faithfulness 0.74, p95 900 ms. The interval on the faithfulness delta is
`[-0.121, -0.043]`, excluding zero and surviving BH. It is flagged `underpowered`
at n = 40 — real, but wider than it would be at 100 questions.

**Decide.** Faithfulness dropped 0.08 — four times the noise floor, in the
predicted direction, with an interval that excludes zero. `recall_at_5` and `mrr`
dropped alongside it: the coherent pattern a real retrieval effect produces rather
than an isolated mover. Sample sizes matched the question count on both runs, so no
judge failures distorted either.

Latency improved by 500 ms, which is genuine. But the decision rule was set in
advance, and a 0.08 faithfulness loss exceeds what that latency saves here.

**Keep reranking.** Record: *reranker off, 40q ragbench, seed 42 — faithfulness
0.82 → 0.74 (CI [-0.121, -0.043], underpowered), p95 1400 → 900 ms. Kept
reranking. Runs `a1b2c3d4` / `e5f6a7b8`.*

What made this defensible was not the interval alone. It was the noise floor, the
metric chosen in advance, the coherence check, and the sample-size check.

---

## Still not available

- **Ensemble judging** with inter-rater agreement. One judge scores every
  generation metric; nothing measures how much a second would have disagreed.
- **Multi-turn evaluation**, so question condensation is exercised.
- **Significance in the dashboard.** The API returns it; the analytics UI shows
  point deltas only. Use the CLI.

Recorded as proposals in [`docs/suggestions.md`](../suggestions.md).

---

**Next:** [7. Experiment cookbook](07-experiment-cookbook.md) — the loop applied to
specific questions.

See also [11. Limits and caveats](11-limits-and-caveats.md).
