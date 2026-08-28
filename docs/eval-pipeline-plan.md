# Plan: per-stage RAG evaluation

**Audience.** An implementing agent starting from a clean context. Each phase is
self-contained: read this header, then read only your phase.

**Goal.** Today the eval stack says *whether* the RAG is good. It cannot say
*which stage* made it worse. This plan makes every stage of the pipeline
measurable on the five core metrics — **accuracy, completeness, hallucination,
speed, cost** — so a regression can be attributed to parsing, chunking,
embedding, a retrieval leg, fusion, reranking, or generation.

**Evidence rule.** Every `file:line` below was checked against the tree. If a
reference does not match what you find, trust the tree and say so; do not
implement against a stale line number.

---

## Invariants — apply to every phase

1. **`None` is not `0.0`.** A metric with no data returns
   `MetricResult(value=None)` (`evals/schemas/results.py:22`). Never coerce, never
   render as zero. This extends to every new metric and to lineage failures.
2. **Judge-free by default.** Only generation and citation metrics may call an
   LLM. Everything in phases 1–4 and 6 is arithmetic on stage outputs. This is
   what makes per-stage attribution cheap enough to run on every sweep.
3. **Do not change pipeline behaviour.** No phase changes retrieval defaults,
   chunking defaults, scoring weights, prompts, or the embedding model. These are
   measurement changes. A phase that alters a number the system produces has
   overstepped.
4. **Every new metric registers explicitly** in `METRIC_GROUPS`
   (`evals/metrics/__init__.py:38`) and declares `requires_judge` and
   `requires_gold` (`evals/metrics/base.py:32-36`).
5. **House style** (from `CLAUDE.md`): module-level functions over classes; no
   ORM — query builders or explicit SQL; SQL-schema migrations; `uv` for Python.
   Skip docstrings on private helpers; type hints replace parameter docs.
6. **Privacy gate is load-bearing.** `enforce_judge_boundary()`
   (`evals/infrastructure/config/models_config.py:414`) fails closed on a
   confidential corpus with an out-of-boundary judge. Any new model or endpoint
   entry declares `execution_boundary`. Do not add a bypass.
7. **No new eval platform.** Postgres plus files on disk. No MLflow, Langfuse,
   Phoenix server, Ragas, or DeepEval as system of record.

---

## Decisions already made — do not relitigate

| Decision | Reason |
|---|---|
| **`ir-measures` for ranking math** | `evals/metrics/retrieval.py` is 298 lines of hand-rolled recall/MRR/nDCG. nDCG has several defensible variants; a hand-rolled one is a coin flip on which was implemented. |
| **No OpenTelemetry dependency** | Stage traces are plain dataclasses in phase 1. OTel is a serialization choice that can be added later without touching metric code. Adding it now buys nothing and couples the metrics to an unstable `gen_ai.*` semconv. |
| **Judge stays in-house** | The metric layer is the asset. Adopt infrastructure, not metrics. |
| **Source-coordinate ground truth, not chunk ids** | A chunk-size sweep invalidates chunk-id anchoring — the sweep would regenerate its own ground truth and compare it against itself. Phase 3 exists for this reason. |
| **Judged metrics on a confidential corpus require the AWS private deployment** | The only in-boundary judge is `qwen38-27b-judge`, and it exists only in Mode B (`docs/private-model-slate-plan.md`). Phases 1–4 and 6 are judge-free and run on a laptop; only phase 5 needs the GPU. |

---

## Orientation

**Two services.**

- **`services/rag_server`** — the system under test. FastAPI.
  - Query path: `api/routes/query.py:15` → `pipelines/inference.py`
  - Ingestion: `pipelines/ingestion.py`
  - Retrieval legs: `infrastructure/search/{bm25_retriever,vector_retriever,hybrid_retriever}.py`
  - Response schemas: `schemas/query.py`
  - Config: `infrastructure/config/models_config.py`, root `config.yml`
- **`services/evals`** — the evaluator. FastAPI + CLI.
  - Orchestration: `evals/runner.py` (`EvaluationRunner:260`, `RAGClient:78`,
    `parse_rag_response:188`)
  - Metrics: `evals/metrics/*.py`, all subclass `BaseMetric`
  - Schemas: `evals/schemas/{dataset,response,results}.py`
  - Datasets: `evals/datasets/` — revisions pinned, sampling unbiased, cache
    fingerprinted (already correct; do not rework)
  - Judge: `evals/judges/llm_judge.py`; stats: `evals/stats.py`; pricing:
    `evals/pricing.py`
- **Database schema:** `services/postgres/init.sql`. It runs **only on a volume's
  first boot** — there are no migrations. Any schema change means
  `docker compose down -v` and re-ingest, so batch schema work.

**Stages that exist in code but are invisible to the evaluator.**

| Stage | Where | What is discarded |
|---|---|---|
| BM25 leg | `hybrid_retriever.py:45` | ranked list |
| Vector leg | `hybrid_retriever.py:46` | ranked list |
| RRF fusion | `hybrid_retriever.py:66` `_fuse_results` | per-leg contribution |
| Rerank | `pipelines/inference.py` (`SentenceTransformerRerank`) | pre-rerank list |
| Parse / chunk | `ingestion.py:132`, `:186` | timings, element lineage |
| Contextual enrich | `ingestion.py:390` — **already times itself**, reports nothing | tokens, USD, success rate |

**What the evaluator sees today:** one `latency_ms` and one final ranked list
(`evals/schemas/response.py`, `QueryMetrics`). That single number is the whole
reason attribution is impossible.

---

## Target state

Deliverable of the whole plan. Each cell names a metric; the number is the phase
that builds it.

| Stage | Accuracy | Completeness | Hallucination | Speed | Cost |
|---|---|---|---|---|---|
| Parse | element retention, lineage integrity ③ | — | — | parse ms/doc ② | — |
| Chunk | evidence containment ④ | evidence fragmentation, orphaned evidence ④ | — | chunk ms/doc ② | — |
| Contextual enrich | prefix factuality ⑤ | enrichment success rate ② | prefix factuality ⑤ | enrich ms/doc ② | **USD/doc ②** |
| Embed | pre-rerank Recall@k, nDCG@10 ④ | evidence-set recall ④ | — | embed ms ② | USD/1k chunks ② |
| BM25 leg | Recall@k, MRR per leg ④ | — | — | leg ms ① | 0 |
| Vector leg | Recall@k, MRR per leg ④ | — | — | leg ms ① | 0 |
| Fusion | fusion lift over best leg ④ | evidence-set recall ④ | — | fuse ms ① | 0 |
| Rerank | promotions / demotions ④ | candidate recall ceiling ④ | — | rerank ms p50/p95 ① | 0 |
| Generation | `answer_correctness` (exists) | **`answer_completeness` ⑤** | `faithfulness`, `claim_groundedness` ⑤ | TTFT, gen ms ① | USD/query (exists) |
| Citation | citation precision/recall (exists) | uncited claim rate ⑤ | citation entailment ⑤ | — | — |

Cross-cutting: failure attribution ⑥, experiment store ⑥, decision discipline ⑦.

---

# Phase 1 — Query-path stage observability

**Load into context:** `services/rag_server/infrastructure/search/hybrid_retriever.py`,
`services/rag_server/pipelines/inference.py`, `services/rag_server/api/routes/query.py`,
`services/rag_server/schemas/query.py`, `services/evals/evals/schemas/response.py`,
`services/evals/evals/runner.py:188-260`.

**Goal.** Every query emits per-stage ranked lists and per-stage timings, and a
retrieval-only endpoint exists so retrieval sweeps cost zero LLM tokens.

**Why first.** Nothing downstream can attribute anything without this. It is also
the highest leverage-to-effort item in the plan: `_fuse_results` already computes
the per-leg lists and throws them away.

### Build

1. **`StageTrace` dataclass** (new, `services/rag_server/schemas/query.py`):
   ```
   name: str                    # bm25 | vector | fusion | rerank | context_assembly
                                # | generation | citation
   duration_ms: float
   item_count: int
   items: list[StageItem] | None # None when the stage does not produce a ranking
   status: str                  # ok | degraded | failed
   error: str | None
   ```
   `StageItem`: `chunk_id`, `doc_id`, `score`, `rank`.

2. **Thread the leg lists out of `HybridRRFRetriever`.** `_retrieve` /
   `_aretrieve` (`hybrid_retriever.py:42,50`) currently pass `bm25_results` and
   `vector_results` straight into `_fuse_results` and drop them. Retain them on
   the retriever instance or return them alongside the fused list. **Do not change
   the fusion math** — `_fuse_results:81-106` stays byte-identical in behaviour.

3. **Capture the pre-rerank list** in `pipelines/inference.py` before the
   `SentenceTransformerRerank` postprocessor runs, and the post-rerank list after.
   Both go into `StageTrace`s.

4. **`POST /search`** in `api/routes/query.py`. Request: `query`, `top_k`,
   optional `stages: list[str]` filter. Response: the `StageTrace` list only.
   **No generation, no LLM call, no session, no chat memory.** This is the
   endpoint every retrieval and chunking sweep will use.

5. **Extend `QueryMetrics`** (`schemas/query.py`) with `stages: list[StageTrace]`.
   Add `time_to_first_token_ms` populated on the streaming path
   (`api/routes/query.py:121` `/query/stream`).

6. **Mirror into evals.** `evals/schemas/response.py` `QueryMetrics` gains
   `stages`; `runner.py:188` `parse_rag_response` populates it; `RAGClient`
   (`runner.py:78`) gains a `search()` method hitting `POST /search`.

### Verify

- `POST /search` returns non-empty `bm25`, `vector`, `fusion`, `rerank` traces,
  each respecting `top_k`.
- Sum of stage `duration_ms` ≤ total `latency_ms` (they nest; assert the bound).
- **Regression gate:** an existing `just eval` run produces the same headline
  metric values as before the change. Behaviour is unchanged; only visibility
  moved.
- A query with the embedder down yields `status: degraded` on the vector stage
  rather than a silent empty list — the failure mode `just demo-check` exists to
  catch.

### Do not

Add OTel. Change ranking or fusion. Emit stage items for chunks the caller is not
already entitled to see (`POST /search` respects the same auth as `/query`).

---

# Phase 2 — Ingestion observability and cost completion

**Load into context:** `services/rag_server/pipelines/ingestion.py`,
`services/evals/evals/pricing.py`, `services/evals/evals/metrics/performance.py`,
`services/postgres/init.sql`.

**Goal.** Per-document ingestion time and USD, attributable to a stage; embedding
cost enters the cost model.

**Why it matters.** Contextual retrieval makes a per-chunk LLM call and is
believed to dominate ingestion time, but this is unmeasured (`CLAUDE.md`,
`docs/suggestions.md` §5.3). Ingestion cost is currently absent from every
scorecard, so a change that halves query cost while tripling ingestion cost looks
like a pure win.

### Build

1. **Stage traces for ingestion**: `parse`, `chunk`, `contextual_enrich`,
   `embed`, `index`. `_add_contextual_retrieval_async` (`ingestion.py:390`)
   already computes elapsed time at `:396` — surface it rather than re-timing.

2. **Token accounting for contextual prefixes.**
   `add_contextual_prefix_to_chunk_async` (`ingestion.py:353`) makes the LLM call;
   return its token usage and aggregate per document. Also count **failures** —
   a per-chunk failure currently leaves a partly-contextualized document silently
   (`docs/internal/rag-pipeline.md:138`). Emit `enrichment_success_rate`.

3. **Persist per-document stage records.** New table in
   `services/postgres/init.sql`:
   ```sql
   CREATE TABLE IF NOT EXISTS document_ingestion_stages (
       id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       document_id   UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
       stage         TEXT NOT NULL,
       duration_ms   DOUBLE PRECISION NOT NULL,
       input_tokens  INTEGER,
       output_tokens INTEGER,
       item_count    INTEGER,
       status        TEXT NOT NULL DEFAULT 'ok',
       error         TEXT,
       created_at    TIMESTAMPTZ DEFAULT NOW()
   );
   CREATE INDEX IF NOT EXISTS idx_ingestion_stages_doc
       ON document_ingestion_stages(document_id);
   ```
   Schema changes require `docker compose down -v` — do all of phase 2 and
   phase 3's schema work in one pass if you can.

4. **Fold embedding cost into the cost model.** `evals/pricing.py:71` carries
   `EMBEDDING_COSTS` with the comment *"not yet part of CostPerQuery"*. Make it
   part of it. Note that the default embedder is self-hosted TEI, so its marginal
   rate is an amortized instance rate, not a vendor price — use the same explicit
   `MODEL_PRICE_OVERRIDES` mechanism (`pricing.py:32`), never an implicit zero.

5. **New metric `IngestionCostPerDocument`** in a new
   `evals/metrics/ingestion.py`, reporting USD/doc broken down by stage, plus
   `IngestionLatencyPerDocument`. Register both.

### Verify

- Ingest one sample document with `enable_contextual_retrieval` on and off; the
  reported ingestion cost delta is non-zero and reconciles with the token counts.
- Kill the LLM mid-ingest: `enrichment_success_rate` drops below 1.0 and the
  document is flagged, not silently accepted.
- `cost_per_query` changes when embedding cost is included, and the change is
  arithmetically explainable from chunk counts.

### Do not

Price an unpriced model at zero. An unpriced model is **excluded from cost
scoring and its `cost: 0.10` weight is redistributed** across the other
objectives (`config.yml` `eval.scoring.weights`), which silently changes the
headline score. If you want a zero rate, set an explicit zero.

---

# Phase 3 — Evidence locator and chunk lineage

**Load into context:** `services/evals/evals/schemas/dataset.py`,
`services/evals/evals/metrics/text_match.py`,
`services/evals/evals/metrics/retrieval.py`,
`services/rag_server/pipelines/ingestion.py`, `services/postgres/init.sql`.

**Goal.** Ground truth anchored to source coordinates, so it survives a chunking
or parsing change. Retire the fuzzy match as the retrieval ground-truth path.

**Why now.** `chunk_size` and `chunk_overlap` are real config
(`config.yml:301-302`), so a chunk-size sweep is *runnable today* — and
uninterpretable, because gold is anchored by `chunk_id`
(`evals/schemas/dataset.py` `GoldPassage.chunk_id`) with a Jaccard ≥ 0.3 fallback
(`metrics/text_match.py:25`) whose error rate nobody has measured. Re-chunking
invalidates the anchors, so the sweep would regenerate its own ground truth and
compare it against itself. **Runnable-but-wrong is worse than blocked.**

### Build

1. **`EvidenceLocator`** in `evals/schemas/dataset.py`:
   ```
   document_hash: str            # matches documents.file_hash
   source_format: str            # pdf | html | docx | pptx | xlsx | md | txt
   locator: dict                 # format-specific, see below
   normalized_text: str          # secondary check
   normalized_text_hash: str
   evidence_set_id: str | None   # groups passages that are jointly required
   ```
   `locator` by format:
   - text / HTML / Markdown — `{element_path, start_char, end_char}`
   - PDF / OCR — `{page, bbox, block_id}`
   - DOCX / PPTX — `{element_id}`
   - spreadsheet — `{sheet, row, col}` or `{sheet, range}`

2. **`GoldPassage.chunk_id` becomes optional**; `EvalQuestion.gold_passages`
   gains `evidence: list[EvidenceLocator]`. Public HF datasets that genuinely have
   no source coordinates keep the old path but their runs are **labelled
   `ground_truth: chunk_id`** so the two are never silently mixed.

3. **Chunk lineage.** Add `source_locator JSONB` to `document_chunks`
   (`init.sql:22`), written at chunk time by `chunk_document_with_docling`
   (`ingestion.py:132`) and `chunk_document_with_text_splitter` (`:186`) from the
   parser's element offsets.

4. **Overlap-based relevance derivation.** New `evals/evidence.py`: given a
   question's gold locators and the current chunks' `source_locator` values,
   return the relevant chunk ids by **overlap in source-coordinate space**.
   Every retrieval metric consumes this instead of `chunk_id` equality.

5. **Lineage failure is a recorded outcome, not a fallback.** If a chunk has no
   `source_locator`, or a parser cannot reconstruct the mapping, emit
   `lineage_failure` for that question and return `None` for the affected
   metrics. **Do not silently fall back to Jaccard.** Put the reason in the code
   as a comment so nobody "simplifies" it back later.

### Verify

**This test is the entire point of the phase.** Ingest one fixture document at
`chunk_size: 500`, then re-ingest at `chunk_size: 1000`. The same unmodified gold
question resolves to the correct chunk set in both runs. If that passes,
chunk-size sweeps are interpretable; if not, phase 4's chunking metrics are
meaningless.

Also: a document ingested without lineage produces `lineage_failure` and `None`
metrics, never a fuzzy-matched number.

### Do not

Delete `text_match.py` — public benchmarks still need it. Demote it, label it,
and stop it being the default.

---

# Phase 4 — Per-stage retrieval, chunking and rerank metrics

**Load into context:** `services/evals/evals/metrics/retrieval.py`,
`services/evals/evals/metrics/__init__.py`, `services/evals/evals/evidence.py`
(phase 3), `services/evals/evals/runner.py`.

**Goal.** Full attribution for the retrieval half of the pipeline, at zero LLM
cost. This is the phase that delivers the plan's headline capability.

**Depends on:** phases 1 and 3. Without stage lists there is nothing to score per
leg; without locators the scores are anchored to the wrong thing.

### Build

1. **Swap the ranking math to `ir-measures`.** Keep every existing metric *name*
   and its position in `METRIC_GROUPS`. Add a parity test on a fixture asserting
   the new implementation matches the old within tolerance, **then** delete the
   hand-rolled bodies in `metrics/retrieval.py`. Parity first, deletion second —
   if they disagree, the hand-rolled version was probably wrong, but establish
   which before changing reported numbers.

2. **Per-leg metrics**, parameterized by stage rather than duplicated per leg:
   `recall_at_k`, `ndcg_at_10`, `mrr` for `leg ∈ {bm25, vector, fusion, rerank}`.
   Emit as `recall_at_5{leg=bm25}` etc. in `MetricResult.details`, so the
   scorecard keeps one row per metric name.

3. **Attribution metrics** (all `requires_judge = False`):
   - `fusion_lift` — fused nDCG minus the better single leg. Negative means RRF
     is hurting.
   - `rerank_promotions` / `rerank_demotions` — count of relevant chunks the
     reranker moved into / out of the final top-k.
   - `candidate_recall_ceiling` — recall of the **pre-rerank** candidate list.
     The reranker can never exceed this; a low ceiling means the fault is
     upstream and no reranker change will help.
   - `evidence_set_recall` — fraction of questions where **all** chunks in an
     `evidence_set_id` were retrieved, not just one. Multi-hop questions are
     scored as solved today when one of two required passages is found.

4. **Chunking metrics** (need phase 3 locators):
   `evidence_containment` (gold evidence lies wholly within one chunk),
   `evidence_fragmentation` (how many chunks a single evidence span is split
   across), `orphaned_evidence_rate` (evidence present in the document but in no
   chunk).

5. **Delta protocols as runner modes** — A/B over one corpus and question set:
   - contextual retrieval on/off → Δ retrieval metrics **and** Δ ingestion cost
     and wall-clock per document (phase 2 supplies the second half)
   - `bm25_only` / `vector_only` / `fused` with per-source attribution of the
     final top-k

### Verify

Fault localization is the acceptance test, not coverage. Configure a deliberately
bad reranker; `rerank_demotions` must rise while `candidate_recall_ceiling` stays
flat — the metrics localize the fault to the rerank stage. Then degrade the
embedder; the ceiling must drop while rerank behaviour holds. If both faults move
the same metrics, the attribution does not work yet.

### Do not

Change `rrf_k`, `top_k`, or the reranker default. Measure them; do not tune them.

---

# Phase 5 — Generation quality: completeness and hallucination

**Load into context:** `services/evals/evals/metrics/generation.py`,
`services/evals/evals/metrics/groundedness.py`, `services/evals/api/dashboard.py`,
`services/evals/evals/judges/llm_judge.py`, `config.yml` (`eval.scoring.weights`).

**Goal.** Fill the two named gaps: **completeness does not exist**, and the
**hallucination metrics are off by default**.

**Deployment constraint.** Judged metrics over a confidential corpus require the
AWS private deployment — the only in-boundary judge is `qwen38-27b-judge`
(`docs/guide/12-private-aws-demo.md`). The GPU cold-pull is ~50 GB and up to 30
minutes, so **batch this phase's runs into a few long sessions**, not many short
ones. Phases 1–4 and 6 need none of this.

### Build

1. **`answer_completeness`.** `api/dashboard.py:35-39` already reads the name and
   returns `None` because nothing computes it. Build it:
   - `EvalQuestion` gains `answer_nuggets: list[str]` — atomic facts a complete
     answer must contain.
   - Metric = fraction of nuggets entailed by the answer. Judge-based,
     `MetricGroup.GENERATION`.
   - Distinct from `answer_correctness`: an answer can be correct as far as it
     goes and still omit half the required facts.

2. **Nugget derivation is offline and cached.** Derive nuggets from
   `expected_answer` once, store them in the dataset cache
   (`evals/datasets/registry.py` — the cache key is already fingerprinted, extend
   the fingerprint), and never derive at eval time. Deriving per run makes the
   metric non-deterministic and prices a judge call into every question.

3. **Surface hallucination as a headline.** `claim_groundedness`
   (`metrics/groundedness.py`) is the hallucination rate. Add it to
   `DashboardMetrics` (`api/dashboard.py`) alongside faithfulness.

4. **Run the groundedness group by default.** It currently runs only under
   `--groundedness` (`evals/cli.py:116,325`). Change the *execution* default to
   on; **leave `eval.scoring.weights.groundedness` at `0.0`**. Reason: running the
   group adds information; changing its weight changes what the headline rewards
   and makes runs before and after the change incomparable. These are two
   separate decisions and only the first is in scope.

5. **Contextual prefix factuality.** A prefix that invents document context is a
   hallucination injected at ingestion time and inherited by every later answer.
   Judge the prefix against its source document; report
   `contextual_prefix_factuality`. This is the only judged ingestion metric.

### Verify

- A deliberately truncated answer scores high `answer_correctness` and low
  `answer_completeness`. If both move together, the metric is not measuring what
  its name says.
- `just eval-calibrate` is re-run: the calibration on record describes `gpt-5.2`,
  not the Qwen judge. Until it is re-run, label every judged metric
  **uncalibrated on this domain** wherever it is displayed.
- Judged metrics on a confidential corpus with a `third_party` judge are refused
  by the gate. Confirm the refusal fires rather than assuming it.

### Do not

Change scoring weights. Average away judge disagreement — retain the raw
distributions.

---

# Phase 6 — Failure attribution and the experiment store

**Load into context:** `services/evals/evals/runner.py`,
`services/evals/evals/schemas/results.py`, `services/postgres/init.sql`,
`services/evals/evals/stats.py`.

**Goal.** Turn per-stage data into a per-question verdict, and store runs where
they can be queried instead of re-parsed from JSON.

### Build

1. **Dual-field attribution** per question:
   - `primary_failure_stage` — the earliest **causally supported** failure
   - `failure_labels[]` — every supported failure mode

   Stages: `retrieval_miss`, `fusion_miss`, `rerank_drop`, `context_truncated`,
   `generation_drift`, `citation_error`, `wrong_abstention`, `missed_abstention`,
   `correct`.

2. **Never auto-label downstream stages after a prerequisite failure.** If
   retrieval missed the evidence, generation faithfulness is **unassessable**, not
   failed — the same principle as `None`-is-not-`0.0`. Store the stage evidence
   supporting each label. An oracle-context run separately answers whether
   generation *would* have succeeded with the right evidence.

3. **Postgres experiment schema** — `experiments → runs → run_metrics →
   run_questions → question_stages`. Explicit SQL in `init.sql`, query builders in
   the service, no ORM. Runs currently land as JSON under `data/eval_runs`
   (`justfile:105`); dual-write first, migrate readers, then stop writing JSON.

4. **Record the identity of every run**: corpus snapshot id, chunking config,
   embedding model, retrieval settings, reranker, prompts hash, judge model and
   boundary, code version, and **whether judging ran inline or out of band**
   (phase 5 makes this matter — an inline judge shares the GPU with the answer
   model and contaminates latency).

### Verify

A question whose gold evidence was never retrieved reports
`primary_failure_stage: retrieval_miss` and `faithfulness: None` — not
`faithfulness: 0.0`. Query the store for "all runs where the reranker demoted
relevant chunks" and get an answer in SQL, not by re-reading JSON.

---

# Phase 7 — Decision discipline

**Load into context:** `services/evals/evals/stats.py`, `services/evals/evals/cli.py`,
`docs/guide/11-limits-and-caveats.md`.

**Goal.** Make it hard to draw a conclusion the data does not support.

### Build

1. **Frozen corpus snapshot.** A versioned snapshot id recorded on every run.
   Comparisons across different snapshots are refused, not warned about.

2. **~50 hand-authored corroboration questions** against that snapshot, with
   phase-3 evidence locators. Authoring rules, in priority order:
   - **Never author from a chunk.** Author from the source document or a real
     information need. Authoring from a chunk reproduces the query-side leakage
     the set exists to detect.
   - **Do not iterate the question against retrieval.** Rewording until the system
     finds it turns the set into a measurement of the current configuration.
   - Locate evidence *after* authoring.
   - Freeze against the corpus-version id.

   Strata (~50 total): factual/single-hop 15 · multi-hop 10 · table/numeric 8 ·
   unanswerable/adversarial 8 · temporal/summarization/cross-document 9. Also
   stratify across document formats present in the corpus.

   **What n=50 can do:** a direction check. `stats.py` flags comparisons below 100
   paired questions as underpowered. The honest test at this size is
   **non-contradiction** — require that the confidence interval does not exclude
   the direction a larger synthetic run proposed. Requiring independent
   confirmation demands power the set does not have and converts "underpowered"
   into "no effect". **Emit this rule in the comparison output**, not only in the
   docs, or the first reader will over-read a 50-question run.

3. **Pre-run guards** in `compare` and the CLI:
   - **Minimum-detectable-effect calculator** — before the run, given observed
     variance and the planned size, report the smallest change it could detect.
     The existing `underpowered` flag only says so afterwards.
   - **Cost-parity check** — refuse or loudly flag a comparison where one side has
     an unpriced model, because its weight is silently redistributed.
   - **One axis per re-baseline** — when the judge and the answer model both
     change, run the new judge against the *stored answers* from the old baseline
     first (judge-behaviour delta), then switch the answer model (answer-quality
     delta). A single run that moves both produces a number nobody can attribute.

4. **Sweep runner** over `chunk_size`, `top_k`, `rrf_k`, reranker on/off, using
   `POST /search` from phase 1 so retrieval sweeps cost no tokens.

5. **Retire the weighted score as the decision surface.** Replace with component
   gates plus a Pareto view. The operator guide already says this
   (`docs/guide/11-limits-and-caveats.md:124` — *"Do not present the weighted
   score as overall quality"*); make the tooling agree with the documentation.

---

## Non-goals

- A laptop-to-AWS network path of any kind.
- A local LLM on the laptop.
- Switching serving stacks, embedding models, or the reranker.
- Changing retrieval settings, chunking defaults, or scoring weights as part of
  any measurement phase.
- Adopting an external eval platform as system of record.
- Human judge calibration by annotation — deferred, tracked in `docs/ROADMAP.md`.
  Until it happens, judged metrics carry the **uncalibrated on this domain**
  label and may not be cited as absolute quality.
