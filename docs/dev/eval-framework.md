# Evaluation Framework

## Why Evaluate RAG Systems

RAG systems combine two failure-prone components: retrieval (finding relevant context) and generation (producing accurate answers). Evaluation ensures:
- **Retrieval Quality**: Are we finding the right chunks?
- **Answer Quality**: Is the generated response accurate and relevant?
- **Safety**: Are we hallucinating or producing unsupported claims?

Without systematic evaluation, configuration changes (chunk size, top-k, reranking) are guesswork.

## Evaluation Approach

**Test Dataset**: Golden Q&A pairs (question, expected answer, ground truth context)
- Current: 10 pairs from Paul Graham essays
- Target: 100+ pairs for production confidence
- Location: `services/evals/evals/data/golden_qa.json`

**Evaluation Types**:
- **Retrieval Metrics**: Measure if correct chunks are retrieved
- **Generation Metrics**: Measure answer accuracy and relevance
- **Safety Metrics**: Detect hallucinations and unsupported claims

**Public Datasets**: Five additional datasets available for comprehensive evaluation (retrieval, generation, citation, abstention). List them with `just eval-datasets` or `GET /eval/datasets`.

## Framework: In-House

Metrics and the LLM-as-judge are implemented in this repo (`services/evals/evals/metrics/`
and `evals/judges/llm_judge.py`) — no third-party eval framework is used. The
project moved from RAGAS to DeepEval (2025-12-07), then off DeepEval as the
metrics were replaced with hand-rolled ones; the dependency was dropped once
nothing imported it.

**LLM Judge**: the model set as `active.eval` in `config.yml` (cloud provider, e.g. OpenAI or Anthropic) - evaluates retrieval relevance, answer faithfulness, and hallucination detection. Note that judge prompts are **not** PII-masked — see [pii-masking.md](pii-masking.md) for the gate that enforces this.

**Integration**:
- Pytest integration with custom markers (`@pytest.mark.eval`)
- CLI tool for standalone evaluation
- CI/CD compatible (optional eval tests on demand)
- Results stored in `evals/data/runs/` for metrics API

### Decision: staying in-house (reviewed 2026-08-01)

Re-adopting DeepEval (or RAGAS/Phoenix) was considered and declined. Reasons, in
order of weight:

1. **It would trade a calibrated judge for an uncalibrated one.** `evals/calibration.py`
   measures our judge against RAGBench's human-verified TRACe labels. Third-party
   metrics arrive with prompts we don't control and no calibration for this corpus,
   so the calibration work would have to be redone against them.
2. **Telemetry posture conflicts with the product thesis.** DeepEval phones home on
   import (public IP via `api.ipify.org`) and is oriented toward a hosted platform.
   The judge path is also the one place with no PII masking — see the gate in
   [pii-masking.md](pii-masking.md). A default-telemetry dependency on exactly that
   path is the wrong direction for a privacy-first product.
3. **Low overlap, high switching cost.** A framework would replace roughly the ~200
   LOC in `metrics/generation.py` out of ~6,300, and contributes nothing to the six
   dataset loaders, citation/abstention metrics, Pareto frontier, cost telemetry, or
   the dashboard API.

**What would justify revisiting**: needing metrics we don't want to maintain
(e.g. multi-turn conversational, agentic tool-use, or red-teaming suites), or a
team large enough that maintaining metric implementations stops being worthwhile.
If that happens, prefer vendoring specific metric *implementations* over adopting a
framework wholesale, and check the telemetry defaults first.

**Worth stealing regardless**: G-Eval's scoring approach (chain-of-thought plus
token-probability weighting) discriminates better than the current single-shot
`SCORE: 0.8` parse. That is an idea to port into `llm_judge.py`, not a reason to
take the dependency.

### Failed judge calls are excluded, not scored 0.0

A judge call that fails is missing data, not evidence of an unfaithful answer, so it
never contributes a score:

- `_parse_response` raises `JudgeParseError` when the response has no `SCORE:` line or
  an unparseable one. This engages `_evaluate`'s retry loop — previously a malformed
  response was accepted as a valid 0.0, so `max_retries` did nothing for that case.
- `_evaluate` raises `JudgeError` once retries are exhausted.
- `BaseMetric.compute_batch` catches it in `_run_one`, drops the sample, and reports
  the reduced `sample_size`; the average is over successes only.
- `calibration.py` drops the item and reports `dropped_judge_failures` /
  `items_requested` in the result metadata, so a run over a flaky judge is visibly
  thin rather than quietly computed over whatever succeeded.

Genuine 0.0 scores still exist and are distinct: no context retrieved (`Faithfulness`)
and no expected answer defined (`AnswerCorrectness`).

## Metrics & Thresholds

**Retrieval Metrics**:
- **Contextual Precision** (threshold: 0.7): Are retrieved chunks relevant to the query?
- **Contextual Recall** (threshold: 0.7): Did we retrieve all information needed to answer?

**Generation Metrics**:
- **Faithfulness** (threshold: 0.7): Is the answer grounded in retrieved context?
- **Answer Relevancy** (threshold: 0.7): Does the answer address the question?

**Safety Metrics**:
- **Hallucination** (threshold: 0.5): Rate of claims not supported by context

Higher scores are better (except hallucination - lower is better).

## Running Evaluations

**Prerequisites**: the API key secret file for the `active.eval` provider in `config.yml` (e.g. `secrets/OPENAI_API_KEY` or `secrets/ANTHROPIC_API_KEY`), Docker services running.

**Via API** (recommended for webapp integration):
```bash
# Trigger a run
curl -X POST http://localhost:8002/eval/runs \
  -H 'Content-Type: application/json' \
  -d '{"tier": "generation", "datasets": ["ragbench"], "samples": 5}'

# Poll progress
curl http://localhost:8002/eval/runs/active

# View results
curl http://localhost:8002/eval/runs

# Dashboard summary
curl http://localhost:8002/eval/dashboard
```

**Via CLI** (inside the running evals container):
```bash
# Quick evaluation (5 samples)
docker compose exec evals .venv/bin/python -m evals.cli eval --tier generation --datasets ragbench --samples 5

# Full evaluation
docker compose exec evals .venv/bin/python -m evals.cli eval --tier end_to_end --datasets ragbench

# List datasets
docker compose exec evals .venv/bin/python -m evals.cli datasets
```

**Via just**:
```bash
just test-eval              # Quick end-to-end smoke test (5 samples)
just test-eval-full         # Full end-to-end suite
just eval --tier generation --datasets ragbench,squad_v2,golden --samples 5   # Custom run
just eval-datasets          # List datasets
just eval-calibrate         # Calibrate LLM judge
just eval-compare id1 id2   # Compare runs
```

**CI/CD**: Evaluation tests are optional (expensive, ~2-5min). Trigger via commit message containing `[eval]` or manual workflow dispatch.

## Eval Service API (port 8002)

The eval service runs as a standalone FastAPI app. The webapp proxies `/api/eval/*` to it.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/eval/runs` | Trigger eval run (202 / 409 if busy) |
| GET | `/eval/runs/active` | Current job progress (null if idle) |
| DELETE | `/eval/runs/active` | Cancel running job |
| GET | `/eval/runs` | List completed runs (paginated) |
| GET | `/eval/runs/{run_id}` | Full run detail with scorecard |
| GET | `/eval/runs/compare?ids=a,b` | Compare runs with metric deltas |
| GET | `/eval/dashboard` | Latest run + active job summary |
| GET | `/eval/datasets` | Available datasets with tier support |
| GET | `/health` | Health check |

**Dashboard Metrics** (computed on-the-fly from scorecard):

| Metric | Scale | Source |
|--------|-------|--------|
| Retrieval Relevance | 0-1 | avg(recall@5, mrr) — null for generation tier |
| Faithfulness | 0-1 | faithfulness (LLM judge) |
| Answer Completeness | 0-1 | answer_correctness (LLM judge) |
| Answer Relevance | 0-1 | answer_relevancy (LLM judge) |
| Response Latency | seconds | latency_p50_ms / latency_p95_ms |

**Trigger request:**
```json
{
  "tier": "generation",
  "datasets": ["ragbench"],
  "samples": 20,
  "seed": 42,
  "judge_enabled": true
}
```

**Design decisions:**
- One job at a time (evals are resource-intensive)
- No database — JSON files on disk, in-memory index rebuilt on startup
- Polling via `GET /eval/runs/active` (every 2-3s during a run)
- Background `threading.Thread` runs `asyncio.run()` over the async runner
- Async parallelization: RAG queries and LLM judge calls run concurrently via `asyncio.gather()` + `Semaphore`
- Concurrency controlled by `query_concurrency` (default 10) and `judge_concurrency` (default 10) in `EvalConfig`
- Progress callback + cancellation via `threading.Event`

## Research References

- [Evidently AI - RAG Evaluation Guide](https://www.evidentlyai.com/llm-guide/rag-evaluation)
- [Braintrust - RAG Evaluation Tools 2025](https://www.braintrust.dev/articles/best-rag-evaluation-tools)
- [Patronus AI - RAG Best Practices](https://www.patronus.ai/llm-testing/rag-evaluation-metrics)
