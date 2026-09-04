# Evaluation Framework

Standalone evaluation framework for measuring RAG server quality. Sends questions from benchmark datasets to the running RAG server over HTTP, compares responses against ground truth, and produces scored results grouped by metric category.

## Metric Groups

Results are organized into five groups. These groups are used throughout the codebase and in the API response when reporting evaluation results.

### Retrieval

Measures how well the retriever finds the right chunks. All compare retrieved chunks against gold (ground truth) passages using `chunk_id` matching.

| Metric | What it measures | Range |
|---|---|---|
| `recall_at_k` | Fraction of gold chunks found in top K results | 0-1, higher is better |
| `precision_at_k` | Fraction of top K results that are gold chunks | 0-1, higher is better |
| `mrr` | Reciprocal rank of the first relevant result | 0-1, higher is better |
| `ndcg_at_k` | Ranking quality accounting for position (DCG/IDCG) | 0-1, higher is better |

Default K values: recall at 1, 3, 5, 10; precision at 1, 3, 5.

### Generation

Measures answer quality using an **LLM-as-judge**. The judge model is whatever `active.eval` names in the repo-root `config.yml` (an OpenAI model in the shipped defaults), and needs that provider's API key mounted as a Docker secret. Disabled with `--no-judge`.

The judge should not share a provider with `active.inference`: self-preference bias in LLM judges extends across a model family, so a same-provider pairing inflates that provider's own generations. The runner warns at startup when they match and records the warning on the run.

Judge prompts embed retrieved chunks and generated answers verbatim and are never masked, so `data_policy` in `config.yml` decides whether the judge may see corpus content at all. Each `models.eval` entry declares an `execution_boundary` (`customer_managed`, `aws_managed`, `third_party`) describing where that endpoint actually runs — never inferred from the provider name — and `data_policy.allowed_judge_boundaries` is an allow-list. A boundary that is missing or not on the list stops the run. Whether the check applies is decided per run: `data_policy.public_datasets` names the datasets that carry no corpus content (`golden` is deliberately absent), and in the `end_to_end` tier `data_policy.eval_index_is_isolated` must also be true, because that tier queries the live index and the judge sees whatever it returns.

| Metric | What it measures | Range |
|---|---|---|
| `faithfulness` | Whether the answer is grounded in the retrieved context (no hallucination) | 0-1, higher is better |
| `answer_correctness` | Semantic equivalence to the expected answer | 0-1, higher is better |
| `answer_completeness` | Fraction of cached reference-answer facts covered by the answer | 0-1, higher is better |
| `answer_relevancy` | Whether the answer addresses the question asked | 0-1, higher is better |

### Citation

Measures how accurately the system cites its sources.

| Metric | What it measures | Range |
|---|---|---|
| `citation_precision` | Fraction of citations pointing to gold passages | 0-1, higher is better |
| `citation_recall` | Fraction of gold passages that are cited | 0-1, higher is better |
| `section_accuracy` | Whether citations point to the correct document AND section | 0-1, higher is better |

### Groundedness

Claim-level grounding and claim-to-citation entailment. Where the citation group asks whether a cited chunk is one of the gold passages, this asks whether that chunk entails the sentence citing it — a citation can pass the first test and fail this one. Sentence-level claims are segmented deterministically (`evals/claims.py`), including the inline `[1]` markers attached to each claim.

Runs by default: it costs one judge call per claim plus one per claim-citation link, against three per question for the whole generation group. The groundedness scoring weight remains 0.0, so collecting the extra signal does not change the weighted score. Capped at 5 claims/answer and 2 citations/claim, with truncation reported per question.

The two citation-link metrics need `eval.citation_scope: explicit` in `config.yml`; under the default `retrieved` the model is never asked for markers and they report `n/a`.

| Metric | What it measures | Range |
|---|---|---|
| `claim_groundedness` | Fraction of the answer's claims the retrieved context supports | 0-1, higher is better |
| `citation_entailment` | Fraction of (claim → cited passage) links where the passage entails the claim | 0-1, higher is better |
| `claim_citation_support` | Fraction of cited claims backed by at least one of their own citations | 0-1, higher is better |
| `uncited_claim_rate` | Fraction of claims carrying no citation marker | 0-1, lower is better |
| `contextual_prefix_factuality` | Fraction of contextual prefixes supported by their source chunk | 0-1, higher is better |

`groundedness` is its own weighted-score objective, weighted `0.0` by default — reported, not scored, until an operator decides otherwise.

### Abstention

Measures how the system handles unanswerable questions. Uses phrase matching against the answer text (e.g., "I don't have enough information").

| Metric | What it measures | Range |
|---|---|---|
| `unanswerable_accuracy` | Correctly abstains on unanswerable, correctly answers answerable | 0-1, higher is better |
| `abstention_false_positive_rate` | Rate of incorrect abstention on answerable questions | 0-1, lower is better |
| `abstention_false_negative_rate` | Rate of hallucinated answers on unanswerable questions | 0-1, lower is better |

### Performance

Operational metrics. Not factored into accuracy scoring.

| Metric | What it measures | Unit |
|---|---|---|
| `latency_p50` | Median query latency | milliseconds |
| `latency_p95` | 95th percentile query latency | milliseconds |
| `cost_per_query` | Dollar cost from token usage — generation plus judging, each priced at its own model's rates | USD |

### Retrieval funnel

The headline retrieval artifact, built by `evals/funnel.py` from the per-stage scores the
ranking metrics already compute (`MetricResult.details["stage_scores"]`). It reports recall@5
at each stage — `bm25`, `vector`, `fusion`, `rerank` — and splits total retrieval loss into the
only two kinds there are:

| Field | Meaning | Points at |
|---|---|---|
| `lost_before_candidates` | `1 - ceiling`: evidence never reached the candidate list | chunking, embeddings, BM25/vector balance, `top_k` |
| `lost_in_rerank` | `ceiling - final`: evidence retrieved, then ranked out | the reranker, `final_top_n` |

`bottleneck` names whichever is larger, or `None` when their sum is under 5% — at which point
the question set can no longer tell configurations apart. Built once in the runner and saved on
the run, so the CLI report, the eval API and the dashboard cannot derive it differently. A run
with no per-stage scores yields an unmeasured funnel carrying the reason, never a zero.

### Weighted Scoring

> Retained for continuity with existing runs and **not** a headline — its retrieval objective
> averages `recall@1`, `recall@5`, `mrr` and `nDCG@10`, metrics in different units, then weights
> the result against an LLM-judge score. Read the funnel and the per-group metrics instead.
> `docs/suggestions.md` §2.11 records what removing it properly requires.

All metric groups (except performance) are combined into a single weighted score. The weights
and the latency/cost normalization thresholds live under `eval.scoring` in the repo-root
`config.yml` — a deployment with a different latency or cost profile changes what the weighted
score rewards there, not in code.

| Objective | Default Weight | Fed by |
|---|---|---|
| `accuracy` | 0.30 | Generation metrics + Abstention metrics |
| `faithfulness` | 0.20 | Generation metrics |
| `citation` | 0.20 | Citation metrics |
| `retrieval` | 0.15 | Retrieval metrics |
| `cost` | 0.10 | Cost per query |
| `latency` | 0.05 | Latency P50 (inverted: 0 ms = 1.0, `latency_threshold_ms_*` = 0.0) |

Metrics that are undefined for a dataset — citation metrics with no gold passages, retrieval
metrics on a question set with no annotations — report `null`, not 0.0 or 1.0, and are excluded
from the objectives they would otherwise feed.

## Running Evaluations

### Prerequisites

1. RAG server running at `localhost:8001` (via `docker compose up -d`)
2. Documents already uploaded and indexed
3. The API key for whatever provider `active.eval` names, if using the LLM judge
   (generation metrics) — `OPENAI_API_KEY` in the shipped defaults

### CLI

Run from `services/evals/`:

```bash
# Quick eval (10 samples from RAGBench, no LLM judge)
python -m evals.cli eval --samples 10 --no-judge

# Full eval with LLM judge (key must match active.eval's provider)
export OPENAI_API_KEY=sk-...
python -m evals.cli eval --samples 100

# Multiple datasets
python -m evals.cli eval --datasets ragbench,squad_v2,hotpotqa --samples 20

# Custom RAG server URL
python -m evals.cli eval --rag-url http://my-server:8001 --samples 10

# From YAML config
python -m evals.cli eval --config eval_config.yml

# List available datasets
python -m evals.cli datasets

# Show dataset statistics
python -m evals.cli stats

# Export a run to CSV
python -m evals.cli export --run-id abc123 --format csv

# Export a per-question review sheet with blank reviewer columns
python -m evals.cli export --run-id abc123 --format review-csv
python -m evals.cli export --run-id abc123 --format review-md

# Export a full Markdown run report
python -m evals.cli export --run-id abc123 --format report

# Compare runs — paired bootstrap CIs and McNemar are reported by default
python -m evals.cli compare baseline candidate

# Add Pareto analysis, or skip significance testing
python -m evals.cli compare run1 run2 --pareto --no-significance

# Calibrate the LLM judge against RAGBench TRACe ground-truth labels
python -m evals.cli calibrate --samples 20
```

### Programmatic

```python
from evals import EvalConfig, run_evaluation, DatasetName

config = EvalConfig(
    datasets=[DatasetName.RAGBENCH, DatasetName.SQUAD_V2],
    samples_per_dataset=50,
    rag_server_url="http://localhost:8001",
)
result = run_evaluation(config)
```

### Via pytest

```bash
pytest tests/test_rag_eval.py --run-eval --eval-samples=5
```

Note: the pytest tests primarily validate the metric calculations and dataset loading in isolation. They do not run the full eval-against-server flow.

## Execution Flow

When you run an evaluation, the runner performs these steps:

```
1. Health check         GET /health on RAG server
2. Snapshot config      GET /models/info (LLM, embedding, reranker) and
                        GET /metrics/retrieval (top_k, hybrid, contextual). A value
                        the server does not return is stored as null, never guessed.
3. Load datasets        Download from HuggingFace (RAGBench, SQuAD, etc.)
4. Query loop           For each question:
                          POST /query → RAG server does full pipeline
                          (embed query → hybrid retrieval → rerank → LLM generation)
                          → measure latency, parse response
5. Compute metrics      Run all metric classes against question/response pairs
6. Score                Build the retrieval funnel; compute the weighted score
7. Save                 Write run results as JSON to data/eval_runs/, a copy to
                        data/eval_runs/backup/, and the per-question samples to
                        data/eval_runs/{run}_samples.json (used by the review exports)
```

The framework treats the RAG server as a **black box over HTTP**. It never imports server internals. The `RAGClient` class sends questions via `POST /query` and parses the JSON response (answer text, sources, citations, token usage).

## Available Datasets

Each dataset targets specific evaluation aspects:

| Dataset | Aspects | Source | Notes |
|---|---|---|---|
| `ragbench` | generation, retrieval | HuggingFace: galileo-ai/ragbench | Multi-domain with TRACe annotations. Default: curated mix (covidqa, finqa, cuad, techqa). Relevance-annotated docs become gold passages; the rest are ingested as distractors |
| `qasper` | citation, generation | HuggingFace: allenai/qasper | Long-document evidence grounding. Loads via the `refs/convert/parquet` revision; verified working on `datasets` 4.5 |
| `squad_v2` | abstention | HuggingFace: rajpurkar/SQuAD_v2.0 | ~50% unanswerable questions |
| `hotpotqa` | retrieval, generation | HuggingFace: hotpot_qa | Multi-hop reasoning |
| `msmarco` | retrieval | HuggingFace: ms_marco | Retrieval ranking |
| `golden` | generation, retrieval | Local: `evals/data/golden_qa.json` | Curated Q&A pairs for your own documents. Add `gold_passages` or `gold_doc_ids` per entry to make retrieval and citation metrics measurable |

## Directory Structure

```
evals/
├── __init__.py              Re-exports public API (EvalConfig, run_evaluation, etc.)
├── __main__.py              Entry point for `python -m evals`
├── cli.py                   CLI commands: eval, stats, datasets, export, compare, calibrate
├── config.py                EvalConfig, DatasetName enum, model cost table, weights
├── runner.py                EvaluationRunner + RAGClient (HTTP client to RAG server)
├── funnel.py                Retrieval funnel: per-stage recall, the two losses, the bottleneck
├── calibration.py           Judge calibration vs RAGBench TRACe ground-truth labels
├── export.py                Export results to JSON/CSV/Markdown for manual review
├── samples.py               Per-question sample sidecar (save/load)
├── stats.py                 Paired bootstrap CIs, McNemar, Benjamini-Hochberg
│
├── schemas/
│   ├── dataset.py           EvalQuestion, GoldPassage, EvalDataset
│   ├── response.py          EvalResponse, Citation, RetrievedChunk, TokenUsage
│   └── results.py           MetricResult, MetricGroup, Scorecard, WeightedScore,
│                             ParetoPoint, EvalRun
│
├── metrics/
│   ├── base.py              BaseMetric ABC (compute, compute_batch)
│   ├── retrieval.py         RecallAtK, PrecisionAtK, MRR, NDCG
│   ├── generation.py        Faithfulness, AnswerCorrectness, AnswerRelevancy
│   ├── citation.py          CitationPrecision, CitationRecall, SectionAccuracy
│   ├── abstention.py        UnanswerableAccuracy, FalsePositiveRate, FalseNegativeRate
│   └── performance.py       LatencyP50, LatencyP95, CostPerQuery
│
├── judges/
│   └── llm_judge.py         LLMJudge — calls the resolved active.eval model to score faithfulness/correctness/relevancy
│
├── datasets/
│   ├── base.py              BaseDatasetLoader ABC
│   ├── registry.py          Dataset registry (register, get_loader, list_available)
│   ├── ragbench.py          RAGBench loader (12 subsets, TRACe-aware gold/distractor split)
│   ├── qasper.py            Qasper loader
│   ├── squad_v2.py          SQuAD v2 loader
│   ├── hotpotqa.py          HotpotQA loader
│   ├── msmarco.py           MS MARCO loader
│   └── golden.py            Local golden dataset loader
│
└── data/
    └── golden_qa.json       Curated Q&A pairs for local evaluation
```

### Key files by role

**Orchestration:** `runner.py` contains `EvaluationRunner` which drives the entire eval. `RAGClient` is the HTTP client that talks to the RAG server. `cli.py` provides the command-line interface.

**Data contracts:** `schemas/` defines the dataclasses used everywhere. `EvalQuestion` + `GoldPassage` represent inputs. `EvalResponse` + `RetrievedChunk` + `Citation` represent outputs. `MetricResult` + `Scorecard` + `EvalRun` represent results.

**Metrics:** Each metric class inherits from `BaseMetric`, implements `compute(question, response) -> MetricResult`, and declares its `MetricGroup`. Generation metrics additionally require an `LLMJudge` instance.

**Datasets:** Each loader inherits from `BaseDatasetLoader`, downloads from HuggingFace, and converts to `EvalDataset` containing `EvalQuestion` objects with gold passages.

## Run Output

Results are saved to `data/eval_runs/{run_id}_{timestamp}.json` with this structure:

```json
{
  "id": "a1b2c3d4",
  "name": "eval-a1b2c3d4",
  "created_at": "2025-01-15T10:30:00",
  "completed_at": "2025-01-15T10:35:00",
  "config": {
    "llm_model": "Qwen/Qwen2.5-14B-Instruct",
    "llm_provider": "vllm",
    "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
    "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "retrieval_top_k": 10,
    "hybrid_search_enabled": true,
    "contextual_retrieval_enabled": false
  },
  "datasets": ["ragbench"],
  "scorecard": {
    "metrics": [
      {"name": "recall_at_5", "value": 0.72, "group": "retrieval", "sample_size": 100},
      {"name": "faithfulness", "value": 0.85, "group": "generation", "sample_size": 100}
    ],
    "by_group": {
      "retrieval": ["recall_at_1", "recall_at_3", "recall_at_5", "precision_at_5", "mrr", "ndcg_at_10"],
      "generation": ["faithfulness", "answer_correctness", "answer_relevancy"]
    }
  },
  "retrieval_funnel": {
    "stages": [
      {"name": "bm25",   "recall": 0.55, "delta": null, "questions_scored": 40},
      {"name": "vector", "recall": 0.72, "delta": null, "questions_scored": 40},
      {"name": "fusion", "recall": 0.81, "delta": 0.09, "questions_scored": 40},
      {"name": "rerank", "recall": 0.54, "delta": -0.27, "questions_scored": 40}
    ],
    "ceiling": 0.81,
    "final": 0.54,
    "lost_before_candidates": 0.19,
    "lost_in_rerank": 0.27,
    "bottleneck": "rerank",
    "diagnosis": "The candidate list contains the evidence 81% of the time, but only 54% survives reranking..."
  },
  "weighted_score": {
    "score": 0.73,
    "objectives": {"accuracy": 0.85, "retrieval": 0.72, "citation": 0.60},
    "weights": {"accuracy": 0.30, "retrieval": 0.15, "citation": 0.20}
  },
  "question_count": 100,
  "error_count": 2,
  "metadata": {
    "tier": "end_to_end",
    "judge_model": "gpt-5.2",
    "judge_provider": "openai",
    "judge_execution_boundary": "third_party",
    "judge_independence_warning": null,
    "scoring": {"weights": {}, "latency_threshold_ms": 30000, "max_cost_per_query_usd": 0.1}
  }
}
```

Each metric also carries `details.per_question` — a `{question_id: score}` map. That is what
makes two runs pairable, and it is what `compare` bootstraps over. A metric that is undefined for
the dataset has `"value": null` and `"sample_size": 0`.

## Comparing runs

`compare` reports a paired bootstrap confidence interval on every metric both runs scored, over
the questions they have in common:

```
Metric                          n      delta                 95% CI         p  verdict
recall_at_5                   100    +0.0620  [+0.0180, +0.1060]    0.0064  significant
faithfulness                  100    +0.0100  [-0.0290, +0.0490]    0.6120  not significant
```

- Binary metrics (recall, abstention accuracy) additionally get McNemar's exact test and the
  discordant counts, so you see how many questions actually flipped and in which direction.
- Comparisons below 100 paired questions are flagged `underpowered` — indicative only.
- Benjamini-Hochberg is applied across the metric family; `significant` means it survived the
  correction, `nominal (fails BH)` means the interval excluded zero but the correction rejected it.
  Scanning ~20 metrics uncorrected gives roughly a 64% chance of at least one spurious mover.

The same data is available from the API at `GET /eval/runs/compare?ids=a,b` under `significance`.
