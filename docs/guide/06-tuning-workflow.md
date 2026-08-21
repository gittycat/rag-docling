# 6. Compare configurations

Use one controlled loop: baseline → one change → identical rerun → paired
comparison → decision.

## Why change one variable

If you change the embedding model and `top_k` together, you only learn whether the
combination changed the result. You cannot tell which change helped or whether one
hid harm from the other.

Change one setting per experiment unless you deliberately test every combination.

## Step 1: define the experiment

Before running anything, write down:

- the setting you will change;
- the evaluation tier;
- the primary metric;
- important guardrail metrics, such as faithfulness or p95 latency; and
- the minimum improvement or maximum cost you will accept.

Choosing the primary metric after seeing results invites a false story: when many
metrics are tested, one often moves by chance.

## Step 2: record the baseline

Keep these fixed across both runs:

| Input | Why |
|---|---|
| Dataset, sample count, and seed | Ensures the same questions |
| Evaluation tier | Runs different pipeline stages |
| Corpus | Changes retrieval results |
| Judge model | Changes the grader |
| `eval.scoring` | Changes the weighted score |
| Machine load, for latency work | Changes timing |

```bash
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --name "baseline"
```

The run records active models and retrieval settings from the RAG server. Also
keep a short experiment note; the snapshot records what ran, not why.

### Measure repeat-run noise

Run the unchanged baseline again:

```bash
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --no-judge-cache --name "baseline-repeat"
```

`--no-judge-cache` forces new judge calls. The difference between two unchanged
runs is an empirical noise floor for that dataset, sample size, judge, and
environment. It captures variation that a single baseline–candidate pair cannot
characterize.

## Step 3: apply one change

Edit `config.yml`, then confirm the effective settings:

```bash
just show-config-full
```

Do not edit configuration during a run. The file auto-reloads, so a mid-run edit
can produce a result that describes neither configuration.

| Change | Extra work |
|---|---|
| Most settings | None after saving |
| Embedding model | Restart and fully re-ingest |
| Reranker model | Cache it with `just init`, then restart |
| Chunk size or overlap | Edit code, rebuild, and fully re-ingest |
| Contextual retrieval | Fully re-ingest to rebuild chunks |

## Step 4: rerun identically

```bash
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --name "candidate"
```

Common confounds are a different seed, changed corpus, changed judge, edited
scoring weights, a mid-run config change, or query caching after re-ingestion.

## Step 5: compare the runs

```bash
just eval-compare <baseline_id> <candidate_id>
```

Read the output in this order:

1. Check `error_count` and each relevant `sample_size`.
2. Find the primary metric chosen before the experiment.
3. Read its confidence interval, not only its point difference.
4. Check related metrics for a coherent mechanism.
5. Compare the effect with repeat-run noise.
6. Review cost and p95 latency.

### Interpret the statistical output

The comparison pairs scores for questions common to both runs.

| Output | Interpretation |
|---|---|
| 95% CI excludes zero and verdict is `significant` | Difference survived the metric-family correction |
| CI includes zero | No difference was established |
| `nominal (fails BH)` | Uncorrected signal; treat as a reason to rerun |
| `underpowered` | Fewer than 100 paired questions; expect wide uncertainty |
| McNemar counts | For binary metrics, questions that improved, regressed, or stayed unchanged |
| `not tested` | No pairable per-question data, such as p50 latency or an older run |

Continuous metrics use a paired bootstrap confidence interval. Binary metrics also
use McNemar’s exact test. Benjamini–Hochberg correction reduces false discoveries
across the metric family.

Statistical significance is not practical importance. A small, credible gain may
still be too expensive or slow. A wide interval means the sample did not resolve
the question; it does not prove the configurations are equal.

### Look for a coherent pattern

A real reranking improvement might raise `mrr`, `ndcg_at_10`, `recall_at_5`, and
faithfulness together. One isolated metric moving while related metrics remain
flat is weaker evidence.

Sample size sets sensitivity. Rough paired-test guidelines at 5% significance and
80% power are about 15 questions for a large effect, 34 for a moderate effect, and
199 for a small effect. Treat these as planning estimates, not guarantees.

## Step 6: decide and record

| Result | Action |
|---|---|
| Credible improvement at acceptable cost | Keep it and make it the new baseline |
| No detectable improvement | Prefer the simpler, cheaper, or faster configuration |
| Regression | Revert |

Record the change, run IDs, primary result, guardrail changes, and decision. This
prevents repeated experiments and makes the next baseline clear.

## Worked example

Suppose you want to test whether reranking is worth its latency.

1. Choose `end_to_end` because reranking is part of retrieval.
2. Choose `mrr` as the primary metric and p95 latency as a guardrail.
3. Run and repeat the baseline with reranking enabled.
4. Set `reranker.enabled: false` and rerun with the same dataset, seed, sample
   count, corpus, and judge.
5. Compare the paired runs.

If MRR falls outside repeat-run noise, its corrected interval excludes zero, and
`ndcg_at_10` and `recall_at_5` fall too, the result matches the expected mechanism.
Keep reranking if that loss exceeds the latency benefit you defined in advance.

## System-specific cautions

- Citation metrics use all retrieved chunks by default.
- Judge caching hides judge variation unless disabled.
- Generation-tier runs never exercise retrieval.
- The default OpenAI judge may favour the OpenAI generation family.
- Eval latency is measured under concurrency.
- The dashboard shows point differences but not significance; use the CLI.

**Next:** [7. Experiment recipes](07-experiment-cookbook.md).

Also read [11. Limits and caveats](11-limits-and-caveats.md) before reporting
results.
