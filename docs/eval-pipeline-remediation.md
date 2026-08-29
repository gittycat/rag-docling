# Plan: remediate the per-stage eval pipeline

**Status.** `docs/eval-pipeline-plan.md` phases 1–6 were implemented across commits
`ed84648..eef6b63`. Both unit suites pass (evals 413, rag_server 198). A review of
that work found defects that make phases 3, 4 and 6 non-functional end to end.
This plan fixes them. Phase 7 of the original plan remains unstarted and is out of
scope here.

**Audience.** An orchestrating agent starting from a clean context, delegating
implementation to subagents.

**The one thing to internalise before touching anything.** The existing tests pass
*with every defect below present*. They are synthetic: they construct chunk ids
that match gold ids exactly, locators that are already well-formed, and stage
traces built by hand. Green tests are not evidence here. **Every fix in this plan
lands with a regression test that fails on the current tree and passes after.**
Write the failing test first and paste its failure output into your report.

---

## Delegation model

You are running on an expensive model. Your job is sequencing, the two design
decisions called out below, cross-track conflict resolution, and final review.
Everything else is delegated.

- **Spawn one subagent per track**, `subagent_type: "general-purpose"`,
  `model: "sonnet"`. Give it the track's section verbatim plus the Invariants
  section. Tracks in the same wave run in parallel.
- **Do not spawn a subagent for a one-line fix.** Trivial items are already folded
  into a neighbouring track. Do not split them out.
- **Read the diff yourself** before accepting a track. A subagent reporting
  "tests pass" is not acceptance — the whole point of this plan is that passing
  tests were consistent with broken metrics.
- **You make these two calls, not a subagent:** the ground-truth resolution
  design in Track A step 1, and the source-fidelity decision in Track F step 1.
  Decide them up front and pass the decision into the track.

### Waves

| Wave | Tracks | Why |
|---|---|---|
| 1 | **A**, **B**, **C**, **D** | Independent file sets, no overlap |
| 2 | **E**, **F** | Both need A's chunk-id namespace to be settled |
| 3 | **G** | Needs A and F to produce trustworthy numbers to diff |

### File ownership — do not cross these lines in wave 1

| Track | Owns |
|---|---|
| A | `services/evals/evals/metrics/retrieval.py`, `services/rag_server/api/routes/documents.py`, the metric-kwargs block of `runner.py` (~line 1062-1066) |
| B | `services/evals/evals/evidence.py`, `services/evals/evals/schemas/dataset.py` |
| C | `services/evals/evals/attribution.py`, `services/evals/evals/experiment_store.py`, the `failures` command in `cli.py` |
| D | `services/rag_server/pipelines/inference.py`, `.../infrastructure/tasks/worker.py`, `.../pipelines/ingestion.py`, `.../infrastructure/database/documents.py` |

Track E later edits the cost block of `runner.py` (~line 1187-1200); Track A must
land first so the two hunks do not collide.

---

## Invariants — pass these to every subagent

Inherited from `docs/eval-pipeline-plan.md`; they still bind.

1. **`None` is not `0.0`** — and the converse now matters more: `0.0` is not
   `None`. A metric with no data returns `MetricResult(value=None)`. A metric that
   is defined and evaluates to zero returns `0.0`. Conflating the two in either
   direction is the root cause of Track A.
2. **Judge-free stays judge-free.** Nothing in tracks A–D may add an LLM call.
3. **Do not change pipeline behaviour.** No fix here changes retrieval defaults,
   `rrf_k`, `top_k`, chunking defaults, scoring weights, prompts or the embedding
   model. `_fuse_results` stays behaviourally identical. These are measurement
   fixes. If a fix requires a behaviour change, stop and report instead.
4. **Every new or renamed metric registers** in `METRIC_GROUPS`
   (`services/evals/evals/metrics/__init__.py:52`) and declares `requires_judge`
   and `requires_gold`.
5. **House style** (`CLAUDE.md`): module-level functions over classes; query
   builders or explicit SQL, no ORM; SQL-schema migrations; `uv` for Python; no
   docstrings on private helpers.
6. **Schema changes require `docker compose down -v`.** `services/postgres/init.sql`
   runs only on a volume's first boot. Batch all schema work — Track C and Track D
   both touch it; land them in one pass.
7. **Privacy gate is load-bearing.** Do not add a bypass to
   `enforce_judge_boundary()`.

---

## Reproductions

Run these from `services/evals` with `uv run python` (place the script inside the
package root; `evals` is not importable from elsewhere). They are the acceptance
evidence for tracks A and B. **Sandbox note:** these need network/CA access —
if you see `PermissionError: [Errno 1] Operation not permitted` out of
`ssl.create_default_context`, that is the sandbox, not the code; re-run with the
sandbox disabled.

**R1 — legacy `chunk_id` path halves a perfect retrieval.**

```python
from evals.metrics.retrieval import RecallAtK
from evals.schemas import EvalQuestion, EvalResponse, RetrievedChunk
from evals.schemas.dataset import GoldPassage

text = "The capital of Freedonia is Sylvania City, founded in 1873 by settlers."
q = EvalQuestion(id="q1", question="capital?", expected_answer="Sylvania City",
    gold_passages=[GoldPassage(doc_id="ragbench:abc", chunk_id="ragbench:abc:chunk:0",
                               text=text, relevance_score=1.0)])
r = EvalResponse(question_id="q1", answer="", retrieved_chunks=[
    RetrievedChunk(doc_id="uuid-1", chunk_id="uuid-1-chunk-0", text=text, rank=1)])
print(RecallAtK(5).compute(q, r))
```

Current: `value=0.5`, `details={'hits': 1, 'gold_count': 2, ...}`. One gold
passage, retrieved perfectly, counted as two. Target: `1.0`.

**R2 — evidence path reports a total miss as undefined.** Build a question with an
`EvidenceLocator` at `start_char 500-620` and retrieved chunks covering `0-100`
and `1000-1100` (see `services/evals/tests/test_evidence.py:13` for the
constructors). Current: `recall_at_5 = None`, note `"No resolvable relevant
chunks"`. Target: `0.0`.

**R3 — `evidence_containment` false-positives on PDF.**

```python
from evals.metrics.retrieval import _wholly_contained
# evidence: page 1, bbox [20,20,30,30]; chunk: page 99, bbox [900,900,910,910]
# both locators lack element_id
```
Current: `True`. Target: `False`.

**R4 — the failure query crashes.**

```python
import asyncio
from evals.experiment_store import ExperimentStore
asyncio.run(ExperimentStore("postgresql://u:p@127.0.0.1:1/db")
            .questions_with_failure_label("rerank_drop", 5))
```
Current: `NameError: name 'FAILURE_STAGES' is not defined`. Target: a connection
attempt.

---

# Track A — retrieval ground truth and the chunk-id namespace

**Blocking. Nothing else in the eval stack means anything until this is right.**

**Load into context:** `services/evals/evals/metrics/retrieval.py`,
`services/evals/evals/metrics/text_match.py`,
`services/evals/evals/runner.py:1057-1070`,
`services/rag_server/api/routes/documents.py:86-110`,
`services/rag_server/infrastructure/search/bm25_retriever.py:175-185`.

### The defect

`_relevance()` (`metrics/retrieval.py:48`) builds ir-measures qrels — the
relevant-set denominator — from the wrong source, differently on each of its two
paths.

**Evidence path.** `derive_relevant_chunk_ids(question.evidence, chunks)` resolves
gold coordinates against *the ranking being scored*. "Relevant" therefore means
"relevant and already retrieved". A question retrieval missed entirely produces
zero qrels and returns `None` — dropped from the average rather than scored `0.0`
(R2). Consequences, all confirmed by running them:

- `recall_at_k`, `ndcg_at_10`, `mrr` are averaged only over questions retrieval
  already got right. Systematically inflated.
- `candidate_recall_ceiling` returns `None` on a miss, so it **cannot fall when
  the embedder degrades** — the fault-localization acceptance test in the original
  plan's phase 4 cannot pass.
- `fusion_lift` normalises each leg against its own denominator. A case where
  bm25 finds evidence A, vector finds evidence B and fusion finds both scores
  `fusion_lift: 0.0` with `fusion_ndcg_at_10: 1.0, best_leg_ndcg_at_10: 1.0`.

**Legacy `chunk_id` path.** qrels get the gold `chunk_id` *and* separately the ids
of text-matched retrieved chunks (`retrieval.py:61-79`). Three chunk-id namespaces
are in play and none of them agree:

| Source | Shape | Where |
|---|---|---|
| Gold passages | `{content_doc_id}:chunk:{n}` | `datasets/ragbench.py:282` |
| Retrieved nodes / stage items | `{document_id}-chunk-{chunk_index}` | `bm25_retriever.py:181`, vector equivalent |
| Catalog endpoint | `str(chunk.id)` — the DB row UUID | `api/routes/documents.py:102` |

So the stale gold id never matches, stays in the denominator, and a perfect
single-passage retrieval scores `0.5` (R1). Every headline retrieval number in
every run to date is roughly halved.

**And the per-leg metrics cannot even reach the text fallback.** `_stage_chunks()`
(`retrieval.py:28`) materialises stage items with `text=""`, and
`match_retrieved_to_gold` matches on text (`metrics/text_match.py:40`). Per-leg
recall on the legacy path is structurally near-zero.

### Build

1. **Decide the resolution model (orchestrator decides, not the subagent).**
   The relevant-set must be resolved against the full current chunk catalog, not
   against the ranking being scored. The runner already collects one
   (`runner.py:937-957`) and passes it only to the chunking metrics
   (`runner.py:1066`). Extend that to the ranking and attribution metrics. Decide
   and record: what happens when the catalog is absent (a generation-tier run, or
   a `/documents/{id}/chunks` failure)? Recommended: `None` with an explicit
   `"chunk catalog unavailable"` note — that is a genuine unassessable, distinct
   from a miss. Do not silently fall back to the old behaviour.

2. **Unify the chunk-id namespace.** Make `GET /documents/{id}/chunks` emit the
   retriever's id (`f"{document_id}-chunk-{chunk_index}"`) as `chunk_id`, keeping
   the row UUID as a separate field if anything needs it. Catalog and stage lists
   must be joinable. Do not change the retrievers' node ids — that would change
   pipeline behaviour (invariant 3).

3. **Rewrite `_relevance()` to take the catalog.** Evidence path: resolve gold
   locators against the catalog, so a total miss yields a non-empty qrels set and
   a `0.0` score. Reserve `None` strictly for `lineage_failure` and for an absent
   catalog.

4. **Fix the legacy path's denominator.** A gold `chunk_id` that resolves to
   nothing in the current catalog is *not* a relevant document — it is a stale
   anchor. Resolve gold passages to current chunk ids once, against the catalog,
   by text match; put only resolved ids in qrels. Where a gold passage resolves to
   nothing, that is a lineage failure for that passage — record it, do not leave a
   phantom id inflating the denominator. Keep `ground_truth: chunk_id` labelling
   intact.

5. **Give stage items usable text, or stop pretending they can be text-matched.**
   Either populate `text` on `_stage_chunks` from the catalog join (preferred, now
   that ids are unified) or make the legacy path return an explicit
   `"per-leg metrics require source-coordinate evidence"` undefined result rather
   than a silent near-zero.

6. **Fold in `CandidateRecallCeiling`'s `k`** (`retrieval.py:279-281`): it defaults
   to `k=5` while the shipped candidate list is `top_k: 10` (`config.yml:305`).
   Evidence at candidate ranks 6–10 is reported as outside a ceiling it is inside.
   The ceiling must measure the whole pre-rerank candidate list.

7. **Broaden the ir-measures parity fixture.** The only parity assertion is one
   hand-computed binary nDCG case (`tests/test_stage_retrieval_metrics.py:167`).
   Add recall, precision and MRR cases, and one graded-relevance case.

### Verify

- R1 returns `1.0`; R2 returns `0.0`; both as new regression tests.
- A fixture where fusion recovers strictly more evidence than either leg produces
  `fusion_lift > 0`.
- A fixture where the pre-rerank list holds the evidence at rank 8 and `top_k=10`
  produces `candidate_recall_ceiling` counting it.
- Per-leg `recall_at_5{leg=bm25}` is non-zero on a fixture where bm25 found the
  evidence.

### Do not

Change the retrievers' node id scheme. Change `rrf_k`, `top_k`, or the reranker
default. Reintroduce a Jaccard fallback on the evidence path.

---

# Track B — the evidence resolver

**Load into context:** `services/evals/evals/evidence.py`,
`services/evals/evals/schemas/dataset.py`, `services/evals/tests/test_evidence.py`.

### The defects

1. **PDF and spreadsheet containment false-positives.** `_wholly_contained`
   (`metrics/retrieval.py:355` — read it, but the fix belongs with the resolver
   semantics; coordinate the final edit with Track A, which owns that file) has a
   text-format branch and then falls through to
   `locator.get("element_id") == evidence.locator.get("element_id")` for every
   other format. For PDF bbox locators neither side has an `element_id`, so
   `None == None` and **any chunk from the same document is reported as containing
   the evidence** (R3). `evidence_containment` on a PDF corpus is ~1.0 by
   construction.

2. **XLSX range locators pass validation and then compare as equal.**
   `_locator_is_usable` (`evidence.py:45`) accepts a locator with `sheet` plus
   `range`, but `_locators_overlap` (`evidence.py:68`) compares only `row` and
   `col`. Two range locators, neither having `row`/`col`, satisfy
   `all(evidence.get(k) == chunk.get(k) for k in ("row", "col"))` as `None == None`
   and match. Same failure shape as (1).

3. **`normalized_text` / `normalized_text_hash` are stored and never used.** The
   original plan specified them as the *secondary check* on coordinate
   resolution. `EvidenceLocator` validates only that its own hash matches its own
   text (`schemas/dataset.py:40`); `derive_relevant_chunk_ids` (`evidence.py:104`)
   compares document hash, format and coordinates and never compares text. A
   coordinate that silently drifts — a re-parse that shifts offsets — resolves to
   the wrong chunk with no signal.

### Build

1. Make every non-text format require a *positive* coordinate assertion. `None`
   on both sides is a lineage failure, never a match. Apply this to
   `_locators_overlap`, `_locator_is_usable` and the containment check
   consistently — an unresolvable coordinate is an unassessable question, which is
   exactly what `lineage_failure` exists to report.
2. Implement XLSX `range` overlap properly, or reject `range`-only locators as
   unusable until it is implemented. Do not leave the accepting-but-not-comparing
   state.
3. Wire `normalized_text_hash` in as the secondary check: when a chunk's lineage
   carries a normalized text hash, a coordinate match whose text hash disagrees is
   a `lineage_failure`, not a match. Put the reason in a comment so nobody
   "simplifies" it away.

### Verify

- R3 returns `False`.
- A PDF fixture: evidence on page 1, chunks on pages 1 and 7 — only the page-1
  chunk resolves, and `evidence_containment` is not 1.0.
- An XLSX fixture with two different `range` locators does not cross-match.
- A fixture where coordinates match but `normalized_text_hash` differs yields
  `lineage_failure`, not a hit.

---

# Track C — phase 6: the store and the verdict

**Load into context:** `services/evals/evals/attribution.py`,
`services/evals/evals/experiment_store.py`,
`services/evals/evals/cli.py` (`cmd_failures`), `services/postgres/init.sql:121-205`.

### The defects

1. **`evals failures <label>` crashes before connecting.**
   `questions_with_failure_label` (`experiment_store.py:269`) references
   `FAILURE_STAGES`; the module imports only `FailureAttribution`
   (`experiment_store.py:13`). R4 reproduces it. The original plan's phase-6
   acceptance test — *"query the store for all runs where the reranker demoted
   relevant chunks and get an answer in SQL"* — has never run.

2. **`failure_labels[]` never holds more than one label.** Every supported branch
   returns immediately (`attribution.py:190`, `:204`, `:218`, `:233`, `:245`,
   `:260`, `:274`). The plan's dual-field design — `primary_failure_stage` *plus every*
   supported mode — is a single field in practice, and the `failure_labels TEXT[]`
   column with its GIN index can never hold a second element.

3. **A vector-only deployment can never report `retrieval_miss`.**
   `retrieval_assessable = bm25 is not None and vector is not None`
   (`attribution.py:177`). With hybrid search off there is no bm25 trace, so the
   miss branch is unreachable. Downstream branches are still reachable for
   questions that *succeeded*, so the effect is silent: misses vanish, successes
   are attributed.

4. **`generation_drift` uses an exact threshold and ignores every other
   generation signal.** `correctness < 1.0` is drift and only exactly `1.0` is
   `correct` (`attribution.py:249`). Faithfulness, completeness, relevancy and
   claim groundedness are not consulted, so an answer scoring correctness `1.0`
   and faithfulness `0.0` is labelled `correct`.

5. **`corpus_snapshot_id` does not hash the corpus.** It hashes question ids, gold
   doc/chunk ids and locator metadata (`experiment_store.py:38-66`) but omits gold
   passage text and all distractor/context passage content. The corpus can change
   without the snapshot id changing — which defeats the identity guarantee the
   whole store exists to provide, and pre-breaks phase 7's "comparisons across
   snapshots are refused".

6. **`context_truncated` is unobservable.** The rerank trace records the same
   postprocessed node list later exposed as response sources
   (`inference.py:658`, `:1131`), and attribution compares those same ids
   (`attribution.py:220`). Nothing between the reranker and the prompt is
   measured, so the label can only ever fire on an empty source list.

### Build

1. Import `FAILURE_STAGES` from `evals.attribution`. Add a test that calls
   `questions_with_failure_label` for each label and asserts the validation
   passes without a `NameError` — a unit test, no database needed.
2. Collect every supported label instead of returning at the first. Keep
   `primary_failure_stage` as the earliest causally supported one; keep the rule
   that a downstream stage after a prerequisite failure is **unassessable, not
   failed**. The distinction to preserve: a stage that is genuinely assessable and
   genuinely failed belongs in `failure_labels` even when it is not primary.
3. Make retrieval assessability adaptive: assess against whichever legs actually
   emitted traces. A vector-only run with a vector trace and no hit is a
   `retrieval_miss`. Report which legs the verdict rested on in the evidence.
4. Replace the `== 1.0` threshold with an explicit, configurable correctness
   threshold, and consult faithfulness/groundedness before emitting `correct`.
   Record which metric supported the verdict.
5. Fold the corpus content into `corpus_snapshot_id` — gold passage text and
   context/distractor text. If the corpus is uploaded from synthesized documents
   (it currently is, `runner.py:884`), hash exactly the bytes uploaded.
6. For `context_truncated`: either measure the context actually packed into the
   prompt (a `context_assembly` stage item list distinct from the rerank output,
   which Track D is already inside) or **remove the label** and say so in the
   evidence. A label that cannot fire is worse than an absent one. Coordinate with
   Track D before choosing.

### Verify

- R4 reaches a connection attempt.
- A fixture question with two genuinely assessable failures returns both in
  `failure_labels` and the earlier one as `primary_failure_stage`.
- A vector-only fixture (vector trace present, bm25 absent, no hit) returns
  `retrieval_miss`.
- Correctness `1.0` with faithfulness `0.0` is not labelled `correct`.

---

# Track D — observability, concurrency and ingestion failure

**Load into context:** `services/rag_server/pipelines/inference.py`,
`services/rag_server/infrastructure/tasks/worker.py:95-155`,
`services/rag_server/pipelines/ingestion.py:470-560`,
`services/rag_server/infrastructure/database/documents.py:167-245`,
`services/rag_server/infrastructure/search/{bm25,vector}_retriever.py`.

### The defects

1. **Stage durations do not nest, and nothing asserts the bound.** The original
   plan's phase-1 verify step — *"sum of stage `duration_ms` ≤ total `latency_ms`;
   assert the bound"* — was never implemented and does not hold. Two causes:
   the trace named `context_assembly` wraps `_arun_c3`, and the installed
   `CondensePlusContextChatEngine._arun_c3` calls `_aget_nodes()` internally
   (`.venv/.../llama_index/core/chat_engine/condense_plus_context.py:305`), so
   retrieval and reranking are inside it *and* emitted separately; and the bm25
   and vector legs run concurrently, so their durations overlap wall time. Note
   the `generation` figure is *not* affected — subtracting
   `_last_context_assembly_ms` already removes retrieval and rerank from it.

2. **Failed ingestion stages are never persisted.** Stage records live inside
   `ingest_document()` and reach the worker only via its return value
   (`worker.py:102-116`); a parse, chunk or embed exception loses the whole trace
   including the `status="failed"` records the chunkers carefully wrote. The index
   handler is worse: it appends a failed stage and immediately `raise`s without
   saving (`worker.py:145-155`). The original plan's phase-2 verify — *"kill the
   LLM mid-ingest; the document is flagged, not silently accepted"* — holds only
   for contextual-enrichment failures, which do not raise.

3. **Retriever health is process-global.** `_last_error`
   (`vector_retriever.py:21`, bm25 equivalent) is module state read after
   retrieval (`hybrid_retriever.py:116`). Under the evaluator's
   `query_concurrency: 10`, one query's failure marks another query's trace
   `degraded`, and one query's success clears another's error before it is read.

4. **Token accounting is process-global too, and it feeds cost.**
   `reset_token_counter()` / `get_token_counts()` (`inference.py:82`, `:88`) are
   module-global and reset at the start of every query, while the runner issues
   ten concurrently (`runner.py:652`). Per-query token counts — and therefore
   `cost_per_query` — are cross-contaminated.

5. **Raw unmasked chunk text is duplicated into JSONB.** `source_text = node.text`
   (`ingestion.py:479`, `:529`) is stored for every successfully enriched chunk
   into `document_ingestion_stages.details` (`database/documents.py:197`). The
   corpus is stored twice, in an unindexed JSONB blob, unmasked even when PII
   masking is enabled elsewhere in the same function.

6. **`get_ingestion_stages` claims pipeline order and does not have it.**
   `ORDER BY created_at, id` (`database/documents.py:224`) — all rows in one
   transaction share `NOW()`, and the tiebreak is `gen_random_uuid()`.

### Build

1. Emit a stage-nesting contract. Either make `context_assembly` exclusive of
   retrieval and rerank (subtract them, as `generation` already does), or rename
   it to something honest and record `parallel: true` on the legs. Then **write
   the bound assertion the original plan asked for** — as a test over a recorded
   trace set, not a comment.
2. Persist ingestion stages on the failure path: wrap `ingest_document()` so the
   stage list is reachable from the exception handler, and save before re-raising.
   The failed stage row is the entire point of the table.
3. Scope health and token accounting per-query. A `contextvars.ContextVar` is the
   minimal fix for both and does not change pipeline behaviour. Keep the global
   health surface for `/metrics/system` and `just demo-check` — that consumer
   genuinely wants process-wide state; the *trace* must not read it.
4. Stop storing `source_text` in the stage details. `ContextualPrefixFactuality`
   needs the source to judge a prefix against — join it from `document_chunks` at
   metric time instead, now that Track A has unified chunk ids. If a join is
   genuinely impractical, store the chunk id and nothing else.
5. Add an explicit ordering column (`stage_index INTEGER`) to
   `document_ingestion_stages` and order by it. Coordinate with Track C: both
   touch `init.sql` and the volume can only be reset once.

### Verify

- A recorded trace set satisfies `sum(stage durations) <= latency_ms`, asserted in
  a test.
- An ingestion that raises during chunking leaves a `status: failed` chunk row in
  `document_ingestion_stages`.
- Two concurrent queries, one against a failing embedder, produce one `degraded`
  trace and one `ok` trace — not two of either.
- Token counts for two concurrent queries with different prompt sizes do not
  cross-contaminate.

---

# Track E — cost accounting

*Wave 2. Needs Track A's `runner.py` edits landed first.*

**Load into context:** `services/evals/evals/metrics/performance.py:194-430`,
`services/evals/evals/runner.py:1126-1205`, `services/evals/evals/pricing.py`.

### The defects

1. **Significance testing runs against a different quantity from the reported
   value.** `details["per_question"]` holds generation cost only
   (`performance.py:329`), while the aggregate `value` additionally includes judge
   and ingestion cost (`performance.py:374-385`). `compare` bootstraps the
   per-question series, so a paired significance result on `cost_per_query` does
   not describe the point estimate printed beside it.

2. **`cost_per_query` moves with `--samples`.** Whole-corpus ingestion cost is
   divided by question count (`runner.py:1197-1200`, `performance.py:378`). This
   is deliberate and documented in a comment, but it makes the metric
   non-comparable across runs with different sample counts, and non-comparable to
   every run recorded before the change.

### Build

1. Make `per_question` and `value` describe the same quantity. Either attribute
   judge and amortised ingestion cost per question into the series, or report the
   composed figure under a distinct name and keep `cost_per_query` as the
   per-question generation+judge cost it used to be. State which you chose in the
   metric's `details`.
2. Record the ingestion component and the query denominator explicitly in
   `details` so a reader can renormalise, and add a note when the denominator
   makes a run non-comparable to another sample size.
3. Leave the "unpriced is not free" machinery alone — it is correct.

### Verify

- Bootstrapping `details["per_question"]` reproduces `value` on a fixture.
- Two runs at `--samples 5` and `--samples 50` over the same corpus produce cost
  figures a reader can reconcile, or a note saying they cannot be compared.

---

# Track F — make phase 3 reachable

*Wave 2. Needs Tracks A and B.*

**Load into context:** `services/evals/evals/datasets/registry.py:152-195`,
`services/evals/evals/datasets/golden.py`, `services/evals/evals/runner.py:860-960`,
`services/evals/evals/schemas/dataset.py`.

### The defect

**No dataset loader constructs an `EvidenceLocator`.** `grep -rn "EvidenceLocator("`
across `services/evals/evals` returns exactly two sites: the cache round-trip
(`registry.py:165`) and sample deserialization (`samples.py:181`). Both only
rehydrate what something else wrote, and nothing writes. The user-authored golden
loader emits `gold_passages` only.

**And the runner could not consume one if it existed.** It uploads synthetic
`.txt` documents assembled from gold and distractor passage *text*
(`runner.py:884`), not the source PDF/DOCX the locator's `document_hash` and
`source_format` refer to. A locator anchored to an original file cannot match a
freshly synthesized text document; a locator-only question would ingest nothing.

The consequence: the entire source-coordinate ground-truth path — the reason
phase 3 exists, and the prerequisite for interpretable chunk-size sweeps — is
dead code. The rechunk test that appears to validate it
(`tests/test_evidence.py:37`) exercises the resolver's arithmetic on synthetic
locators, not a real ingestion.

### Build

1. **Decide the source-fidelity model (orchestrator decides).** Two options,
   pick one and record why:
   - **Ingest real source files.** The golden dataset references actual documents
     in the corpus; the runner uploads those bytes; locators anchor to their real
     hash and format. Highest fidelity, and the only version that makes a PDF or
     spreadsheet sweep interpretable. Requires a corpus directory contract.
   - **Anchor locators to the synthesized document.** Cheaper, keeps the current
     upload path, but only ever exercises the `txt` locator branch — Track B's
     PDF and XLSX work would then have no real consumer.

   The first is what the original plan intended ("a chunk-size sweep is runnable
   today — and uninterpretable"). Take it unless something concrete blocks it.

2. Give the golden loader a way to carry locators — authored alongside the
   question, per the original plan's phase-7 authoring rules (author from the
   source document, never from a chunk; locate evidence *after* authoring).
3. Thread `evidence` through the upload path so a locator-bearing question causes
   its source document to be ingested and its `document_hash` to match what
   `documents.file_hash` records.
4. Keep the `ground_truth: chunk_id` / `source_coordinate` run labelling intact —
   the two must never be silently mixed in one scorecard.
5. Extend the dataset cache fingerprint to cover the locator payload.

### Verify

**This is the original plan's phase-3 acceptance test, run for real for the first
time.** Ingest one fixture document at `chunk_size: 500`, then re-ingest at
`chunk_size: 1000`, through the actual ingestion path. The same unmodified gold
question resolves to the chunk set containing the evidence in both runs, and
`recall_at_5` is `1.0` in both. Do it for a `txt` fixture *and* a PDF fixture — the
PDF path is the one Track B just repaired and it has never been exercised
end to end.

Also: a document ingested without lineage produces `lineage_failure` and `None`
metrics, never a fuzzy-matched number.

---

# Track G — phase 4's missing delta protocols

*Wave 3.*

**Load into context:** `services/evals/evals/config.py:340-360`,
`services/evals/evals/cli.py`, `services/evals/evals/runner.py`.

### The defect

The original plan's phase 4 step 5 required A/B delta protocols as runner modes.
Only half shipped: `--retrieval-only` with `--retrieval-source
{bm25,vector,fusion,rerank}` covers the per-source attribution half
(`config.py:345-350`). There is no contextual-retrieval on/off paired runner and
no automatic delta computation, so phase 4 is incomplete independently of the
qrels defect.

### Build

1. A paired runner mode: one question set, one corpus, contextual retrieval on
   and off, emitting Δ retrieval metrics **and** Δ ingestion cost and wall-clock
   per document (phase 2's `IngestionCostPerDocument` /
   `IngestionLatencyPerDocument` supply the second half).
2. Route retrieval sweeps through `POST /search` so they cost no tokens.
3. Reuse the existing `compare` significance path rather than inventing a second
   one.

### Verify

The fault-localization test the original plan named as phase 4's real acceptance
criterion, which cannot pass today:

> Configure a deliberately bad reranker; `rerank_demotions` must rise while
> `candidate_recall_ceiling` stays flat. Then degrade the embedder; the ceiling
> must drop while rerank behaviour holds. If both faults move the same metrics,
> the attribution does not work yet.

Run it. It is the only end-to-end proof that tracks A, B and F actually landed.

---

## Reporting

For each track, report: the failing test written first with its output, the diff,
the verification evidence, and anything found that this plan does not describe.
A track that cannot complete reports what it left and why — do not narrow scope
silently.

Do not close this plan on green tests. Close it on Track G's fault-localization
run.
