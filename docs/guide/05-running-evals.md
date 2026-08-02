# 5. Running evaluations

This chapter is mechanical: which datasets exist, how to build one from your own
documents, how to run an evaluation, and how to read what comes back.

The most important section is [building a golden set](#building-a-golden-set-from-your-own-corpus).
The public datasets are useful for exercising the pipeline and sanity-checking a
change, but they tell you nothing about whether this system answers questions
about *your* documents. Only your own questions do that.

---

## The built-in datasets

```bash
just eval-datasets
```

| Dataset | What it is | Best for | Tiers |
|---|---|---|---|
| `ragbench` | Multi-domain RAG benchmark with human/model-annotated ground truth across several industry subsets | General-purpose checks; the only dataset supporting both tiers | `generation`, `end_to_end` |
| `qasper` | Question answering over scientific papers, with evidence spans | Citation and evidence-grounding behaviour | `end_to_end` |
| `hotpotqa` | Multi-hop questions requiring reasoning across several documents | Retrieval under compositional questions | `end_to_end` |
| `msmarco` | Large-scale passage ranking | Retrieval ranking specifically | `end_to_end` |
| `squad_v2` | Reading comprehension including deliberately unanswerable questions | Abstention behaviour | `generation` |
| `golden` | Your own curated question/answer pairs | Everything that actually matters to you | `generation` |

Invalid tier/dataset combinations are rejected before the run starts rather than
producing a meaningless result.

Datasets other than `golden` are downloaded from HuggingFace on first use and
cached to disk. Manage that cache with:

```bash
docker compose exec evals .venv/bin/python -m evals.cli cache status
docker compose exec evals .venv/bin/python -m evals.cli cache clear
```

---

## Building a golden set from your own corpus

This is the highest-value thing in this guide. Thirty questions written against
your own documents will teach you more about your deployment than every public
benchmark combined.

### The file

`services/evals/evals/data/golden_qa.json`, a flat JSON array. It ships with ten
example entries. Each entry:

```json
{
  "question": "What are the three qualities that work must have to do great work?",
  "answer": "The work must have three qualities: it must be something you have a natural aptitude for, that you have a deep interest in, and that offers scope to do great work.",
  "document": "greatwork.html",
  "context_hint": "The essay discusses the first step in doing great work",
  "query_type": "factual"
}
```

| Field | Required | Purpose |
|---|---|---|
| `question` | Yes | What gets asked. |
| `answer` | Yes | The reference answer. `answer_correctness` is scored against this. |
| `document` | No | Source filename. Used for grouping and readability. **Not validated** — nothing checks that this file was ever ingested. |
| `context_hint` | No | A note to yourself. Carried in metadata; not scored. |
| `query_type` | No | Classifies the question. Defaults to `factual`. |
| `gold_passages` | No | The passages that should be retrieved. Makes retrieval and citation metrics measurable — see below. |
| `gold_doc_ids` | No | Document-level shorthand for the same thing. |
| `context_passages` | No | Distractor passages, injected alongside the gold ones in `generation` tier. |
| `is_unanswerable` | No | Marks a question the corpus genuinely cannot answer. Feeds the abstention metrics. |

Accepted `query_type` values: `factual` (or `factoid`), `reasoning` (or
`multi_hop`), `summary`, `procedural`, `comparison`, and `unanswerable`. Anything
unrecognized silently becomes `factual`.

Edit the file, save, and re-run. There is no import step and no rebuild needed —
`services/evals/evals/data/` is bind-mounted into the container, so your edit is
live immediately. Add `--no-cache` to your next run if you changed the set and
want to be certain you are not reading a cached copy.

### Annotating gold passages

Without annotations a golden entry measures **answer quality** only: faithfulness,
correctness, relevancy, abstention. That is genuinely valuable — it is the part
users experience — but it is not a retrieval measurement, and retrieval and
citation metrics will report **`n/a`** rather than a number.

They report `n/a` rather than 0.0 or 1.0 deliberately. Citation precision and
recall used to return a perfect **1.0** with no gold passages, so an unannotated
golden run displayed flawless citation scores that measured nothing.

To make them measurable, add gold passages. The richest form carries the text:

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

- `"gold_passages": ["the passage text", ...]` — ids are derived from `document`.
  Text overlap still resolves citations, so the citation metrics work.
- `"gold_doc_ids": ["3f2a..."]` — document level only. Retrieval and citation
  metrics resolve by document; nothing can resolve to a specific chunk.

**`doc_id` must be the id the RAG server uses**, not your filename. Get it from
`GET /documents`. A filename here matches nothing and scores zero.

The golden dataset still only supports the `generation` tier: the passages are
injected as context rather than ingested, so an annotated golden set measures how
well the pipeline uses the right passages, not whether retrieval finds them. For
that, use `end_to_end` runs against `ragbench`, `hotpotqa`, or `msmarco`, and
accept that you are measuring on somebody else's documents.

### Choosing questions

The instinct is to write questions you know the system handles well. Resist it —
that produces a set that cannot detect a regression.

Aim for a spread across four axes:

**Difficulty.** Include questions answerable from a single obvious passage,
questions requiring information from two places, and questions that are genuinely
hard. If everything is easy, every configuration scores well and you learn
nothing.

**Question type.** Factual lookups, comparisons, procedural "how do I" questions,
and summaries stress different parts of the pipeline. Retrieval that is excellent
at factual lookup is often poor at summarization, because a summary needs broad
coverage rather than one precise hit.

**Phrasing.** Write some questions using your documents' exact vocabulary and
others using the words a newcomer would use. The gap between those two is exactly
what hybrid search exists to close, and it will not show up in your numbers unless
your question set contains it.

**Answerability.** Include questions your corpus genuinely cannot answer, marked
`"query_type": "unanswerable"`. Without these, abstention metrics have nothing to
work with — and a system that never abstains will look perfect right up until a
user asks something outside the corpus.

A practical way to gather real questions: take them from actual users. Support
tickets, chat logs, the questions people ask in team channels. Questions you
invent reflect your model of the corpus; questions users ask reflect theirs, and
theirs is the one that matters.

### How many

More is better, and the reason is statistical rather than aesthetic: your ability
to tell a real improvement from noise depends directly on how many questions you
scored. With a very small set, only enormous differences are distinguishable from
chance, and most tuning changes are not enormous.

As a practical progression:

- **10–20 questions** — enough to catch a change that broke something badly.
  Not enough to compare two reasonable configurations.
- **30–50 questions** — the point where a moderate difference starts to be
  visible. A reasonable target for a first serious golden set.
- **100+ questions** — where small differences become detectable, and where
  per-category breakdowns (by question type, by document area) start being
  meaningful rather than anecdotal.

Chapter 6 covers how to reason about whether a specific difference is real given
the set size you actually have. The short version: with a small set, believe large
consistent movements and be sceptical of everything else.

Note the cost side. Every question in a run with judging enabled costs LLM calls —
one per generation metric — so a 100-question run means several hundred judge
calls. Build the set to the size you need, then keep it fixed. A question set that
changes between runs makes runs incomparable.

### Keeping it honest

A golden set is a benchmark, and benchmarks rot. Two failure modes:

**Overfitting.** After ten tuning cycles against the same 30 questions you have a
configuration optimized for those 30 questions. Hold back a portion — write 40,
tune against 30, and check the remaining 10 only when you think you are done. If
the held-back scores did not move with the others, you tuned to the set rather
than to the corpus.

**Staleness.** When the corpus changes, answers that were correct become wrong.
Re-check reference answers whenever the underlying documents change materially, or
your correctness scores will drop for reasons that have nothing to do with
configuration.

---

## Running an evaluation

### From the CLI

The `just` recipes cover the common cases:

```bash
just test-eval                 # smoke test: ragbench, end-to-end, 5 samples
just test-eval-full            # all end-to-end datasets, all samples
just eval --tier generation --datasets golden --samples 20
just eval-datasets             # list available datasets
just eval-calibrate 20         # check the judge against ground truth
just eval-compare <run_id> <run_id>
```

`just eval` passes arguments straight through, so anything below works with it.
The underlying form, useful when a recipe does not fit:

```bash
docker compose exec evals .venv/bin/python -m evals.cli eval \
  --tier generation --datasets golden --samples 20 --name "baseline"
```

Flags for `eval`:

| Flag | Default | Effect |
|---|---|---|
| `--datasets` | `ragbench` | Comma-separated dataset names. |
| `--tier` | `end_to_end` | `generation` or `end_to_end`. |
| `--samples` | `100` | Questions per dataset. |
| `--seed` | `42` | Sampling seed. **Keep this fixed across runs you intend to compare.** |
| `--name` | `eval-<run_id>` | A label. Use it — you will not remember what `eval-a3f9c201` was. |
| `--no-judge` | off | Skips all generation metrics. Fast and free; use when you only care about retrieval. |
| `--no-cache` | off | Bypasses the dataset disk cache. |
| `--rag-url` | `http://localhost:8001` | Which RAG server to evaluate. |
| `--output` | `data/eval_runs` | Where the run JSON is written. |
| `--config` | none | A YAML config file. Note that `--tier` still overrides it, and other flags are ignored when it is given. |

For `end_to_end` runs the CLI health-checks the RAG server first and exits with a
clear message if it is unreachable.

### From the API

The eval service listens on port 8002:

```bash
curl -X POST http://localhost:8002/eval/runs \
  -H 'Content-Type: application/json' \
  -d '{"datasets": ["golden"], "tier": "generation", "samples": 20}'

curl http://localhost:8002/eval/runs/active     # progress
curl -X DELETE http://localhost:8002/eval/runs/active   # cancel
curl http://localhost:8002/eval/queue           # jobs waiting behind it
curl -X DELETE http://localhost:8002/eval/queue/<job_id>   # drop a queued job
curl http://localhost:8002/eval/runs            # list past runs
```

**Only one evaluation runs at a time**, process-wide — they saturate the RAG
server. Further requests are **queued** rather than rejected: `POST /eval/runs`
returns `202` with a `queue_position` (0 means it started immediately). Only when
the queue is full does it return `429`; depth defaults to 5 and is set by
`EVAL_QUEUE_DEPTH`.

### From the dashboard

The Experiments tab has a **Run evaluation** panel. "Options" opens the form —
run name, tier, datasets (filtered to those supporting the selected tier),
samples per dataset, seed, and whether the LLM judge is enabled; "Start run"
posts it. While a run is active the panel replaces the form with live progress
(phase, current dataset, question counter, elapsed time) and a **Cancel** button.
The run list refreshes on its own when the run finishes.

Starting a run while one is active queues it behind the current one.

---

## Calibrating the judge

```bash
just eval-calibrate 20
```

This checks the judge's scores against ground-truth annotations in the RAGBench
dataset and reports how well they agree: accuracy on the adherence judgement, and
root-mean-square error against the annotated scores.

Worth running when you change `active.eval`, and worth running once before you
trust any judged metric. If agreement is poor, your faithfulness scores are noise
with a decimal point.

**What it does not cover:** only faithfulness and context relevance are
calibrated. `answer_correctness` and `answer_relevancy` are never checked against
ground truth at all. Calibration results are saved under `data/calibration/`.

---

## Reading a result

A run produces a JSON file at `data/eval_runs/<run_id>_<timestamp>.json`, where
`run_id` is an eight-character identifier. It contains:

- **`config`** — a snapshot of the models used.
- **`scorecard`** — every metric, grouped, each with a value and a `sample_size`.
- **`weighted_score`** — the headline number and its objective breakdown.
- **`question_count`**, **`error_count`**, **`duration_seconds`**.

Read it in this order:

1. **`error_count`.** If queries failed, everything below describes a partial run.
2. **`sample_size` on each judged metric.** Lower than `question_count` means
   judge calls failed and were excluded. A large shortfall makes that metric
   unrepresentative.
3. **The metrics you actually care about**, per chapter 4 — not the weighted
   score.
4. **The weighted score**, last, as a sanity check rather than a verdict.

### Comparing runs

```bash
just eval-compare <run_id_a> <run_id_b>
```

Prints each metric side by side, plus the weighted score and duration. Adding
`--pareto` reports which runs are not dominated by any other across all
objectives.

Below the table it reports, for every metric both runs scored, a **paired
bootstrap 95% confidence interval** on the per-question difference:

```
Metric                          n      delta                 95% CI         p  verdict
faithfulness                  120    +0.0956     [+0.0643, +0.1263]    0.0001  significant
recall_at_5                   120    +0.1667     [+0.0500, +0.2833]    0.0105  significant
                                   McNemar: 38 questions improved, 18 regressed, 64 unchanged
```

How to read it:

- **The interval, not the delta, is the result.** An interval spanning zero means
  the run did not establish a difference — regardless of how large the delta looks.
- **`significant`** survived Benjamini-Hochberg across the whole metric family.
  **`nominal (fails BH)`** means the interval excluded zero but the correction
  rejected it; scanning twenty metrics produces roughly one of those by chance.
- **`underpowered`** marks fewer than 100 paired questions. The interval is still
  computed, but treat it as indicative.
- Binary metrics get McNemar's exact test and the discordant counts, which is
  usually more informative than the rate: "38 improved, 18 regressed" says more
  than "+0.17".
- Metrics listed as *not tested* have no per-question data to pair on — aggregate
  metrics like P50 latency, or runs saved before the framework recorded them.

`--no-significance` skips it. Chapter 6 covers making decisions when the intervals
are wide.

### Exporting

```bash
docker compose exec evals .venv/bin/python -m evals.cli export \
  --run-id <run_id> --format csv --output results.csv
```

| `--format` | Output |
|---|---|
| `json` | The run JSON, unchanged. |
| `csv` | One row per metric. Undefined metrics export blank, never 0. |
| `review-csv` / `review-md` / `review-json` | One row or section **per question** — question, reference answer, generated answer, citations, retrieved chunks — with blank reviewer columns to fill in. |
| `scorecard-csv` / `scorecard-md` | Metrics only. |
| `report` | Full Markdown run report: config, weighted score breakdown, all metrics. |

The `review-*` formats read the run's samples sidecar
(`data/eval_runs/{run}_samples.json`), written alongside every run. Runs completed
before that sidecar existed cannot be exported for review.

Human review is the only check on the judge that does not itself involve an LLM.
If a judged metric moves and you cannot explain why, export the review sheet and
read twenty answers.

---

## Where things are stored

Everything is flat files, not a database:

| What | Container path | On your host |
|---|---|---|
| Runs | `/app/data/eval_runs/` | `./data/eval_runs/` — bind-mounted |
| Golden set | `/app/evals/data/` | `./services/evals/evals/data/` — bind-mounted |
| Dataset cache | `/app/data/dataset_cache/` | `./.cache/datasets/` — bind-mounted |
| Calibration | `/app/data/calibration/` | `./data/calibration/` — bind-mounted |
| Per-question samples | `/app/data/eval_runs/{run}_samples.json` | alongside the run |
| Run backups | `/app/data/eval_runs/backup/` | `./data/eval_runs/backup/` |
| Response cache | `/app/data/eval_cache/` | not mounted — rebuilt on demand |

So run JSON is directly readable from your repository root:

```bash
ls data/eval_runs/
```

So is calibration output:

```bash
ls data/calibration/
```

The eval service builds an in-memory index of runs by scanning the runs directory
at startup, skipping the `_samples.json` sidecars. Restarting rebuilds it. Every
run is also copied to `data/eval_runs/backup/`, so deleting a run file is
recoverable — deleting both is not.

---

**Next:** [6. The tuning workflow](06-tuning-workflow.md) — the loop these
measurements exist to serve.
