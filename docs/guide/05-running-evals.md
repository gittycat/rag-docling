# 5. Run evaluations

Use public datasets to exercise the pipeline. Use a golden set based on your own
documents to measure your use case.

## Built-in datasets

```bash
just eval-datasets
```

| Dataset | Best use | Supported tiers |
|---|---|---|
| `ragbench` | General checks across several domains | `generation`, `end_to_end` |
| `qasper` | Evidence grounding in scientific papers | `end_to_end` |
| `hotpotqa` | Multi-document questions | `end_to_end` |
| `msmarco` | Passage ranking | `end_to_end` |
| `squad_v2` | Answerable and unanswerable questions | `generation` |
| `golden` | Questions from your corpus | `generation` |

Invalid tier and dataset combinations fail before the run starts. Public datasets
download from Hugging Face on first use and are cached on disk.

```bash
docker compose exec evals .venv/bin/python -m evals.cli cache status
docker compose exec evals .venv/bin/python -m evals.cli cache clear
```

## Building a golden set from your own corpus

Edit `services/evals/evals/data/golden_qa.json`. The file is bind-mounted, so no
rebuild or import is required.

```json
{
  "question": "How long are audit logs retained?",
  "answer": "Audit logs are retained for 18 months.",
  "document": "security-policy.pdf",
  "query_type": "factual",
  "is_unanswerable": false
}
```

| Field | Required | Purpose |
|---|---|---|
| `question` | Yes | Question sent to the pipeline |
| `answer` | Yes | Reference for `answer_correctness` |
| `document` | No | Source label; not validated against the index |
| `context_hint` | No | Operator note; not scored |
| `query_type` | No | Question category; defaults to `factual` |
| `gold_passages` | No | Expected supporting passages |
| `gold_doc_ids` | No | Document-level supporting IDs |
| `context_passages` | No | Distractor passages supplied with the gold context |
| `is_unanswerable` | No | Whether the corpus should not answer the question |

Accepted `query_type` values are `factual`, `factoid`, `reasoning`, `multi_hop`,
`summary`, `procedural`, `comparison`, and `unanswerable`. Unknown values become
`factual`.

### Annotating gold passages

Gold passages make citation metrics meaningful and give the generation model
controlled context. Use the richest form when possible:

```json
{
  "question": "How long are audit logs retained?",
  "answer": "Audit logs are retained for 18 months.",
  "document": "security-policy.pdf",
  "gold_passages": [
    {
      "doc_id": "3f2a...",
      "chunk_id": "3f2a...:7",
      "text": "Audit logs are retained for eighteen months."
    }
  ]
}
```

`doc_id` must match the RAG server’s ID from `GET /documents`, not a filename.
You may also supply passage strings or `gold_doc_ids`, but they identify evidence
less precisely.

The golden dataset supports only `generation`. Retrieval does not run in that
tier, so a golden set cannot evaluate an embedding, search, or reranking change.
Use an `end_to_end` dataset with gold passages for retrieval experiments.

### Choose representative questions

Include:

- easy lookups and harder multi-passage questions;
- factual, comparison, procedural, and summary tasks;
- exact document terms and the words a newcomer would use; and
- questions the corpus cannot answer.

Prefer real user questions from support cases, chat logs, or interviews. Keep the
set fixed during an experiment.

| Size | What it supports |
|---:|---|
| 10–20 | Smoke tests and large regression detection |
| 30–50 | Early comparison of moderate effects |
| 100+ | Better sensitivity and useful category breakdowns |

`eval-compare` flags fewer than 100 paired questions as underpowered. For a first
serious set, 30–50 useful questions are better than 100 artificial ones.

Keep a holdout set if you tune repeatedly. Recheck reference answers whenever the
corpus changes.

## Run from the CLI

```bash
just test-eval
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --name "baseline"
just eval-compare <baseline_id> <candidate_id>
just eval-export <run_id> report
```

`just eval` passes arguments to the eval CLI:

| Flag | Default | Effect |
|---|---|---|
| `--datasets` | `ragbench` | Comma-separated datasets |
| `--tier` | `end_to_end` | `generation` or `end_to_end` |
| `--samples` | `100` | Questions per dataset |
| `--seed` | `42` | Sampling seed; keep fixed for comparisons |
| `--name` | Generated ID | Human-readable run label |
| `--no-judge` | Off | Skip judge-dependent metrics |
| `--no-cache` | Off | Bypass the dataset cache |
| `--no-judge-cache` | Off | Repeat identical judge calls |
| `--cache-queries` | Off | Reuse answers for the same recorded server config |
| `--rag-url` | `http://localhost:8001` | RAG server to evaluate |
| `--output` | `data/eval_runs` | Run output directory |
| `--config` | None | Evaluation YAML; `--tier` still overrides it |

Judge caching is on by default. Use `--no-judge-cache` when measuring repeat-run
noise. Query caching does not include the indexed corpus in its key, so never use
it after re-ingestion.

## Run from the API

```bash
curl -X POST http://localhost:8002/eval/runs \
  -H 'Content-Type: application/json' \
  -d '{"datasets": ["golden"], "tier": "generation", "samples": 40}'

curl http://localhost:8002/eval/runs/active
curl http://localhost:8002/eval/queue
curl http://localhost:8002/eval/runs
```

One evaluation runs at a time. Later requests queue up to the
`EVAL_QUEUE_DEPTH` limit, which defaults to 5. Cancel with:

```bash
curl -X DELETE http://localhost:8002/eval/runs/active
curl -X DELETE http://localhost:8002/eval/queue/<job_id>
```

### From the dashboard

Open the **Experiments** tab and expand **Run evaluation**. The form supports run
name, tier, compatible datasets, samples, seed, and judge enablement. It also shows
progress and can cancel the active run.

## Calibrate the judge

```bash
just eval-calibrate 20
```

Run calibration before trusting a judge and after changing `active.eval`.
Faithfulness and context relevance are compared with RAGBench annotations.
Correctness and relevancy use a weaker test that checks whether matched
question–answer pairs score above deliberately mismatched pairs.

Calibration results are saved in `data/calibration/`.

## Read a result

A run writes `data/eval_runs/<run_id>_<timestamp>.json`. Inspect it in this order:

1. `error_count` — failed queries make the run partial.
2. Each metric’s `sample_size` — judge failures reduce it.
3. The primary metric chosen before the run.
4. Related metrics, latency, and cost.
5. The weighted score as a summary, not a verdict.

The file also records the dataset, tier, config snapshot, duration, question count,
scorecard, and weighted-score breakdown. Per-question samples are stored in a
sidecar file.

### Comparing runs

```bash
just eval-compare <baseline_id> <candidate_id>
```

The command prints point differences and paired uncertainty. Chapter 6 explains
how to interpret confidence intervals, McNemar counts, multiple-comparison
correction, sample size, and repeat-run noise.

### Exporting

```bash
just eval-export <run_id> review-csv
```

Formats include `json`, `csv`, `review-csv`, `review-md`, `review-json`,
`scorecard-csv`, `scorecard-md`, and `report`. Review formats contain each
question, answer, reference, citations, and retrieved chunks. Use them when a judge
score moves for reasons you cannot explain.

## Storage locations

| Data | Host path |
|---|---|
| Runs and sample sidecars | `data/eval_runs/` |
| Run backups | `data/eval_runs/backup/` |
| Golden set | `services/evals/evals/data/` |
| Dataset cache | `.cache/datasets/` |
| Calibration | `data/calibration/` |

The response cache is container-local and can be rebuilt. Other paths are bind
mounted. Deleting both a run and its backup is permanent.

**Next:** [6. Compare configurations](06-tuning-workflow.md).
