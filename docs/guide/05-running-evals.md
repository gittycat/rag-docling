# 5. Running evaluations

Which datasets exist, how to build one from your own documents, how to run an
evaluation, and how to read what comes back.

The most important section is [building a golden set](#building-a-golden-set-from-your-own-corpus).
Public datasets exercise the pipeline and sanity-check a change; they tell you
nothing about whether this system answers questions about *your* documents.

---

## The built-in datasets

```bash
just eval-datasets
```

| Dataset | What it is | Best for | Tiers |
|---|---|---|---|
| `ragbench` | Multi-domain benchmark with annotated ground truth across several industry subsets | General checks; the only dataset supporting both tiers | `generation`, `end_to_end` |
| `qasper` | QA over scientific papers, with evidence spans | Citation and evidence grounding | `end_to_end` |
| `hotpotqa` | Multi-hop questions spanning several documents | Retrieval under compositional questions | `end_to_end` |
| `msmarco` | Large-scale passage ranking | Retrieval ranking specifically | `end_to_end` |
| `squad_v2` | Reading comprehension with deliberately unanswerable questions | Abstention behaviour | `generation` |
| `golden` | Your own curated Q&A pairs | Everything that actually matters to you | `generation` |

Invalid tier/dataset combinations are rejected before the run starts.

Everything except `golden` downloads from Hugging Face on first use and caches to
disk:

```bash
docker compose exec evals .venv/bin/python -m evals.cli cache status
docker compose exec evals .venv/bin/python -m evals.cli cache clear
```

---

## Building a golden set from your own corpus

Thirty questions written against your own documents will teach you more about your
deployment than every public benchmark combined.

### The file

`services/evals/evals/data/golden_qa.json` — a flat JSON array, shipping with ten
example entries.

```json
{
  "question": "What are the three qualities that work must have to do great work?",
  "answer": "The work must have three qualities: something you have a natural aptitude for, that you have a deep interest in, and that offers scope to do great work.",
  "document": "greatwork.html",
  "context_hint": "The essay discusses the first step in doing great work",
  "query_type": "factual"
}
```

| Field | Required | Purpose |
|---|---|---|
| `question` | Yes | What gets asked |
| `answer` | Yes | The reference answer. `answer_correctness` scores against this. |
| `document` | No | Source filename, for grouping and readability. **Not validated** — nothing checks it was ever ingested. |
| `context_hint` | No | A note to yourself. Carried in metadata, not scored. |
| `query_type` | No | Classifies the question. Defaults to `factual`. |
| `gold_passages` | No | Passages that should be retrieved. Makes retrieval and citation metrics measurable. |
| `gold_doc_ids` | No | Document-level shorthand for the same thing. |
| `context_passages` | No | Distractor passages, injected alongside the gold ones. |
| `is_unanswerable` | No | Marks a question the corpus genuinely cannot answer. Feeds abstention metrics. |

Accepted `query_type` values: `factual` (or `factoid`), `reasoning` (or
`multi_hop`), `summary`, `procedural`, `comparison`, `unanswerable`. Anything
unrecognized silently becomes `factual`.

`services/evals/evals/data/` is bind-mounted, so edits are live — no import step,
no rebuild. Add `--no-cache` if you changed the set and want certainty you are not
reading a cached copy.

### Annotating gold passages

Without annotations a golden entry measures **answer quality** only — faithfulness,
correctness, relevancy, abstention. Retrieval and citation metrics report **`n/a`**
rather than a number (deliberately: an earlier version returned a meaningless 1.0).

The richest form carries the text:

```json
{
  "question": "What is the retention period for audit logs?",
  "answer": "Audit logs are retained for 18 months.",
  "document": "security-policy.pdf",
  "gold_passages": [
    {
      "doc_id": "3f2a...",
      "chunk_id": "3f2a...:7",
      "text": "Audit logs are retained for a period of eighteen (18) months..."
    }
  ]
}
```

Two shorthands, in decreasing fidelity:

| Form | Resolves to |
|---|---|
| `"gold_passages": ["the passage text", ...]` | IDs derived from `document`; text overlap still resolves citations |
| `"gold_doc_ids": ["3f2a..."]` | Document level only — nothing resolves to a specific chunk |

**`doc_id` must be the ID the RAG server uses**, not your filename. Get it from
`GET /documents`. A filename here matches nothing and scores zero.

The golden dataset supports only the `generation` tier — passages are injected as
context rather than ingested. So an annotated golden set measures how well the
pipeline *uses* the right passages, not whether retrieval *finds* them. For that,
run `end_to_end` against `ragbench`, `hotpotqa`, or `msmarco`, and accept that you
are measuring on somebody else's documents.

### Choosing questions

The instinct is to write questions you know the system handles well. Resist it —
that produces a set that cannot detect a regression. Spread across four axes:

| Axis | What to include | Why |
|---|---|---|
| **Difficulty** | Single-passage lookups, two-source questions, genuinely hard ones | If everything is easy, every configuration scores well and you learn nothing |
| **Question type** | Factual, comparison, procedural, summary | Retrieval that excels at factual lookup is often poor at summarization, which needs broad coverage rather than one precise hit |
| **Phrasing** | Your documents' exact vocabulary *and* a newcomer's words | The gap between those two is what hybrid search exists to close |
| **Answerability** | Questions your corpus cannot answer, marked `"query_type": "unanswerable"` | Without these, abstention metrics have nothing to work with |

Take questions from real users where you can — support tickets, chat logs, team
channels. Questions you invent reflect your model of the corpus; users' questions
reflect theirs, and theirs is the one that matters.

### How many

Your ability to tell a real improvement from noise depends directly on how many
questions you scored.

| Size | What it buys |
|---|---|
| **10–20** | Catches a change that broke something badly. Not enough to compare two reasonable configurations. |
| **30–50** | A moderate difference starts to be visible. Reasonable target for a first serious set. |
| **100+** | Small differences become detectable; per-category breakdowns stop being anecdotal. `compare` flags anything below 100 paired questions as underpowered. |

Every question in a judged run costs LLM calls — one per generation metric — so a
100-question run means several hundred judge calls. Build the set to the size you
need, then **keep it fixed.** A question set that changes between runs makes runs
incomparable.

### Keeping it honest

**Overfitting.** After ten tuning cycles against the same 30 questions you have a
configuration optimized for those 30 questions. Write 40, tune against 30, check
the remaining 10 only when you think you are done. If the held-back scores did not
move with the others, you tuned to the set rather than to the corpus.

**Staleness.** When the corpus changes, correct answers become wrong. Re-check
reference answers whenever documents change materially, or correctness scores drop
for reasons unrelated to configuration.

---

## Running an evaluation

### From the CLI

```bash
just test-eval                          # smoke test: ragbench, end-to-end, 5 samples
just test-eval-full                     # all end-to-end datasets, all samples
just eval --tier generation --datasets golden --samples 20 --name "baseline"
just eval-datasets                      # list datasets
just eval-calibrate 20                  # check the judge against ground truth
just eval-compare <run_id> <run_id>
just eval-export <run_id> report
```

`just eval` passes arguments straight through. The underlying form, when a recipe
does not fit:

```bash
docker compose exec evals .venv/bin/python -m evals.cli eval \
  --tier generation --datasets golden --samples 20 --name "baseline"
```

| Flag | Default | Effect |
|---|---|---|
| `--datasets` | `ragbench` | Comma-separated dataset names |
| `--tier` | `end_to_end` | `generation` or `end_to_end` |
| `--samples` | `100` | Questions per dataset |
| `--seed` | `42` | Sampling seed. **Keep fixed across runs you intend to compare.** |
| `--name` | `eval-<run_id>` | A label. Use it — you will not remember what `eval-a3f9c201` was. |
| `--no-judge` | off | Skips all generation metrics. Fast and free; use when you only want retrieval. |
| `--no-cache` | off | Bypasses the dataset disk cache (re-downloads) |
| `--no-judge-cache` | off | Re-runs every judge call instead of reusing identical cached ones |
| `--cache-queries` | off | Reuses RAG answers cached from a previous run with the same server config |
| `--rag-url` | `http://localhost:8001` | Which RAG server to evaluate |
| `--output` | `data/eval_runs` | Where the run JSON is written |
| `--config` | none | A YAML config file. `--tier` still overrides it; other flags are ignored when given. |

**Two caching notes that affect comparability.** Judge-call caching is **on by
default** — identical judge calls are reused, which makes re-runs cheaper but means
a re-run does not resample judge variance. Use `--no-judge-cache` when measuring
your noise floor (chapter 6). Query caching is **off by default** and opt-in via
`--cache-queries`; its key does not cover the indexed corpus, so never use it after
re-ingesting documents.

For `end_to_end` runs the CLI health-checks the RAG server first and exits with a
clear message if it is unreachable.

### From the API

```bash
curl -X POST http://localhost:8002/eval/runs \
  -H 'Content-Type: application/json' \
  -d '{"datasets": ["golden"], "tier": "generation", "samples": 20}'

curl http://localhost:8002/eval/runs/active               # progress
curl -X DELETE http://localhost:8002/eval/runs/active     # cancel
curl http://localhost:8002/eval/queue                     # jobs waiting behind it
curl -X DELETE http://localhost:8002/eval/queue/<job_id>  # drop a queued job
curl http://localhost:8002/eval/runs                      # list past runs
```

**Only one evaluation runs at a time**, process-wide — they saturate the RAG
server. Further requests are **queued**, not rejected: `POST /eval/runs` returns
`202` with a `queue_position` (0 means it started immediately). Only a full queue
returns `429`; depth defaults to 5, set by `EVAL_QUEUE_DEPTH`.

### From the dashboard

The Experiments tab has a **Run evaluation** panel. "Options" opens the form — run
name, tier, datasets (filtered to those supporting the selected tier), samples,
seed, and whether the judge is enabled. While a run is active the panel shows live
progress (phase, dataset, question counter, elapsed time) and a **Cancel** button.
Starting a run while one is active queues it.

---

## Calibrating the judge

```bash
just eval-calibrate 20
```

Checks the judge's scores against ground truth and reports agreement. Worth running
when you change `active.eval`, and once before you trust any judged metric. If
agreement is poor, your faithfulness scores are noise with a decimal point.

| Prompt | Check | Strength |
|---|---|---|
| Faithfulness | Against RAGBench annotations — accuracy on the adherence judgement plus RMSE | Strong |
| Context relevance | Same | Strong |
| `answer_correctness` | Discrimination test: score each response against its own reference and against a deliberately mismatched one, report how often the matched pair ranked higher | Weak — a floor, not evidence that mid-range scores track human judgement |
| `answer_relevancy` | Same | Weak |

Results are saved under `data/calibration/`.

---

## Reading a result

A run writes `data/eval_runs/<run_id>_<timestamp>.json`, where `run_id` is eight
characters. Read it in this order:

1. **`error_count`.** If queries failed, everything below describes a partial run.
2. **`sample_size` on each judged metric.** Lower than `question_count` means judge
   calls failed and were excluded, making that metric unrepresentative.
3. **The metrics you actually care about**, per chapter 4.
4. **The weighted score**, last, as a sanity check rather than a verdict.

The file also holds `config` (a snapshot of models and retrieval settings read live
from the RAG server), `scorecard` (every metric with its value and sample size),
`weighted_score` with its objective breakdown, `question_count`, and
`duration_seconds`.

### Comparing runs

```bash
just eval-compare <run_id_a> <run_id_b>
```

Prints each metric side by side, plus the weighted score and duration. `--pareto`
reports which runs are not dominated by any other across all objectives.

Below the table, for every metric both runs scored, it reports a **paired bootstrap
95% confidence interval** on the per-question difference:

```
Metric                          n      delta                 95% CI         p  verdict
faithfulness                  120    +0.0956     [+0.0643, +0.1263]    0.0001  significant
recall_at_5                   120    +0.1667     [+0.0500, +0.2833]    0.0105  significant
                                   McNemar: 38 questions improved, 18 regressed, 64 unchanged
```

| Read | Meaning |
|---|---|
| **The interval, not the delta** | An interval spanning zero means the run did not establish a difference, regardless of how large the delta looks |
| `significant` | Survived Benjamini-Hochberg correction across the whole metric family |
| `nominal (fails BH)` | The interval excluded zero but the correction rejected it. Scanning twenty metrics produces roughly one of these by chance. |
| `underpowered` | Fewer than 100 paired questions. The interval is computed but treat it as indicative. |
| McNemar counts | Binary metrics get McNemar's exact test. "38 improved, 18 regressed" says more than "+0.17". |
| *not tested* | No per-question data to pair on — aggregate metrics like P50 latency, or runs saved before the framework recorded them |

The bootstrap uses 10,000 resamples with a fixed seed, so the same two runs always
compare identically. `--bootstrap-samples` changes the count; `--no-significance`
skips the whole block. Chapter 6 covers deciding when the intervals are wide.

### Exporting

```bash
docker compose exec evals .venv/bin/python -m evals.cli export \
  --run-id <run_id> --format csv --output results.csv
```

| `--format` | Output |
|---|---|
| `json` | The run JSON, unchanged |
| `csv` | One row per metric. Undefined metrics export blank, never 0. |
| `review-csv` / `review-md` / `review-json` | One row or section **per question** — question, reference answer, generated answer, citations, retrieved chunks — with blank reviewer columns to fill in |
| `scorecard-csv` / `scorecard-md` | Metrics only |
| `report` | Full Markdown report: config, weighted score breakdown, all metrics |

The `review-*` formats read the run's samples sidecar
(`data/eval_runs/{run}_samples.json`). Runs completed before that sidecar existed
cannot be exported for review.

**Human review is the only check on the judge that does not itself involve an LLM.**
If a judged metric moves and you cannot explain why, export the review sheet and
read twenty answers.

---

## Where things are stored

Flat files, not a database:

| What | Container path | On your host |
|---|---|---|
| Runs | `/app/data/eval_runs/` | `./data/eval_runs/` |
| Per-question samples | `/app/data/eval_runs/{run}_samples.json` | alongside the run |
| Run backups | `/app/data/eval_runs/backup/` | `./data/eval_runs/backup/` |
| Golden set | `/app/evals/data/` | `./services/evals/evals/data/` |
| Dataset cache | `/app/data/dataset_cache/` | `./.cache/datasets/` |
| Calibration | `/app/data/calibration/` | `./data/calibration/` |
| Response cache | `/app/data/eval_cache/` | not mounted — rebuilt on demand |

All bind-mounted except the response cache, so run JSON is directly readable:

```bash
ls data/eval_runs/
ls data/calibration/
```

The eval service builds an in-memory index by scanning the runs directory at
startup, skipping `_samples.json` sidecars; restarting rebuilds it. Every run is
also copied to `backup/`, so deleting a run file is recoverable — deleting both is
not.

---

**Next:** [6. The tuning workflow](06-tuning-workflow.md) — the loop these
measurements exist to serve.
