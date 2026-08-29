# Suggestions

An actionable backlog assembled while rewriting the documentation. Everything here
was found by reading code and configuration, not by running the system.

Items are grouped by area, dashboard first. Each entry gives **what**, **why it
matters**, rough **effort**, and **where it lives**.

Effort is a rough sizing: **S** = hours, **M** = a day or two, **L** = larger than
that.

Nothing here is a documentation task. These are changes to the product.

Every actionable entry carries a **Status** line: `Open`, `Partially done`, or
`✅ Done` with the date and commit. Statuses were last reconciled against the code
on **2026-08-26** (judge resolution and the execution-boundary privacy model —
§4.11; before that **2026-08-21** for the pgvector migration, and section 4 on
2026-08-03).

---

## 1. Dashboard and web app

The dashboard reads a small fraction of what the backends already return. Roughly
35 distinct fields or endpoints are exposed by the eval and metrics APIs and never
rendered. The high-value ones are below.

### 1.1 No way to start or cancel an evaluation from the UI
**What.** The eval API supports `POST /eval/runs` to start a run and
`DELETE /eval/runs/active` to cancel one. No UI calls either. The Experiments tab's
empty state tells the user to go and use `curl` or the CLI.
**Why it matters.** This is the single largest gap between what the product can do
and what a user can reach. The dashboard is positioned as the place you evaluate
configurations, and it cannot evaluate anything. Every tuning cycle requires
dropping to a terminal.
**Effort.** M — the API exists; this is a form, a progress poll against
`GET /eval/runs/active`, and a cancel button.
**Where.** `services/webapp/src/lib/components/analytics/ExperimentsTab.svelte`,
`services/evals/api/routes.py`.
**Status.** ✅ Done (2026-08-02). `RunEvalPanel.svelte` in the Experiments tab: trigger form (name, tier, datasets, samples, seed, judge), live progress poll against `GET /eval/runs/active`, and a cancel button. Smoke-testing the trigger surfaced a backend defect, fixed in the same pass: `JobManager.trigger` claimed the single active-job slot *before* validating datasets and tier, so a rejected request (422) left the service permanently believing a job was queued and every later trigger returned 409 until someone called `DELETE /eval/runs/active`. Validation now happens before the slot is claimed, and a failure to start the thread releases it.

### 1.2 Weighted score is shown without its breakdown
**What.** The API returns `weighted_score` with `weights`, `contributions`, and
`objectives` — the full explanation of how the headline number was reached. The UI
reads only `.score`.
**Why it matters.** The weighted score combines six objectives with fixed weights
that suit some deployments and not others. Showing the number without the
contributions makes an opinionated aggregate look like a measurement, and gives the
user no way to see that, say, latency contributed almost nothing.
**Effort.** S — the data is already in the response.
**Where.** `services/webapp/src/lib/components/analytics/`.
**Status.** ✅ Done (2026-08-02). `WeightedScoreBreakdown.svelte` renders weights, effective share after redistribution, per-objective score, contribution, and share of the total, plus the objectives that had no data.

### 1.3 Standard deviation is dropped for most metric groups
**What.** `MetricResult.details.std_dev` is computed for every metric. The UI
renders it only for the `generation` group; retrieval, citation, and abstention
silently discard it.
**Why it matters.** Variance is exactly what a user needs to judge whether a
difference is meaningful, and the system currently computes it and throws it away
in three of four groups. Combined with 1.4 and section 2, this is why the tuning
workflow has to be done by hand.
**Effort.** S.
**Where.** `services/webapp/src/lib/components/analytics/MetricBreakdown.svelte`.
**Status.** ✅ Done (2026-08-02). `MetricBreakdown` shows `std_dev` (and sample size) for every group.

### 1.4 Per-sample distributions are never surfaced
**What.** `details.individual_scores` carries per-question scores. Nothing displays
them.
**Why it matters.** An average of 0.7 from every question scoring 0.7 and an average
of 0.7 from half scoring 1.0 and half scoring 0.4 are different systems needing
different fixes. A distribution view would make that visible immediately.
**Effort.** M.
**Where.** As above.
**Status.** ✅ Done (2026-08-02). `ScoreDistribution.svelte` — per-metric histogram plus min/p25/median/p75/max, expandable from each metric row.

### 1.5 Config diff ignores all but two selected runs
**What.** The comparison UI lets a user select up to four runs; `ConfigDiff` only
ever compares baseline-A against run-B.
**Why it matters.** Silently ignoring selected input is worse than not offering it —
the user believes they are comparing four runs.
**Effort.** S to disable the extra selection, M to support n-way diffing.
**Where.** `services/webapp/src/lib/components/ConfigDiff.svelte`.
**Status.** ✅ Done (2026-08-02). `diffConfigs` is now n-way and `ConfigDiff` renders one column per selected run, baseline first, marking cells that differ from the baseline.

> **Note:** the snapshot defect behind this (**2.1**) is fixed, so the diff now
> reflects real values. Settings the runner never captured render as `Unknown` and
> are never reported as a change.

### 1.6 Endpoints the webapp never calls
**What.** `/models/info` (per-model cost rates) and `/config` (max upload size) are
implemented and unused.
**Why it matters.** Cost-per-token rates would let the dashboard show cost context
alongside results. The upload-size limit is currently a number the user discovers
by exceeding it.
**Effort.** S each.
**Where.** `services/webapp/src/lib/api/`.
**Status.** ✅ Done (2026-08-02). `/models/info` cost rates show in the "Config under test" panel (only when the run's LLM matches the current one); `/config` max upload size is shown on the upload page and enforced client-side.

### 1.7 Chat citations show a filename and nothing else
**What.** Each source carries `score`, `full_text`, and `path`. The chat UI renders
a filename badge only.
**Why it matters.** Verifying a grounded answer means reading the passage it came
from. Users currently have to trust the citation or go and find the document
themselves — which undercuts the product's central claim.
**Effort.** M — an expandable source panel with the retrieval score.
**Where.** `services/webapp/src/routes/chat/`.
**Status.** ✅ Done (2026-08-02). Sources are an expandable list with retrieval score, path, and the full retrieved passage; dedupe is by passage rather than document, so distinct chunks are no longer dropped.

### 1.8 Settings load failures are invisible
**What.** A failed settings fetch is caught and passed to `console.error`. No error
state renders.
**Why it matters.** The page appears to work and shows stale or empty values. Silent
failure in a settings screen leads directly to users believing they changed
something they did not.
**Effort.** S.
**Where.** `services/webapp/src/routes/settings/`.
**Status.** ✅ Done (2026-08-02). Load and update failures render an error with a retry; the toggle reverts and says the change was not saved.

### 1.9 Documents table caps at 15 rows client-side
**What.** The full document list is fetched and then truncated to 15 rows in the
browser. There is no pagination.
**Why it matters.** Documents beyond the first 15 are unreachable in the UI, and the
fetch cost grows with the corpus while the display does not.
**Effort.** M for real server-side pagination, S for client-side paging over the
fetched list.
**Where.** `services/webapp/src/routes/documents/`.
**Status.** ✅ Done (2026-08-02). Client-side paging over the fetched list (15/25/50/100 rows). Server-side pagination remains unimplemented — the API still returns the whole list.

### 1.10 Bulk delete has no partial-failure handling
**What.** Deleting several documents at once does not report which deletions
succeeded when some fail.
**Why it matters.** The user is left without an accurate picture of system state
after a partial failure.
**Effort.** S.
**Where.** `services/webapp/src/routes/documents/`.
**Status.** ✅ Done (2026-08-02). `Promise.allSettled`: failures stay selected and are named individually, with a count of what succeeded.

### 1.11 Upload progress is simulated before task IDs exist
**What.** Progress is animated with a timer until real task IDs arrive, then
switches to real polling.
**Why it matters.** Fabricated progress is actively misleading during the phase
where an upload is most likely to fail. A stalled upload shows a healthy bar.
**Effort.** S — an indeterminate state until real progress is available.
**Where.** `services/webapp/src/routes/upload/`.
**Status.** ✅ Done (2026-08-02). The simulated timer is gone. Hashing and uploading render an indeterminate bar; a determinate bar appears only once the server reports chunk counts.

### 1.12 Status is conveyed by colour alone
**What.** Outside the `HealthBadge` component, status indicators are coloured dots
with no text or shape distinction.
**Why it matters.** Accessibility. Red and green dots are indistinguishable to a
substantial fraction of users.
**Effort.** S.
**Where.** `services/webapp/src/lib/components/analytics/`.
**Status.** ✅ Done (2026-08-02). `HealthBadge` gained an icon-only mode and is now used for component/system status dots and metric pills, so every band carries a shape.

### 1.13 Dead client code
**What.** `fetchEvalDatasets` is defined and never called; `clearChatSession` is
imported and unused.
**Effort.** S.
**Where.** `services/webapp/src/lib/`.
**Status.** ✅ Done (2026-08-02). `fetchEvalDatasets` is used by the new run form; `clearChatSession` and its unused import are removed.

---

## 2. Evaluation framework

### 2.1 ★ The config snapshot is partly fabricated
**What.** `_create_config_snapshot` hardcodes `retrieval_top_k=10`,
`hybrid_search_enabled=False`, and `contextual_retrieval_enabled=False` into every
saved run, with source comments noting the values are not available from
`/models/info`.
**Why it matters.** This is the most damaging defect found. **Every stored run
misreports the configuration that produced it**, across three of the most commonly
tuned settings. Run comparison, config diffing, and any Pareto analysis that assumes
configuration varies are all built on values that are constants. A user cannot
reconstruct what they tested, which undermines the entire measure-change-measure
workflow the product exists for.
**Fix.** Extend the rag-server `/models/info` response to include the retrieval
configuration, and read it in the snapshot. The values are already available
server-side via `get_inference_config()`.
**Effort.** S — this is a small change with disproportionate value.
**Where.** `services/evals/evals/runner.py`,
`services/rag_server/api/routes/health.py`, `services/rag_server/schemas/health.py`.
**Status.** ✅ Done — 2026-08-02, commit `e26a4d2`.

**✅ FIXED (2026-08-02).** No `/models/info` change was needed — `GET
/metrics/retrieval` already returned all three values. `RAGClient.get_retrieval_config()`
now fetches it at run start. When that call fails the fields are stored as `null`
and render as "Unknown" rather than falling back to defaults: a guessed value is
indistinguishable from a measurement once written to disk, so `ConfigSnapshot`'s
three retrieval fields are now `int | None` / `bool | None`. `_run_to_dict` was
also silently dropping `config.additional`, so saved runs now carry the full
retrieval response (`rrf_k`, reranker `top_n`, `final_top_n`). Two places that
re-introduced the same lie downstream were fixed with it: `export.py` rendered
`None` as "Disabled", and `webapp/src/lib/utils/diff.ts` rendered an uncaptured
value as an added/removed diff line, i.e. reporting a config change that never
happened. Covered by `services/evals/tests/test_config_snapshot.py`.

### 2.2 ★ No statistical significance testing anywhere
**What.** `compare` reports raw arithmetic deltas plus strict Pareto dominance. No
confidence intervals, no paired tests, no variance accounting. The per-metric
`std_dev` is computed and never surfaced in any comparison.
**Why it matters.** The product's core promise is deciding whether a configuration
change helped. Without any uncertainty estimate, it cannot distinguish a real
improvement from noise, and it does not indicate which it is showing. A difference
across 10 questions renders identically to one across 1000.
**Proposed fix**, in priority order:
1. **Paired bootstrap confidence intervals.** Compute per-question deltas between
   two runs, resample with replacement (B = 10,000), and report the 2.5th/97.5th
   percentiles alongside the point delta. Works identically for continuous judge
   scores and binary hit/miss metrics.
2. **McNemar's test for binary metrics** such as recall@k — report the discordant
   pair count so a user sees how many questions actually flipped and in which
   direction, rather than only an aggregate rate.
3. **A minimum-N floor.** Flag comparisons below a threshold as "underpowered —
   indicative only." Published guidance is explicit that normal-approximation
   intervals substantially understate uncertainty below a few hundred datapoints.
4. **A multiple-comparisons correction**, or at minimum surfacing the arithmetic:
   scanning 20 metrics uncorrected gives roughly a 64% chance of at least one
   spurious "significant" mover.
**Effort.** M for (1) and (2); S for (3) and (4).
**Where.** `services/evals/evals/cli.py` (`cmd_compare`),
`services/evals/api/routes.py` (`compare_runs`).
**Status.** ✅ Done — 2026-08-03. All four parts.

**✅ FIXED (2026-08-03).** New module `services/evals/evals/stats.py`. All four
proposals landed: seeded percentile paired bootstrap (B = 10,000) with a two-sided
p-value, McNemar's **exact** test plus discordant counts for binary metrics
(exact rather than chi-square because discordant counts at these sample sizes are
routinely under 25), an `underpowered` flag below 100 paired questions, and
Benjamini-Hochberg across the metric family with the uncorrected false-positive
arithmetic printed alongside so the correction is auditable.

The prerequisite was per-question data that could actually be paired.
`BaseMetric.compute_batch` now records `details.per_question` as a
`{question_id: score}` map — keyed by id, not a bare list, because a list
misaligns the moment one question errors in one run only and pairing by position
would then compare different questions. The three metrics that override
`compute_batch` populate it too, and the runner adds it for `latency_avg_ms`.

Only questions present in both runs are paired. Metrics with no per-question data
(aggregate-only metrics, or runs predating the capture) are reported as `skipped`
rather than given invented statistics. Reached from `compare` (default on,
`--no-significance` to skip) and `GET /eval/runs/compare` (`significance` field,
`significance=false` to skip). `numpy` became a direct dependency: a vectorized
bootstrap keeps a 20-metric comparison well under a second. Covered by
`services/evals/tests/test_stats.py`.

### 2.3 The golden dataset cannot measure retrieval
**What.** The golden loader sets `gold_passages=[]` unconditionally.
**Why it matters.** Two consequences. Retrieval metrics are meaningless on a user's
own question set — the only set that reflects their corpus. And because citation
precision and recall are *defined* to return **1.0** when no gold passages exist, a
golden-set run displays perfect citation scores that mean nothing. That is the most
misleading number the system can produce.
**Fix.** Allow optional `gold_passages` (or `gold_doc_ids`) in `golden_qa.json`, and
return `None` rather than `1.0` for citation metrics when gold data is absent.
**Effort.** M.
**Where.** `services/evals/evals/datasets/golden.py`,
`services/evals/evals/metrics/citation.py`.
**Status.** ✅ Done — 2026-08-03.

**✅ FIXED (2026-08-03).** The loader accepts `gold_passages` in three shapes
(full dicts, bare passage strings with ids derived from `document`, and the
document-level `gold_doc_ids` shorthand), plus `context_passages` and
`is_unanswerable`. `MetricResult.value` became `float | None`, and citation
metrics return `None` where they used to return `1.0`.

Two things fell out of it that were the same defect wearing a different sign.
Retrieval metrics returned **`0.0`** without gold passages, so a dataset without
retrieval annotations looked like a retrieval regression — also `None` now. And
`abstention_false_positive_rate` scored an unanswerable question `0.0` ("did not
falsely abstain"), pulling the rate down by however many unanswerable questions
happened to be in the set; same for the mirrored false-negative case. Both are
`None`.

`None` is propagated end to end rather than coerced at any boundary: `n/a` in the
CLI and exports, `null` over the API, a muted `n/a` in the dashboard, and the
weighted score drops the objective and redistributes its weight instead of
scoring it zero. Document-level gold needed a matching path of its own in the
citation metrics — a text-less gold passage can only ever be resolved by doc id,
and would otherwise have scored a spurious 0. Covered by
`tests/test_golden_dataset.py` and `tests/test_undefined_metrics.py`.

The shipped `golden_qa.json` is deliberately **not** back-annotated: its
`document` values are filenames, and gold passages must carry the doc ids the RAG
server assigns. Guessing would have reintroduced exactly the class of bug this
fixes.

### 2.4 Single judge, and the default pairs judge with generator by family
**What.** One judge model scores every generation metric. No ensemble, no
inter-rater agreement. The shipped defaults use OpenAI models for both
`active.inference` and `active.eval`.
**Why it matters.** Self-preference bias in LLM judges is documented to extend
across a model family, not only to identical models. The default configuration is
therefore not a neutral referee for exactly the comparison users most want to run —
local versus cloud generation.
**Fix.** Warn at startup when judge and generation model share a provider. Longer
term, support an ensemble with agreement reporting.
**Effort.** S for the warning, L for ensembles.
**Where.** `services/evals/evals/judges/llm_judge.py`, `config.yml`.
**Status.** Partially done — 2026-08-03. Warning done; ensembles still open.

**✅ WARNING ADDED (2026-08-03).** `check_judge_independence` compares
`active.inference` and `active.eval` providers; `warn_if_judge_not_independent`
logs it, the CLI prints it before the run, and it is stored on the run at
`metadata.judge_independence_warning` — the person reading the scores months
later is the one who needs to know the judge was not neutral. The run report
renders it as a caveat block. The shipped defaults (both OpenAI) do trigger it.

Still open: **ensemble judging with inter-rater agreement**. A warning tells you
the referee may be biased; it does not measure by how much.

Distinct from the judge data-egress gate, which is a check on the same two
fields for a different reason. That gate was originally the `pii.allow_cloud_judge`
check in `2131914` (2026-08-01); it was replaced by the `data_policy` /
`ExecutionBoundary` model on 2026-08-26 — see **4.11**.

### 2.5 Calibration covers half the judge prompts
**What.** `calibrate` checks faithfulness against adherence labels and context
relevance against relevance labels. `answer_correctness` and `answer_relevancy` are
never checked against ground truth.
**Why it matters.** Two metrics users rely on have no evidence of agreeing with a
human on anything.
**Effort.** M.
**Where.** `services/evals/evals/calibration.py`.
**Status.** ✅ Done — 2026-08-03, with a stated limitation.

**✅ FIXED (2026-08-03).** There is no RAGBench label corresponding to answer
correctness or answer relevancy, so calibrating them against ground truth is not
available at any effort. What is available for free is that an item's reference
response is correct for *its own* question and wrong for a different item's.
`calibrate` now runs a **discrimination check** on both prompts: each response is
scored against its own reference/question and against a neighbouring item's, and
the result reports mean matched score, mean mismatched score, separation, and the
fraction of pairs the judge ranked correctly.

This is deliberately labelled a floor rather than a calibration, in the CLI output
and in the docs: accuracy well below 100% means the prompt is unreliable, near
100% only means it is not broken. Claiming more would be the same kind of
overstatement the rest of this section exists to remove. Reported as
`correctness_discrimination` / `relevancy_discrimination` in the saved result.

### 2.6 The richer exporters are unreachable
**What.** `export_for_review`, `export_scorecard`, and `export_run_report` are
implemented and called from nowhere. The CLI's `export` subcommand has its own
simpler inline logic.
**Why it matters.** `export_for_review` produces per-question CSV and Markdown with
blank reviewer columns — a human-review workflow that would directly mitigate 2.4,
already written and unusable.
**Effort.** S — wire them to CLI flags.
**Where.** `services/evals/evals/export.py`, `services/evals/evals/cli.py`.
**Status.** ✅ Done — 2026-08-03.

**✅ FIXED (2026-08-03).** `export --format` gained `review-json`, `review-csv`,
`review-md`, `scorecard-csv`, `scorecard-md` and `report`, all wired to the
existing library functions.

The S estimate missed a prerequisite: `export_for_review` takes question/response
objects, and the run JSON holds aggregates only, so there was nothing on disk to
export. Runs now write a per-question sidecar, `{run}_samples.json`, alongside the
run file — sidecar rather than inline because run files are read on every
dashboard request and indexed wholesale at startup, and a few hundred answers with
their retrieved chunks dwarf the metrics they accompany. `evals/samples.py`
handles both directions; the job manager's run index skips the sidecars.

Runs completed before the sidecar existed cannot be exported for review, and the
command says so rather than emitting an empty sheet.

### 2.7 Weighted-score normalization thresholds are hardcoded
**What.** Latency and cost are normalized against fixed constants in the runner
(latency thresholds in the tens of thousands of milliseconds, a maximum cost per
query of 0.10 USD). The objective weights are Python constants, not `config.yml`
keys.
**Why it matters.** A latency-sensitive deployment weighting latency at 0.05 against
thresholds chosen for a different profile gets a headline number that does not
reflect its constraints — and cannot change it without editing code.
**Effort.** S — move to `config.yml`.
**Where.** `services/evals/evals/config.py`, `services/evals/evals/runner.py`.
**Status.** ✅ Done — 2026-08-03.

**✅ FIXED (2026-08-03).** New `eval.scoring` block in `config.yml`: `weights`,
`latency_threshold_ms_generation`, `latency_threshold_ms_end_to_end` and
`max_cost_per_query_usd`, validated by `ScoringSettings` (negative or all-zero
weights are rejected). `ScoringConfig.from_models_config()` reads them, falling
back to module constants when the config is unavailable, and the runner uses them
instead of the inline numbers.

The resolved values are recorded in each run's `metadata.scoring`, because these
settings decide what the headline number *means* — a run compared across a change
to them is not comparable, and without the record there would be no way to tell
that had happened.

### 2.8 Stale artifacts from the previous framework
**What.** `evals/data/golden_baseline.json` and old run files reference metrics
(`contextual_precision`, `hallucination`) that no longer exist. Nothing reads them.
**Why it matters.** Anyone browsing `data/` concludes those metrics exist.
**Effort.** S — delete.
**Where.** `services/evals/evals/data/`.
**Status.** ✅ Done — 2026-08-03. `golden_baseline.json` and the
`evals/data/results/` directory are deleted; nothing referenced either.

### 2.9 Smaller items
| Item | Effort | Where | Status |
|---|---|---|---|
| No caching of query or judge responses — re-running an identical config repeats all work | M | `runner.py` | ✅ Done — 2026-08-03 |
| `cleanup_on_failure` is declared and never read | S | `config.py` | ✅ Done — 2026-08-03 |
| One active job process-wide; a second request gets a 409 with no queue | M | `api/job_manager.py` | ✅ Done — 2026-08-03 |
| The `qasper` loader is documented as broken with `datasets>=4.0` | M | `datasets/qasper.py` | ✅ Done — 2026-08-03 (documentation was stale, loader works) |
| Eval runs are flat JSON with no backup; deleting a file loses the run permanently | M | `runner.py` | ✅ Done — 2026-08-03 |
| `data/calibration/` is not bind-mounted, so calibration results are lost whenever the container is recreated — unlike `data/eval_runs/`, which is mounted | S | `docker-compose.yml` | ✅ Done — 2026-08-03 |
| `evals/README.md` is stale — says to run from `services/rag_server/`, names Claude Sonnet as the judge default when `active.eval` is an OpenAI model | S | `evals/evals/README.md` | ✅ Done — 2026-08-03 |

Notes on the less obvious ones:

**Response caching** (`evals/cache.py`) is content-addressed on disk, and the two
halves ship with different defaults because their risk profiles differ. The judge
cache is **on**: temperature is 0, so an identical prompt is an identical call. The
query cache is **off** behind `--cache-queries`, because its key covers the
server's reported configuration but *not the indexed corpus* — after a re-ingest a
cached answer is stale while looking fresh. It also self-disables when the server
did not report its retrieval configuration, since the fingerprint then cannot tell
two pipelines apart. A cache hit replays the originally measured latency rather
than the hit time, so latency metrics do not silently become a measurement of the
cache.

**`cleanup_on_failure`** now does what its name says: on a failed end-to-end run
with the flag false, ingested documents are left in place and the count is logged,
because the corpus is the only way to reproduce what the failing queries saw.
Cleanup on success is unconditional.

**The job queue** is FIFO with depth `EVAL_QUEUE_DEPTH` (default 5). A second
trigger queues and gets a `queue_position` in the 202 response; only a full queue
returns `429` (was `409`). `GET /eval/queue` and `DELETE /eval/queue/{job_id}`
expose it. The queue is in-memory, so a restart loses pending jobs — acceptable
for jobs that have not started, and the alternative is a persistence layer this
service deliberately does not have.

**`qasper`** was not broken. It already loaded via the `refs/convert/parquet`
revision and handled both `qas` shapes; a run against `datasets` 4.5.0 returns
questions with gold passages. The claim was stale documentation in four places,
now corrected rather than a code change.

**Run backups** are a copy of each run JSON into `data/eval_runs/backup/` at save
time. Not a substitute for a database, but it makes an accidental `rm` in the runs
directory recoverable.

### 2.10 `context_truncated` has no real measurement
**What.** Failure attribution's `context_truncated` stage is meant to detect
evidence that survived reranking but was dropped before generation — packed out of
the context window, deduplicated away, etc. Measuring it requires a distinct trace
of what was *actually assembled into the prompt*. The installed
`CondensePlusContextChatEngine` returns `_aget_nodes()`'s output straight out of
`_run_c3`, so the `context_assembly` trace attribution reads is the reranker's own
node list, not an independent measurement — comparing it against itself can only
ever agree.
**Why it matters.** A label that can structurally never fire is worse than no
label: it implies the stage is being checked. `attribute_question` now detects the
mirrored list (`_same_items`) and marks the stage explicitly unassessable with a
reason, rather than emitting `context_truncated=False` as if it had been checked
and passed.
**Effort.** M — needs the response synthesizer instrumented to emit what it
actually received, which is a real engine change, not an attribution fix.
**Where.** `services/evals/evals/attribution.py`,
`services/rag_server/pipelines/inference.py`.
**Status.** Open — worked around by making the gap explicit; not measured.

---

## 3. Configuration

### 3.1 ★ Chunk size and overlap are not configurable
**What.** `chunk_size=500` and `chunk_overlap=50` are hardcoded in
`services/rag_server/core/config.py`.
**Why it matters.** These are among the highest-leverage RAG tuning parameters, and
changing them requires a code edit and an image rebuild. The documented chunk-size
experiment cannot be run by configuration alone — the only recipe in the guide with
that limitation.
**Effort.** S — add a `chunking` section to `config.yml`.
**Where.** `services/rag_server/core/config.py`.
**Status.** ✅ Done — 2026-08-27.

**✅ FIXED (2026-08-27).** `ChunkingConfig` (`chunk_size`, `chunk_overlap`) in
`infrastructure/config/models_config.py`, a `chunking:` block in `config.yml`, and
`get_chunking_config()` beside `get_ingestion_config()`. All three former literals
now read it: LlamaIndex `Settings` (`core/config.py`), the `SentenceSplitter` in
`pipelines/ingestion.py` (the bare `chunk_overlap=50` included), and
`GET /metrics/retrieval`.

The endpoint additionally reports a `chunkers` list naming each path and only the
parameters it has — the Docling chunker splits on document structure and reports
`chunk_size: null` rather than the SentenceSplitter's numbers, which it never used.
`ConfigSnapshot` carries `chunk_size`, `chunk_overlap` and `chunker`, all
`| None`, so a run against an older server records "not captured" instead of a
default that happens to match. This closed the last live instance of the 2.1
defect class.

### 3.2 ★ Three provider API keys have no supported path
**What.** The settings classes read `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, and
`MOONSHOT_API_KEY`, and `config.yml` offers `gemini-pro`, `deepseek-chat`, and
`moonshot-v1`. **No compose file declares any of them as a Docker secret.**
**Why it matters.** Selecting one of these providers passes YAML validation and then
fails at boot. The configuration file advertises capabilities that cannot be used
without hand-editing compose.
**Fix.** Declare the secrets in `docker-compose.yml`, or remove the model entries.
**Effort.** S.
**Where.** `docker-compose.yml`, `config.yml`.
**Status.** ✅ Done — 2026-08-02, commit `e26a4d2`.

**✅ FIXED (2026-08-02).** Removed, per the owner's call that none of the three are
in use. Gone from both `Settings` classes, the `LLMProvider` enum, the key
validators and their dispatch, the factory provider map, all three cost tables, and
`config.yml`. The now-unused `llama-index-llms-google-genai` and
`llama-index-llms-deepseek` dependencies were dropped from both `pyproject.toml`
files. `config.yml` keeps a commented example entry, and the enum, both settings
classes and the compose `secrets:` block carry a checklist of everything a future
provider must touch — enum value, key field in both settings classes, validator +
dispatch entry, factory entry, compose secret, cost-table entry.

### 3.3 Six config keys are parsed and never acted on
| Key | What actually happens |
|---|---|
| `models.reranker.*.top_n` | Ignored; the reranker uses `max(5, retrieval.top_k // 2)` |
| `database.max_connections` | Never read; the real limit is hardcoded in `docker-compose.yml` |
| `eval.abstention_phrases` | Not used by the abstention metrics, which use a hardcoded list |
| `pii.masking_strategy` | Only one legal value; nothing branches on it |
| `pii.validation.max_retries` | No retry loop exists |
| `pii.validation.alert_on_failure` | No alerting path exists |

**Why it matters.** Each is a knob a user can turn with no effect and no warning. An
experiment "tuning" one of these measures nothing while appearing to work.
`reranker.top_n` is the worst case, because `just show-config-full` prints the
configured value — actively telling the user a number that is not in use.
**Effort.** S each — either wire them up or remove them. `reranker.top_n` should be
wired up; the rest are probably removals.
**Status.** ✅ Done — 2026-08-02, commit `e26a4d2` (all six keys resolved: two wired
up, four removed).

**✅ FIXED (2026-08-02).** `reranker.top_n` and `eval.abstention_phrases` wired up;
the other four removed from `config.yml` and their schema models, with a pointer
left at the real `max_connections` in `docker-compose.yml`. `top_n` now resolves
through `effective_reranker_top_n(configured, top_k)` — configured value when set,
`max(5, top_k // 2)` otherwise — used by the reranker, `/metrics/retrieval` and both
config banners, so the displayed number is the one in use (this also closes the
`show-config-full` half of **3.7**). With the shipped config the effective value is
unchanged at 5, so no existing scores move.

Two traps worth recording, because both would have shipped a knob that only *looked*
wired:
- `config.yml` held six **exact sentences** where the metric used fifteen lenient
  **substrings**. Making the config authoritative as-written would have silently
  narrowed abstention detection ("I don't know", "I cannot answer that" would stop
  counting) and depressed `UnanswerableAccuracy` / `FalseNegativeRate` with nothing
  about the model having changed. The config list is now the substring fragments,
  which subsume the six sentences, so scores are preserved.
- The reader first went through `get_models_config()`, which validates the active
  provider's API key and **raises without one** — so on any host with no secrets
  mounted it silently fell back to the hardcoded list, once per answer scored.
  Reading an eval setting must not depend on model credentials; there is now a
  `load_raw_config()` that parses `config.yml` with no validation or secret
  injection, the result is cached, and the fallback logs that scores no longer
  reflect config. Covered by `services/evals/tests/test_abstention_config.py`,
  which asserts the result is *not* the fallback object so a silent regression
  fails rather than passing vacuously.

### 3.4 RRF source weights are not exposed
**What.** `bm25_weight` and `vector_weight` are hardcoded to `1.0`; the factory never
passes them through.
**Why it matters.** Weighting keyword search against vector search is a natural
tuning axis — corpora heavy in identifiers benefit from favouring BM25 — and it is
unavailable.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/search/hybrid_retriever.py`.
**Status.** Open — the constructor still defaults both weights to `1.0` and no
caller passes them.

### 3.5 Task worker constants are hardcoded
**What.** Poll interval, max attempts, a one-hour stuck-task timeout, retry delays,
and a worker concurrency cap are module constants. The cap silently overrides the
`WORKER_CONCURRENCY` environment variable.
**Why it matters.** These are operational parameters. The stuck-task timeout
determines how long a crashed job blocks reprocessing, and a silently-capped env var
is a confusing failure.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/tasks/task_worker.py`.
**Status.** Open.

### 3.6 Multiple drifting model-cost tables
**What.** Hardcoded per-model pricing exists in at least
`services/rag_server/api/routes/health.py` and `services/evals/evals/config.py`, with
differing values. Neither is sourced from configuration or a pricing feed.
**Why it matters.** Reported cost differs depending on which service you ask, and
both drift from real prices as vendors change them.
**Effort.** M — single source, ideally in `config.yml`.
**Status.** Open. `e26a4d2` pruned the removed providers from all three cost tables,
so they agree on fewer models, but the tables are still duplicated and hardcoded.

### 3.7 Config inspection is incomplete and partly misleading
**What.** `just show-config-full` prints the configured reranker `top_n`, which is
not the value used. Neither banner prints the `database` or `chat_memory` sections.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/config/display.py`.
**Status.** Partially done — the misleading half closed 2026-08-02 (`e26a4d2`): both
banners now print the effective reranker `top_n` via `effective_reranker_top_n()`.
Still open: neither banner prints the `database` or `chat_memory` sections.

---

## 4. Correctness defects

### 4.1 ★ Deleting a document leaves its vectors in the separate vector store
**What.** Document deletion removed the Postgres rows and the stored file. Nothing
removed the corresponding embeddings, which at the time lived in a second, separate
vector service.
**Why it matters.** Orphaned vectors accumulate indefinitely and remain retrievable,
so deleted content can still surface in answers. For a system whose selling point is
data control, "delete does not delete" is a serious defect — and a plausible
compliance problem for anyone relying on deletion.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/database/documents.py`.
**Status.** ✅ Done — 2026-08-02, commit `e26a4d2`; **superseded 2026-08-21** by the
pgvector migration, which makes the class of defect unreachable.

**✅ FIXED (2026-08-02).** Vectors were keyed on the `document_id` metadata field
written during ingestion, which is exactly what the vector store's
`delete(ref_doc_id)` filtered on, so no ingestion change was needed. A new
`services/document_service.py` became the single entry point used by both call sites
(the HTTP route and the worker's pre-retry reset — the latter now also cleans up
vectors a *failed* ingestion left behind, the same bug in another guise).

**Ordering:** vectors first, then the Postgres row. If the vector service was
unreachable the call raised before Postgres was touched, so the document stayed
visible and the delete was retryable, and the route returned 500 instead of "deleted
successfully". The accepted tradeoff was that a Postgres failure after a successful
vector delete left a listed document with no vectors — a silent dead entry, far less
bad than a phantom retrievable one.

**Pre-existing orphans** (anything deleted before that fix shipped) were not swept
automatically; a `reconcile-vectors` script and its `just` recipes existed for that.

**✅ SUPERSEDED (2026-08-21).** Embeddings moved into an `embedding vector(768)`
column on `document_chunks` (768 was the dimension at the time — the column is
`vector(1024)` today, after the Ollama→TEI/Qwen3 embedding migration; the
`ON DELETE CASCADE` behaviour described below is unaffected by that change),
indexed with pgvectorscale StreamingDiskANN. Deleting a
document is now the `ON DELETE CASCADE` that was always on
`document_chunks.document_id`: one statement removes the row, the chunks and the
vectors together. The explicit vector-delete step, its ordering tradeoff, the
reconcile script and both `just` recipes are all deleted — an orphaned vector is no
longer a state the schema can reach. `services/document_service.py` remains as the
shared entry point; `services/rag_server/tests/test_document_deletion.py` still
covers it.

### 4.2 ★ CI and Makefile reference a test file that no longer exists
**What.** Both the Forgejo CI eval job and the `Makefile` eval targets point at
`services/rag_server/tests/test_rag_eval.py`, removed when evals moved to
`services/evals/`. CI also references a `--group eval` dependency group that no
longer exists.
**Why it matters.** The CI eval job is broken as committed. A broken job is worse
than no job — it either fails constantly and gets ignored, or passes vacuously.
**Effort.** S.
**Where.** `.forgejo/workflows/ci.yml`, `Makefile`.
**Status.** ✅ Done — 2026-08-02, commit `e26a4d2`. Both CI jobs are green, at the
cost of the deselections recorded in **4.8** and the 4.4 note.

**✅ FIXED (2026-08-02).** The `Makefile` was deleted rather than repaired — the
`justfile` already covered every target (the only difference: `make docker-logs`
implied `docker-up`; `just logs` does not). The gated `test-eval` job was removed
rather than repointed: the real end-to-end eval is `just test-eval`, which needs
docker compose and a running rag-server. `test` became `test-rag-server`, the stale
`--ignore` flags are gone, and a new always-on `test-evals` job was added.

**The bigger finding:** `services/evals/tests/` (4 files, ~1,600 lines) ran in **no
CI job at all**, and was not green — 19 of its tests failed on an unmodified tree.
Adding it verbatim would have committed a red job, which is the exact failure this
item is about. Both jobs now run commands verified to pass: rag_server **127 passed,
38 skipped, 1 xfailed**; evals **103 passed, 31 skipped**. See **4.8** for what had
to be deselected to get there.

### 4.3 `content_with_context` is always empty
**What.** The BM25 retriever reads `content_with_context` and falls back to
`content`. The ingestion path never populates it — it reads a `contextual_prefix`
metadata key that is never set, and merges generated context into the node text
instead.
**Why it matters.** A column exists, is queried, and is always empty. Either the
contextual prefix should be stored there or the column and its read path should go.
**Effort.** S.
**Where.** `services/rag_server/pipelines/ingestion.py`,
`services/rag_server/infrastructure/search/bm25_retriever.py`.
**Status.** ✅ Done — 2026-08-03. The column and its read path were removed.

**✅ FIXED (2026-08-03).** Of the two options, the column went. The generated
prefix is prepended to `node.text` before embedding, so it is already inside
`document_chunks.content` — which is also the column `idx_chunks_bm25` indexes.
A second column would have duplicated that text, and the retriever's
`content_with_context or content` was a no-op in every case. Removed from
`init.sql`, the ORM model, `add_chunks()`, the ingestion `chunks_data` payload
(along with the dead `contextual_prefix` metadata filter) and the retriever's
SELECT.

**Existing databases** keep the empty column — `init.sql` does not re-run on an
existing volume. Nothing reads or writes it; drop it by hand if you want it gone:
`ALTER TABLE document_chunks DROP COLUMN IF EXISTS content_with_context;`

### 4.4 Two BM25 implementations, and the test covers the wrong one
**What.** The live retriever uses `to_bm25query` with the `<@>` operator. A second
function, `search_chunks_bm25`, uses `bm25_search` with `websearch_to_tsquery` and is
called only by its own test. That test asserts the live retriever emits the *unused*
implementation's SQL.
**Why it matters.** The test provides false confidence about query-safety behaviour
that the live path does not have. Anyone debugging special-character handling will
be misled by both the test and the dead function.
**Effort.** S — delete the unused function and correct the test.
**Where.** `services/rag_server/infrastructure/database/documents.py`,
`services/rag_server/tests/test_bm25_query_safety.py`.
**Status.** ✅ Done — 2026-08-03.

**✅ FIXED (2026-08-03).** `search_chunks_bm25` is deleted, and with it
`test_document_bm25_search_uses_pg_textsearch`, which only ever proved that an
uncalled function still looked the way it always had. The skipped test is
rewritten against the live retriever: it asserts the SQL contains
`to_bm25query(:query, 'idx_chunks_bm25')` and that the query text is bound as a
parameter rather than appearing anywhere in the SQL string — which is the
query-safety property the file claims to cover.

### 4.5 BM25 failures degrade silently
**What.** The retriever catches all exceptions, logs a warning, and returns an empty
list.
**Why it matters.** A broken `pg_textsearch` extension or index turns every hybrid
query into a vector-only query with no error surfaced. The system appears healthy
while half its retrieval strategy is dead — and a user measuring "does hybrid search
help?" would conclude it does not.
**Fix.** Surface BM25 health in `/health` or `/metrics/system` so the failure is
visible without reading logs.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/search/bm25_retriever.py`,
`services/rag_server/services/metrics.py`.
**Status.** ✅ Done — 2026-08-03.

**✅ FIXED (2026-08-03).** The `except` still swallows the error — a BM25 fault
should not fail a user's query — but it now logs at `ERROR` and records the
failure in module state (`get_bm25_health()`). `/metrics/system` reports
`component_status.bm25`, combining that with an active probe (`probe_bm25()`)
that runs the same `<@>`/`to_bm25query` pair against `idx_chunks_bm25`:

| Value | Meaning |
|---|---|
| `healthy` | probe works, last real search succeeded |
| `unhealthy` | probe works, last real search failed |
| `unavailable` | probe itself fails — extension, index or permissions |

The probe answers before any query has run, so a dropped index is visible at
boot rather than after a confusing eval. The key is omitted when hybrid search
is disabled. Covered by `tests/test_bm25_health.py`.

### 4.6 The startup banner names the wrong technologies
**What.** `services/rag_server/main.py` logged "pg_search BM25 + pgvector". Neither
half was true at the time: there is no `pg_search` extension, and `pgvector` was a
listed but unused dependency while the vectors lived in a separate service.
**Effort.** S.
**Status.** ✅ Done — 2026-08-03; re-checked after the 2026-08-21 pgvector
migration.

**✅ FIXED (2026-08-03).** The same wrong claim was also served by the API:
`VectorSearchConfig.vector_store` defaulted to `"PostgreSQL (pgvector)"` and
`get_retrieval_config()` passed that literal, so `/metrics/retrieval` — which
the dashboard renders — named a store the system did not use. Both were corrected
to name the store actually in use.

**Follow-up (2026-08-21).** The migration made the original wording accurate by
accident, but the values were re-derived rather than reverted. The banner reads
"pg_textsearch BM25 + pgvector vectors", and `/metrics/retrieval` now reports
`vector_store: "pgvector"`, `index_type: "diskann"` and `table_name:
"document_chunks"` — the collection-name field is gone with the collection concept.

### 4.7 Documentation and code disagree on whether contextual enrichment is masked
**What.** The repository contradicts itself. The `config.yml` comment and the
`validate_privacy_posture` docstring both state that contextual enrichment is never
masked. The `PiiConfig` class docstring, a few lines away in the same file,
correctly states that the document name and chunk preview *are* masked — which
matches the code: `_mask_contextual_inputs` masks both before the contextual-prefix
LLM call and unmasks the returned prefix.
**Why it matters.** A privacy claim where the in-repo description contradicts the
implementation. Here the code is safer than the comment, but a reader deciding
whether to enable contextual retrieval with a cloud provider is reading the comment.
**Fix.** Correct the comment and the docstring.
**Effort.** S.
**Where.** `config.yml`,
`services/rag_server/infrastructure/config/models_config.py`,
`services/rag_server/pipelines/ingestion.py`.
**Status.** ✅ Done — 2026-08-03. Both statements now match the code: masking
covers every path that reaches the LLM (generation *and* contextual enrichment);
embeddings and reranking are what stay unmasked and local.

### 4.8 ★ Eleven eval tests import rag-server internals and fail everywhere
**What.** `services/evals/tests/test_rag_eval.py` — `TestCitationExtraction` (8
tests) and `TestQueryEndpointIncludeChunks` (3) — does
`from pipelines.inference import extract_numeric_citations` / `extract_sources`.
`pipelines` is a **rag-server** package, not installed in the evals service, so
these fail with `ModuleNotFoundError` on any machine. They were left behind when
evals moved out of `services/rag_server/`, and because the evals suite ran in no CI
job (**4.2**), nobody saw it.
**Why it matters.** Eleven tests covering citation extraction — which the citation
metrics depend on — have not run since the move. They are currently
`@pytest.mark.skip`-ped with the cause in the reason string so the suite is honestly
green, but the coverage is simply absent.
**Fix.** They test rag-server code, so move them to `services/rag_server/tests/`.
**Effort.** S.
**Where.** `services/evals/tests/test_rag_eval.py`.
**Status.** ✅ Done — 2026-08-03. Moved to
`services/rag_server/tests/test_citation_extraction.py`; all eleven run in the
`test-rag-server` CI job. The skip markers and the per-test local imports are
gone (the imports are now module-level, which is what makes the move honest —
the file cannot silently stop importing the code it tests).

### 4.9 Importing the task worker performs live network I/O
**What.** Importing `services/rag_server/infrastructure/tasks/task_worker.py`
triggered a real `httpx.get()` embedding-endpoint reachability check at module
scope. With no endpoint reachable this doesn't just fail a test — it crashes
the whole pytest collection with `INTERNALERROR`/`SystemExit`, taking the
entire rag-server suite with it. At the time, `config.yml`'s active embedding
was `ollama` at `host.docker.internal:11434`, so a CI runner hit this too; the
active embedding provider is `tei` today, but the import-time hazard this item
describes was about *where* the check ran, not which provider it targeted.
**Why it matters.** Import-time side effects that reach the network make a module
untestable and can take down an unrelated suite. Worked around at the test level
(mocking the reachability check); the import-time call itself is
untouched.
**Fix.** Make the reachability check lazy, at first use rather than at import.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/tasks/task_worker.py`,
`services/rag_server/core/config.py`.
**Status.** ✅ Done — 2026-08-03.

**✅ FIXED (2026-08-03).** `init_settings()`/`initialize_settings()` moved from
module scope into `main()`, so importing the module reaches nothing. The check
itself stays eager *within* `main()` — a worker that cannot reach its embedding
provider should fail at boot, not on the first document — the defect was where
it ran, not that it runs. The test-level workaround
(`test_task_worker_concurrency.py`'s import-time patching of the reachability
check and the vector-store client) is deleted and replaced by a regression test
asserting the import stays inert. (The reachability check itself was later
renamed `check_embedding_endpoint_reachable` as part of the Ollama→TEI
migration; the fix described here — making it lazy — is unaffected by that
rename.)

### 4.10 `ConfigSnapshot` in the rag-server schemas is dead code
**What.** `services/rag_server/schemas/metrics.py:159` defines a 15-field pydantic
`ConfigSnapshot` — a richer model than the evals dataclass actually used, including
`llm_base_url`, `rrf_k`, `reranker_top_n` and `citation_scope`. Nothing constructs
it anywhere.
**Why it matters.** It reads as the authoritative snapshot model and is not wired to
anything, so a reader fixing snapshot behaviour may edit the wrong type. It is also
a better shape than the one in use — worth harvesting rather than only deleting.
**Effort.** S.
**Where.** `services/rag_server/schemas/metrics.py`.
**Status.** ✅ Done — 2026-08-03. Deleted.

**✅ FIXED (2026-08-03).** Nothing further was harvested: the evals snapshot's
`additional` field already carries the whole `/models/info` and
`/metrics/retrieval` payloads, so every remaining field of the pydantic model
(`llm_base_url`, `citation_scope`, `citation_format`, `abstention_phrases`) was
either already captured there or not available to the eval runner at all —
adding declared-but-unfilled fields is the 2.1 defect in a new place. The
module docstring now points at `evals/schemas/results.py` as the only snapshot
type.

### 4.11 `active.eval` was dead configuration, and the judge privacy gate checked the wrong thing
**What.** Two defects on the same code path, found together.

*Dead judge config.* `JudgeConfig` defaulted to `provider="anthropic"`,
`model="claude-sonnet-4-20250514"`. Both entry points — `evals/cli.py` and
`api/job_manager.py` — constructed `JudgeConfig(enabled=...)` and passed neither
field, so the defaults always won. `_load_default_config()` in `llm_judge.py` read
`active.eval` correctly but only ran when `config is None`, which never happened.
Every real eval run called Anthropic, at a model retired 2026-06-15, whatever
`config.yml` said.

*The privacy gate was uninformative.* Judge egress was gated by `pii.enabled` plus
a `LOCAL_JUDGE_PROVIDERS` set, with a `pii.allow_cloud_judge` opt-out. The set was
empty, so every judge classified as cloud and the opt-out was the only way to run
anything. Worse, "local" was being inferred from the provider string, which cannot
distinguish a self-hosted OpenAI-compatible endpoint from `api.openai.com`, and the
whole check hung off `pii.enabled` — but confidential content need not contain any
PII.

**Why it matters.** The first defect makes every run's recorded judge a fiction and
bills an account nobody chose. The second is worse: the two combined meant a
validation layer could have reported a "local" judge while the runtime called
Anthropic — a privacy claim in the documentation that the code did not implement.
**Effort.** M.
**Where.** `services/evals/evals/config.py`,
`services/evals/evals/judges/llm_judge.py`, `services/evals/evals/cli.py`,
`services/evals/api/job_manager.py`, both services'
`infrastructure/config/models_config.py`, `config.yml`.
**Status.** ✅ Done — 2026-08-26.

**✅ FIXED (2026-08-26).** `resolve_judge_config()` is now the single source of
judge identity: it reads `active.eval`, validates it, and returns a fully resolved
`JudgeConfig` carrying provider, model, `base_url`, temperature, timeout, retries
and `execution_boundary`. `JudgeConfig` has no provider/model defaults and
`LLMJudge` refuses a config it was not handed, so there is no path left that can
substitute a different model. The resolved values are recorded in run metadata
(`judge_provider`, `judge_model`, `judge_execution_boundary`).

The gate was replaced rather than repaired. `LOCAL_JUDGE_PROVIDERS` and
`pii.allow_cloud_judge` are gone; a three-value `ExecutionBoundary`
(`customer_managed` / `aws_managed` / `third_party`) is declared per model
definition in `config.yml` as a property of the resolved endpoint, and
`data_policy` holds an allow-list defaulting to `{customer_managed, aws_managed}`.
A missing boundary fails closed. Enforcement runs at config load and again at judge
resolution, so the object the runtime calls is the object that was checked.
Rationale in `docs/internal/design-decisions.md`; covered by
`services/evals/tests/test_privacy_posture.py` and
`services/evals/tests/test_judge_config_resolution.py`.

Note that **4.11 does not close 3.6** — the duplicated, hardcoded cost tables are
untouched by this change.

### 4.12 PDF evidence locators were unusable for real Docling output
**What.** Two defects on the same code path, found together while authoring
source-coordinate PDF fixtures.

*Bbox origin.* Docling emits PDF provenance with `coord_origin: BOTTOMLEFT`, where
the top edge of a box has a *larger* y-coordinate than the bottom edge.
`_valid_bbox` asserted `value[1] < value[3]`, which is only true for a
top-left-origin box, so it rejected every real PDF bbox as malformed. Every PDF
locator was therefore unusable and the whole PDF evidence path was a lineage
failure by construction, never a real check.

*Wrong locator field.* `_locator_is_usable` accepted only a `block_id` or a bbox.
Docling's actual provenance carries `element_id` (its `self_ref`), not `block_id`,
so a real Docling PDF chunk had neither an accepted id nor (until the first fix) a
usable bbox — unusable twice over.

**Why it matters.** Both defects together meant no PDF gold question could ever
resolve to a chunk; the source-coordinate ground-truth work would have silently
degraded to "PDF evidence never verifies" without ever raising an error to say so.
**Effort.** S — both are narrow, already fixed.
**Where.** `services/evals/evals/evidence.py` (`_normalized_bbox`,
`_locator_is_usable`).
**Status.** ✅ Done — 2026-08-29. Regression tests in
`services/evals/tests/test_source_coordinate_authoring.py::TestDoclingBboxOrigin`.

### 4.13 `init.sql`'s `CREATE TABLE IF NOT EXISTS` does not apply column additions to an already-initialized database
**What.** `services/postgres/init.sql` runs only once, via
`docker-entrypoint-initdb.d`, on an empty Postgres volume. Adding a column to an
*existing* table's `CREATE TABLE IF NOT EXISTS` block (e.g. `document_chunks
.source_locator JSONB`, added for source-coordinate evidence) is a silent no-op on
any volume that already has that table — the file is byte-identical to "correct"
and nothing about running it says the new column never applied. New tables in the
same file **do** get created (`IF NOT EXISTS` is only a no-op for tables that
already exist), which is why this was easy to miss: most of a given change lands
fine and only the one altered pre-existing table silently doesn't.
**Why it matters.** The failure surfaces far from the cause: every read of the new
column raises `asyncpg.exceptions.UndefinedColumnError` / HTTP 500 at query time,
not at container start, on a volume that looks fully migrated (`\dt` shows every
table `init.sql` declares). This is not specific to the AWS demo's baked-AMI case
already tracked in §7.2 — it hits any long-lived local dev Postgres volume the
moment a change adds a column to a table that already existed, which is exactly
what happened here: `document_chunks.source_locator` was missing from the running
dev database and broke `GET /documents/{id}/chunks` until manually added with
`ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS source_locator JSONB;`.
**Effort.** S — no migration tooling needed while this project is in development,
not production (see `CLAUDE.md`); a real migration path is deferred until that
changes. The dev-mode fix is making `init.sql` idempotent and re-runnable.
**Where.** `services/postgres/init.sql`, `justfile`.
**Status.** ✅ Done — 2026-08-29. Every statement in `init.sql` is now safe to
re-run against an already-initialized database: `CREATE INDEX` uses
`IF NOT EXISTS` throughout, and `document_chunks` gets an explicit
`ALTER TABLE ADD COLUMN IF NOT EXISTS source_locator JSONB` (the pattern to
repeat for the next column added to an existing table). `just db-reconcile`
re-applies `init.sql` against the running container, and `just up` now calls it
automatically after postgres is healthy, so drift self-heals on every start
instead of requiring a manual `ALTER TABLE`.

> **Section 4 was complete as of 2026-08-03** for entries 4.1–4.10. Both suites
> were green with no skips attributable to those entries: rag-server **147 passed,
> 37 skipped, 1 xfailed**; evals **190 passed, 20 skipped** (the 11
> previously-skipped citation tests moved into the rag-server count). **4.11** was
> found later and resolved on 2026-08-26.

---

## 5. Unverified claims

Traced during this exercise under a no-invented-measurements rule.

### 5.1 "~48% better retrieval than either method alone" — **unverified**
**Where.** `OVERVIEW.md`, attributed to hybrid search + RRF.
**Finding.** No source was located. The figure does not appear in Anthropic's
contextual-retrieval post, and no vendor benchmark using it was found. It is not a
plausible transcription of any figure in that post — those are 35%, 49%, 67%, and
90%, and all concern contextual retrieval rather than hybrid search.
**Action.** Cite a real source or remove the number. It should not be repeated as
fact.
**Status.** Partially done — gone from `OVERVIEW.md` as of the 2026-08-01 docs
rewrite (`352fb07`), but it survives verbatim in `docs/ROADMAP.md:45`
("~48% retrieval improvement over single-method").

### 5.2 "~49% fewer retrieval failures" — **substantiated, was uncredited**
**Where.** `OVERVIEW.md`, attributed to contextual retrieval.
**Finding.** The figure is exact and real: Anthropic reports combining contextual
embeddings with contextual BM25 reduced top-20 retrieval failure rate by 49%
(5.7% → 2.9%). Two precisions the original wording elided — it is the *combined*
contextual-embeddings-plus-contextual-BM25 number and already assumes hybrid search,
so it does not stack additively on a separate hybrid-search gain; and it excludes
reranking, which Anthropic measures separately at 67%. Since RAGBench enables
reranking by default, the shipped configuration corresponds to the 67% row.
**Action.** Cite
<https://www.anthropic.com/engineering/contextual-retrieval>. Done in `OVERVIEW.md`;
retained here for the record.
**Status.** ✅ Done — 2026-08-01, commit `352fb07` (`OVERVIEW.md:30`, with both
precisions stated). `docs/ROADMAP.md:49` still carries the bare figure uncredited.

### 5.3 "Contextual retrieval takes ~85% of processing time" — **unverified**
**Where.** `CLAUDE.md`, Common Issues.
**Finding.** No measurement exists in the repository or externally. The only real
benchmark ran with contextual retrieval disabled. The claim is architecturally
plausible — one LLM call per chunk — but plausibility is not measurement.
**Action.** Measure it (the per-stage timing log lines already exist) or soften to a
qualitative statement.
**Status.** Partially done — `CLAUDE.md` now says contextual retrieval's per-chunk
LLM calls "dominate ingestion time (unmeasured)" and points here, so the fabricated
85% is gone. `ingest_document()` (`services/rag_server/pipelines/ingestion.py`) now
returns a `timings` dict with `parse_s` / `contextual_s` / `embed_s` for every
document ingested, alongside the Ollama→TEI embedding migration's parse/embed/write
instrumentation — so a real baseline can now actually be captured from those
numbers. It has not been captured yet; this item stays open until it is.

### 5.4 `docs/BENCHMARKS.md` — **substantiated, and narrow**
**Finding.** A real run on a 3-file, 6-chunk corpus, honest about its own limits. It
tested neither hybrid nor contextual retrieval and reported no measurable difference
at that corpus size. It cannot support any claim about either feature.
**Status.** No action required as originally scoped — informational. Separately,
the parse/embed/write instrumentation added in **5.3** means a proper baseline run
(more than 3 files) is now possible without new code; nobody has run one yet.

---

## 6. Operations

| Item | Why it matters | Effort | Status |
|---|---|---|---|
| **No backups for any volume.** Postgres data (which since 2026-08-21 includes the embedding vectors), eval runs, and the Forgejo CI history are all unbacked-up named volumes. | Total data loss on volume removal. `docker compose down -v` is one flag away from destroying everything. | M | Open |
| **No resource limits on any container** in any compose file. | One runaway service can starve the host. | S | Open |
| **No request or correlation IDs** anywhere in logging. | Tracing a single request across webapp → rag-server → task-worker is impossible; debugging relies on timestamp correlation. | M | Open |
| ~~**`EMBEDDING_MODEL` is never set** by any compose file, so `GET /models/info`'s `embedding_model` field always reports `unknown`.~~ | The API misreports the active embedding model, and any consumer relying on it — including run records — gets nothing. | S | ✅ **Resolved**, as part of the Ollama→TEI migration. `services/rag_server/api/routes/health.py`'s `get_models_info()` now reads `models_config.embedding.model` (i.e. `config.yml`, the same source of truth `GET /metrics/models` already used) instead of `os.getenv("EMBEDDING_MODEL", "unknown")`. `/models/info` now reports `Qwen/Qwen3-Embedding-0.6B`. |
| **`RAG_SERVER_AUTH_TOKEN` (non-file variant)** is read as a fallback and set by no compose file. | Dead code path. | S | Open |
| **`pytrec-eval-terrier` (pulled in by `ir-measures`, used for `R`/`RR`/`nDCG`/`P`) publishes no Linux aarch64 wheel** — 31 wheels cover macOS, Linux x86_64, and Windows, but not arm64, so `docker compose build evals` on Apple Silicon/arm64 hosts falls back to the sdist and fails with `gcc: No such file or directory`. | Blocks building the evals image on any arm64 host (OrbStack on Apple Silicon, Graviton). | S | ✅ Done — 2026-08-29. `gcc`/`g++`/`make` added to `services/evals/Dockerfile` before `uv sync`, with a comment naming the reason so it isn't later deleted as unused. Decision was to keep `ir_measures` and add the compiler rather than replace the dependency — recorded so the Dockerfile line isn't later "cleaned up" as unnecessary. |

---

## 7. AWS demo deployment

Limitations of the AWS demo deployment (CloudFormation stack, golden AMI, single
EC2 instance running every service including the self-hosted TEI embedder).
Recorded as accepted trade-offs of a demo deployment, not as defects to fix.

### 7.1 `config.yml` is a read-write bind mount
**What.** `config.yml` is bind-mounted read-write into the container, and the app
writes back to it: `PATCH /settings` (`services/rag_server/api/routes/settings.py:23`)
calls `update_config_file()` (`services/rag_server/infrastructure/config/models_config.py:690`)
so both `rag-server` and the worker pick up the change.
**Why it matters.** Fine on a single instance, where one file and one writer exist.
It blocks horizontal scaling of `rag-server`: multiple replicas writing the same
mounted file race, and there is no mechanism to propagate a write from one
replica's mount to the others'.
**Effort.** L — moving live-toggleable settings out of a mounted file and into a
shared store (e.g. Postgres, SSM Parameter Store) is a real design change.
**Where.** `services/rag_server/api/routes/settings.py`,
`services/rag_server/infrastructure/config/models_config.py`.
**Status.** Open.

### 7.2 No database migrations run
**What.** `alembic.ini` exists (`services/rag_server/alembic.ini`) and
`services/rag_server/infrastructure/database/migrations/versions/` exists, but the
versions directory is empty and nothing in the justfile or any compose file calls
`alembic upgrade`. The schema is created entirely by
`services/postgres/init.sql` on the container's first boot.
**Why it matters.** The AWS demo bakes a golden AMI with the database already
initialized. A schema change against that AMI has no migration path — `init.sql`
only runs once, on an empty volume — so it requires a re-bake rather than a
migration run.
**Effort.** M — would need both an actual migration authoring workflow and a way
to run it against the baked AMI's database.
**Where.** `services/rag_server/alembic.ini`,
`services/rag_server/infrastructure/database/migrations/versions/`,
`services/postgres/init.sql`.
**Status.** Open.

### 7.3 No backups
**What.** Destroying the ephemeral demo CloudFormation stack destroys the EC2
instance and its volumes, with nothing backed up off-instance.
**Why it matters.** The shipped corpus survives teardown because it is baked into
the AMI, but anything ingested *during* a demo — uploaded documents, chat
sessions, eval runs — is lost the moment the stack is torn down.
**Effort.** S — periodic sync of the Postgres volume (or a pre-teardown dump) to
S3 would cover it, but nothing does this today.
**Where.** CloudFormation stack / EC2 instance definition.
**Status.** Open.

### 7.4 Single AZ in practice
**What.** The demo VPC spans 2 AZs so the ALB can be provisioned, but the single
EC2 instance running every service sits in one of them.
**Why it matters.** Correct for a demo — there is exactly one instance to place —
but it is not an HA design: losing that AZ takes down the whole deployment despite
the ALB's multi-AZ footprint implying otherwise.
**Effort.** L — real HA here means multiple app instances and a non-single-instance
Postgres, which is a different architecture, not a config change.
**Where.** CloudFormation stack / VPC definition.
**Status.** Open.

---

## Suggested priority

If picking a handful, these give the most value per unit of effort.

**Done (2026-08-02, commit `e26a4d2`):**

1. ~~**2.1** — the fabricated config snapshot.~~ ✅
2. ~~**4.1** — deleted documents leaving retrievable vectors.~~ ✅ (superseded
   2026-08-21: the second vector store is gone, so the cascade handles it)
3. ~~**3.2** — provider keys with no supported path.~~ ✅
4. ~~**4.2** — the broken CI eval job.~~ ✅ (also **3.3**, which was not on this list)

**Done (2026-08-02, dashboard pass):**

5. ~~**1.1** — starting and cancelling an eval run from the dashboard.~~ ✅ (all of
   section 1 landed in the same pass)

**Done (2026-08-03, evaluation-framework pass):**

6. ~~**2.2** — significance testing in `compare` and the API.~~ ✅ The largest
   improvement to the quality of conclusions users can draw.
7. ~~**2.3**, **2.5**, **2.6**, **2.7**, **2.8**, and all of **2.9**.~~ ✅
   **2.4** is partially done: the same-provider warning landed, ensemble judging
   did not.

**Done (2026-08-03, correctness pass):**

8. ~~**4.3**, **4.4**, **4.5**, **4.6**, **4.7**, **4.8**, **4.9**, **4.10**.~~ ✅
   All of section 4 now closed. The two with the most behavioural weight: **4.5**
   (BM25 failures are now reported at `component_status.bm25` instead of only in
   logs) and **4.8** (eleven citation-extraction tests run again).

9. ~~**3.1** — chunk size and overlap in `config.yml`.~~ ✅ 2026-08-27. The
   documented chunk-size recipe now runs by configuration alone, and the eval
   snapshot records the values the pipeline actually used.

**Still the top of the queue:**

10. **Surface significance in the dashboard.** The API returns it; the analytics UI
    still shows point deltas only, which is where most users will read a comparison.
11. **2.4** — ensemble judging. The same-provider warning landed; pairing judge and
    generator by family is still the default.
