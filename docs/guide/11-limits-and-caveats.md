# 11. Limits and caveats

An honest account of what the evaluation apparatus can and cannot establish.

The failure mode for a system like this is not that it produces no numbers — it is
that it produces numbers that feel more authoritative than they are. A dashboard
showing 0.83 invites confidence the measurement does not support. **If you read one
chapter before presenting results to someone else, read this one.**

None of what follows means the measurements are worthless. It means they are
evidence of a particular strength, and knowing that strength is what lets you use
them well.

---

## What a good score does and does not prove

**A good score means:** on this question set, with this corpus, under this
configuration, as scored by this judge, at this moment, the system produced answers
satisfying these particular criteria.

| It does not mean | Because |
|---|---|
| The system will answer *your users'* questions well | Those are different questions, asked differently, often about parts of the corpus your set does not touch |
| It will still score this way next month | The corpus drifts, providers update models behind stable names, and your set ages |
| The configuration is optimal | It beat the alternatives you happened to test. The best one may be untried. |
| The answers are correct | The judge found them plausible against the criteria in its prompt. On specialist material those differ noticeably. |

---

## Statistical limits

### Significance testing exists, but cannot rescue a small sample

`compare` and `GET /eval/runs/compare` report a **paired bootstrap 95% confidence
interval** on every metric both runs scored, over their common questions. Binary
metrics also get **McNemar's exact test** with discordant counts, so you see how
many questions flipped and which way. Benjamini-Hochberg is applied across the
metric family, and comparisons below 100 paired questions are flagged
`underpowered`. The bootstrap uses a fixed seed, so the same two runs always compare
identically.

What that fixes: a difference across 10 questions no longer renders identically to
one across 1000, and "the biggest mover" is no longer a verdict.

What it does not fix:

- **A wide interval is still a wide interval.** The test tells you your 10-question
  comparison is uninformative; it does not make it informative.
- **Only metrics with per-question scores can be tested.** Aggregate-only metrics
  such as P50 latency, and runs produced before the framework recorded per-question
  data, are listed as skipped rather than given invented statistics.
- **The judge's own variance is not in the interval.** The bootstrap resamples
  questions, not judge calls. Re-judging identical answers can move a score; that
  noise is invisible here — and judge caching is on by default, which hides it
  further. Chapter 6's noise-floor technique, run with `--no-judge-cache`, is what
  catches it.

### Sample sizes are usually too small

For a paired test at the conventional 5% threshold and 80% power:

| Effect size | Paired questions needed |
|---|---|
| Large (d = 0.8) | ~15 |
| Moderate (d = 0.5) | ~34 |
| Small (d = 0.2) | ~199 |

The shipped golden dataset has **ten entries.** Practitioner guidance converges on
100 or more. Most tuning changes produce small or moderate effects, so **most
comparisons you run on a small set will be underpowered** — `compare` now says so
explicitly, but saying so is all it can do.

The obvious workaround is itself unsound: computing a mean and standard error and
treating it as a confidence interval **substantially understates true uncertainty**
on evaluation sets below a few hundred datapoints. The bootstrap exists to avoid
that assumption.

### Checking many metrics manufactures false winners

Each run reports roughly fifteen to twenty metrics. Testing twenty at the 5%
threshold gives about a **64% chance** that at least one moves "significantly" by
chance (1 − 0.95²⁰).

`compare` applies Benjamini-Hochberg and prints that arithmetic under the table. A
metric marked `nominal (fails BH)` had an interval excluding zero but did not
survive correction — a lead to re-run, not a result.

More likely than not, a spurious winner is available in every comparison you run.
The only defence is choosing your primary metric before you look, which is
discipline, not tooling.

---

## Judge limits

Three of the most-watched metrics — faithfulness, correctness, relevancy — come
from a single LLM reading the answer and assigning a score.

**One judge, no ensemble, no agreement check.** No second judge to disagree, no
majority vote, no inter-rater reliability figure. When the judge is wrong, nothing
catches it.

**Documented biases apply.** The LLM-as-judge literature names three recurring
failure modes: position bias, verbosity bias (longer answers score better
independent of quality), and self-preference — judges scoring their own model
family more favourably.

That last is directly relevant: the shipped configuration uses OpenAI models for
**both** generation and judging. Self-preference is documented to extend across a
model *family*, not only the identical model, and reported magnitudes swing widely
in both directions across model pairs — so no correction factor applies. It is a
risk factor, not a fixed offset. The runner detects the pairing and records a
warning on the run, but detecting is not correcting.

**Calibration is uneven.**

| Prompt | Check | Strength |
|---|---|---|
| Faithfulness, context relevance | Against RAGBench ground-truth annotations — agreement plus RMSE | Strong |
| `answer_correctness`, `answer_relevancy` | Discrimination test: score each response against its own reference and a deliberately mismatched one, report how often the matched pair ranked higher | Weak — accuracy near 100% only means the prompt is not broken. It is a floor, not evidence that mid-range scores track human judgement. |

**The rubric compresses.** Judge prompts describe a 0.0 / 0.5 / 1.0 scale; the
parser accepts any float and clamps. Scores cluster at the rubric points, limiting
the resolution available for small differences — a constraint that compounds the
sample-size problem.

**The judge is not a domain expert.** On specialist content it assesses
plausibility and internal consistency, not correctness. A confidently wrong answer
in a domain the judge does not know often scores well.

**Judge failures shrink your sample silently.** Failed calls are excluded rather
than scored zero — right behaviour, but a metric's `sample_size` can fall well
below your question count, and the survivors are not a random subset. Check
`sample_size`. Nothing warns you.

---

## Dataset limits

**Public benchmarks are not your corpus.** RAGBench, HotpotQA, MS MARCO, QASPER,
and SQuAD 2.0 tell you the pipeline functions and let you compare configurations on
a fixed task. Their documents are not your documents; their questions are not your
questions.

**Your golden set encodes your assumptions.** It contains the questions you thought
to write. A perfect score on questions you wrote is evidence about questions you
wrote.

**The golden set measures retrieval only if you annotate it** — and even then, only
partly. Adding `gold_passages` (or `gold_doc_ids`) makes recall, precision, MRR,
NDCG and the citation metrics measurable. Without annotations they report **`n/a`**,
not a number; an earlier version returned 1.0 for citation precision and recall,
displaying perfect scores that meant nothing. But the golden set supports only the
`generation` tier, so annotations measure how well the pipeline *uses* the right
passages, not whether retrieval *finds* them.

**Retrieval is not measured in the `generation` tier**, because retrieval does not
run.

**Citation metrics measure retrieval by default.** With `eval.citation_scope` at
`retrieved`, every retrieved chunk counts as a citation — re-measuring retrieval
with different arithmetic, not assessing what the model chose to cite.

---

## Coverage limits

| Not covered | Consequence |
|---|---|
| **Everything is single-turn** | The condensation step that rewrites follow-up questions is never exercised, and it is a genuine source of failure in real conversational use. A system that scores well here can still handle follow-ups badly. |
| **Latency is measured under eval concurrency** | Runs execute many queries at once; a real user runs one. Useful for comparing runs, misleading about user experience. |
| **Cost is estimated from hardcoded rate tables** | Two such tables in different services, drifted apart. Useful for comparison, not for forecasting a bill. |
| **Streaming is not evaluated** | Evaluations use the non-streaming path. The PII output guardrail can only audit on the streaming path, never block. |
| **PII masking's quality cost is not measured by default** | You must construct that comparison yourself (chapter 8). |
| **Nothing measures the corpus** | If the answer is not in your documents, no configuration finds it. Uniformly low scores with high abstention usually indicate a coverage gap, and no metric distinguishes the two. |

---

## Reproducibility limits

**What is recorded.** The saved config snapshot reads the models and retrieval
settings live from the RAG server, so `retrieval_top_k`, `hybrid_search_enabled`,
and `contextual_retrieval_enabled` reflect what actually ran. When the server does
not report them they record as `Unknown` rather than a guess, and query caching is
refused for that run. Every run is also copied to `data/eval_runs/backup/`.

**What is not.**

- **Configuration can change mid-run.** The config file auto-reloads on
  modification, so editing during an evaluation applies the change partway through,
  yielding a result describing neither configuration.
- **Model providers are not stable.** A cloud model behind a fixed name can change
  underneath you, and nothing records the provider-side version. A comparison today
  and one in three months may not measure the same system.
- **Nothing is deterministic end to end.** `temperature=0` reduces variation for
  both generator and judge without eliminating it.
- **Judge caching is on by default**, so a re-run is not an independent measurement
  unless you pass `--no-judge-cache`.
- **Chunk size and overlap are not in `config.yml`** and are not recorded as
  anything you set — they are code constants, so a run that used different values
  is only distinguishable by your own notes.

---

## What this system is genuinely good for

The list above is long, so it is worth being equally clear about the strengths.

| Strength | Why it matters |
|---|---|
| **Detecting large regressions** | If a change makes things substantially worse you will see it, before your users do. This alone justifies the apparatus. |
| **Comparing configurations that differ a lot** | Reranking on/off, a 4B local model vs a frontier cloud model, hybrid vs vector-only — effects large enough to see clearly at realistic sample sizes |
| **Measuring retrieval honestly and cheaply** | No judge, deterministic, the most trustworthy numbers here. Since most RAG quality problems are retrieval problems, this is more valuable than it sounds. |
| **Making cost and latency trade-offs visible** | Even approximate figures beat intuition when deciding whether a quality gain justifies a latency cost |
| **Enforcing discipline** | A fixed question set and a repeatable procedure stop you tuning on vibes and remembering yesterday's answers as better than they were |
| **Catching hallucination behaviour** | Faithfulness and the abstention false negative rate measure whether the system invents answers — something ad-hoc testing reliably misses |

---

## How to report results honestly

- **State the sample size.** Every time. It determines whether a difference means
  anything.
- **State the dataset and tier**, so it is clear what was and was not exercised.
- **Quote the confidence interval, not just the delta** — and say when a comparison
  was flagged `underpowered`.
- **Say whether you established a noise floor**, and what it was.
- **Say which metric you chose in advance**, and resist promoting a
  chosen-afterward metric to headline.
- **Report what got worse**, not only what improved.
- **Do not present the weighted score as an overall quality figure.** It embeds a
  weighting of six objectives, with latency at 0.05 and cost at 0.10 by default —
  and if you edited `eval.scoring`, say so, because it makes earlier runs
  incomparable.
- **Do not present citation metrics from an unannotated run.** They are `n/a` by
  definition and mean nothing.
- **Say "no detectable difference"** rather than "no difference" when a comparison
  comes back flat. Those are different claims, and at these sample sizes only the
  first is supportable.

---

## Still missing

Recorded as concrete proposals in [`docs/suggestions.md`](../suggestions.md).

- **Ensemble judging** with inter-rater agreement reporting.
- **Multi-turn evaluation**, so question condensation is exercised.
- **Per-question significance in the dashboard.** The API returns it; the analytics
  UI still shows point deltas only.
- **Configurable chunk size and overlap**, and configurable RRF source weights.

---

**Back to:** [Guide index](INDEX.md)

Engineering detail: [`docs/internal/eval-framework.md`](../internal/eval-framework.md).
