# 11. Limits and caveats

An honest account of what the evaluation apparatus in this system can and cannot
establish.

This chapter exists because the failure mode for a system like this is not that it
produces no numbers — it is that it produces numbers that feel more authoritative
than they are. A dashboard with a weighted score of 0.83 invites a confidence the
underlying measurement does not support. If you read only one chapter of this
guide before presenting results to someone else, read this one.

None of what follows means the measurements are worthless. It means they are
evidence of a particular strength, and knowing that strength is what lets you use
them well.

---

## What a good score does and does not prove

**A good score means:** on this specific set of questions, with this corpus, under
this configuration, as scored by this judge, at this moment, the system produced
answers that satisfied these particular criteria.

**It does not mean** the system will answer *your users'* questions well. Those
are different questions, asked differently, often about parts of the corpus your
question set does not touch.

**It does not mean** the system will still score this way next month. The corpus
drifts, model providers update models behind stable names, and your evaluation set
ages.

**It does not mean** the configuration is optimal. It means it beat the
alternatives you happened to test. The best configuration may be one you never
tried.

**It does not mean** the answers are correct. It means the judge found them
plausible against the criteria in its prompt. On specialist material those are
noticeably different things.

---

## Statistical limits

This is the most serious category, and it deserves to be first.

### There is no significance testing anywhere

The `compare` command reports raw arithmetic differences. The API reports raw
arithmetic differences. The dashboard reports raw arithmetic differences. **No
confidence interval, no paired test, no variance accounting exists anywhere in the
comparison path.**

The practical consequence: the tooling cannot distinguish a real improvement from
noise, and it does not indicate which it is showing you. A difference of 0.03
across 10 questions renders identically to a difference of 0.03 across 1000.

The per-metric standard deviation *is* computed and stored in the run JSON — and
then omitted from every comparison view. The information exists; nothing surfaces
it where you would use it.

Chapter 6's noise-floor technique — running the same configuration twice and
observing how much it moves on its own — is a workaround, not a substitute. Use
it. But know that it is a rough empirical guard, not a statistical guarantee.

### Sample sizes are usually too small to conclude anything

Detecting a **large** effect takes on the order of 15–25 paired questions. A
**moderate** effect takes roughly 34. A **small** effect takes 150–200 or more.

The shipped golden dataset has **ten entries**. At that size, only a dramatic
change is distinguishable from chance. Practitioner guidance for golden sets
converges on 100 or more, and one commonly cited figure puts 250 pairs at roughly
±0.04 confidence-interval width on a proportion.

Most tuning changes produce small or moderate effects. **Most comparisons you run
on a small set will be underpowered, and the tooling will not tell you so.**

And the obvious workaround is itself unsound: computing a mean and standard error
and treating it as a confidence interval **substantially understates true
uncertainty** on evaluation sets below a few hundred datapoints. This is a
documented result, not a quibble. The comfortable-looking error bar would be the
wrong size.

### Checking many metrics manufactures false winners

Each run reports roughly fifteen to twenty metrics. If you scan them and declare
the biggest mover the winner, the arithmetic works against you: testing twenty
metrics at the conventional 5% threshold gives about a **64% chance** that at
least one moves "significantly" by pure chance.

More likely than not, a spurious winner is available in every comparison you run.
The only defence is choosing your primary metric before you look — which is
discipline, not tooling.

---

## Judge limits

Three of the most-watched metrics — faithfulness, correctness, relevancy — come
from a single LLM reading the answer and assigning a score.

**One judge, no ensemble, no agreement check.** There is no second judge to
disagree with, no majority vote, and no inter-rater reliability figure. When the
judge is wrong, nothing catches it.

**Documented biases apply.** The research literature on LLM-as-judge names three
recurring failure modes: position bias, verbosity bias (longer answers score
better independent of quality), and self-preference — judges scoring outputs from
their own model family more favourably.

That last one is directly relevant to the shipped configuration, which uses
OpenAI models for **both** generation and judging. Self-preference is documented
to extend across a model *family*, not only to the identical model. The magnitude
varies enormously across model pairs and datasets — reported swings run in both
directions across a wide range — so no single correction factor applies. It is a
known risk factor, not a fixed offset.

The practical implication: **comparisons between models from different families,
judged by a model from one of them, are not neutral.** Recipe 2 in chapter 7 says
so explicitly.

**Calibration is partial.** The `calibrate` command checks the judge against
ground-truth annotations for faithfulness and context relevance. `answer_correctness`
and `answer_relevancy` are **never checked against ground truth at all.** For
those two metrics you have no evidence the judge agrees with a human on anything.

**The rubric compresses.** Judge prompts describe a 0.0 / 0.5 / 1.0 scale. The
parser accepts any float and clamps it. Scores cluster around the rubric points,
which limits the resolution available for detecting small differences — a
constraint that compounds the sample-size problem.

**The judge is not a domain expert.** On specialist content it is assessing
plausibility and internal consistency, not correctness. A confidently wrong answer
in a domain the judge does not know will often score well.

**Judge failures shrink your sample silently.** Failed calls are excluded from
averages rather than scored zero — the right behaviour, as chapter 4 explains, but
it means a metric's `sample_size` can fall well below your question count, and the
questions that survived are not a random subset. Check `sample_size`. Nothing
warns you.

---

## Dataset limits

**Public benchmarks are not your corpus.** RAGBench, HotpotQA, MS MARCO, QASPER,
and SQuAD 2.0 tell you the pipeline functions and let you compare configurations
on a fixed task. They tell you nothing about whether the system answers questions
about *your* documents. Their documents are not your documents; their questions
are not your questions.

**Your golden set encodes your assumptions.** It contains the questions you
thought to write. Real users ask things you did not anticipate, phrased in ways you
did not consider. A perfect score on questions you wrote is evidence about
questions you wrote.

**The golden set cannot measure retrieval at all.** The loader never populates
gold passages, so recall, precision, MRR, and NDCG have nothing to compare
against. Worse, citation precision and recall are *defined* to return **1.0** when
no gold passages exist — so a golden-set run displays perfect citation scores that
mean nothing. This is the single most misleading number the system can show you.

**Retrieval is not measured in the `generation` tier**, because retrieval does not
run.

**Citation metrics measure retrieval by default.** With `eval.citation_scope` at
its default of `retrieved`, every retrieved chunk counts as a citation. Under that
setting these metrics are re-measuring retrieval with different arithmetic, not
assessing what the model chose to cite.

**One dataset is documented as broken.** The `qasper` loader is noted in the
source as failing with recent versions of the `datasets` library.

---

## Coverage limits

**Everything is single-turn.** Every evaluation asks one question and scores one
answer. The condensation step that rewrites follow-up questions into standalone
ones is **never exercised** — and it is a genuine source of failure in real
conversational use. A system that scores well here can still handle follow-ups
badly, and you would not know.

**Latency is measured under evaluation conditions.** Runs execute many queries
concurrently; a real user runs one. The reported figures are useful for comparing
runs against each other and misleading as a statement about user experience.

**Cost is estimated from hardcoded rate tables** in the source — not a live
pricing feed. There are two such tables in different services and they have
drifted apart. Useful for comparison, not for forecasting a bill.

**Streaming is not evaluated.** Evaluations use the non-streaming path. The
streaming path differs in ways that matter — most notably, the PII output
guardrail can only audit there, never block, because tokens are already sent.

**PII masking's quality cost is not measured by default.** You have to construct
that comparison yourself, as chapter 8 describes.

**Nothing measures the corpus.** If the answer is not in your documents, no
configuration finds it. Uniformly low scores with high abstention usually indicate
a coverage gap, not a tuning problem — and no metric here distinguishes the two.

---

## Reproducibility limits

**The saved config snapshot is partly fabricated.** `retrieval_top_k`,
`hybrid_search_enabled`, and `contextual_retrieval_enabled` are hardcoded
constants written into every run record regardless of actual configuration. Those
three cover several of the most commonly tuned settings.

This means **a stored run does not reliably record what produced it.** The
dashboard's config-diff inherits the flaw and can report "no change" between runs
that differed precisely in these settings. Keep your own record; chapter 6 says so
repeatedly for this reason.

**Configuration can change mid-run.** The config file auto-reloads on
modification, so editing it during an evaluation applies the change partway
through, yielding a result describing neither configuration.

**Model providers are not stable.** A cloud model behind a fixed name can change
underneath you. A comparison run today and a comparison run in three months may
not be measuring the same system, and nothing records the provider-side version.

**Nothing is deterministic end to end.** `temperature=0` reduces variation without
eliminating it, for both the generator and the judge.

**Results have no backup.** Runs are flat JSON files. The index is rebuilt by
scanning the directory at startup. Delete a file and the run is gone.

**Several config keys silently do nothing** — `reranker.top_n`,
`eval.abstention_phrases`, `database.max_connections`, and three PII settings. An
experiment that "tuned" one of these measured nothing while appearing to work.
Chapter 3 lists them.

---

## What this system is genuinely good for

The list above is long, so it is worth being equally clear about the real
strengths. They are not small.

**Detecting large regressions.** If a change makes things substantially worse, you
will see it, and you will see it before your users do. This alone justifies the
apparatus.

**Comparing configurations that differ a lot.** Reranking on versus off, a 4B
local model versus a frontier cloud model, hybrid search versus vector-only —
these produce effects large enough to see clearly at realistic sample sizes.

**Measuring retrieval, honestly and cheaply.** Retrieval metrics need no judge,
are deterministic, and are the most trustworthy numbers the system produces. Since
most RAG quality problems are retrieval problems, this is more valuable than it
sounds.

**Making cost and latency trade-offs visible.** Even approximate figures beat
intuition when deciding whether a quality gain justifies a latency cost.

**Enforcing discipline.** The greatest practical value is often procedural: a
fixed question set and a repeatable procedure stop you from tuning on vibes and
remembering yesterday's answers as better than they were.

**Catching hallucination behaviour.** Faithfulness and the abstention false
negative rate measure something genuinely important — whether the system invents
answers — and measure it in a way ad-hoc testing reliably misses.

---

## How to report results honestly

If you are showing these numbers to someone else:

- **State the sample size.** Every time. It is the first thing that determines
  whether a difference means anything.
- **State the dataset and tier**, so it is clear what was and was not exercised.
- **Say whether you established a noise floor**, and what it was.
- **Say which metric you chose in advance**, and resist presenting a
  chosen-afterward metric as the headline.
- **Report what got worse**, not only what improved.
- **Do not present the weighted score as an overall quality figure.** It embeds
  someone else's weighting of six objectives, with latency at 0.05 and cost at
  0.10.
- **Do not present citation metrics from a golden-set run.** They are 1.0 by
  definition and mean nothing.
- **Say "no detectable difference"** rather than "no difference" when a comparison
  comes back flat. Those are different claims, and at these sample sizes only the
  first is supportable.

---

## Recommendations (not currently implemented)

Improvements that would materially strengthen the conclusions available here. None
of these exist today; each is recorded as a concrete proposal in
[`docs/suggestions.md`](../suggestions.md).

- **Paired bootstrap confidence intervals** on per-question score differences,
  reported alongside the point delta in `compare`.
- **McNemar's test** for binary metrics like recall@k, surfacing how many
  questions actually flipped and in which direction.
- **A minimum sample size** before a comparison claims a metric moved, with
  underpowered comparisons visibly flagged.
- **A multiple-comparisons correction**, or at minimum surfacing the false-positive
  arithmetic next to any "biggest mover" display.
- **Cross-family judging by default**, or a warning when judge and generation
  model share a vendor.
- **Ensemble judging** with agreement reporting.
- **Gold passages in the golden dataset**, so a custom set can measure retrieval.
- **Multi-turn evaluation**, so question condensation is exercised.
- **An accurate config snapshot**, so runs record what actually produced them.

---

**Back to:** [Guide index](INDEX.md)

Engineering detail on the framework's internals:
[`docs/internal/eval-framework.md`](../internal/eval-framework.md).
