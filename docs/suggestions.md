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
on **2026-08-02** (through commit `e26a4d2`).

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
**Status.** Open.

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
**Status.** Open.

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
**Status.** Open.

### 1.4 Per-sample distributions are never surfaced
**What.** `details.individual_scores` carries per-question scores. Nothing displays
them.
**Why it matters.** An average of 0.7 from every question scoring 0.7 and an average
of 0.7 from half scoring 1.0 and half scoring 0.4 are different systems needing
different fixes. A distribution view would make that visible immediately.
**Effort.** M.
**Where.** As above.
**Status.** Open.

### 1.5 Config diff ignores all but two selected runs
**What.** The comparison UI lets a user select up to four runs; `ConfigDiff` only
ever compares baseline-A against run-B.
**Why it matters.** Silently ignoring selected input is worse than not offering it —
the user believes they are comparing four runs.
**Effort.** S to disable the extra selection, M to support n-way diffing.
**Where.** `services/webapp/src/lib/components/ConfigDiff.svelte`.
**Status.** Open. (The related snapshot defect **2.1** is fixed, including the
`diff.ts` half of it, but `ConfigDiff` still compares only two runs.)

> **Note:** config diffing is currently unreliable for a deeper reason — see
> **2.1**. Fixing the UI without fixing the snapshot produces a confident diff of
> fabricated values.

### 1.6 Endpoints the webapp never calls
**What.** `/models/info` (per-model cost rates) and `/config` (max upload size) are
implemented and unused.
**Why it matters.** Cost-per-token rates would let the dashboard show cost context
alongside results. The upload-size limit is currently a number the user discovers
by exceeding it.
**Effort.** S each.
**Where.** `services/webapp/src/lib/api/`.
**Status.** Open.

### 1.7 Chat citations show a filename and nothing else
**What.** Each source carries `score`, `full_text`, and `path`. The chat UI renders
a filename badge only.
**Why it matters.** Verifying a grounded answer means reading the passage it came
from. Users currently have to trust the citation or go and find the document
themselves — which undercuts the product's central claim.
**Effort.** M — an expandable source panel with the retrieval score.
**Where.** `services/webapp/src/routes/chat/`.
**Status.** Open.

### 1.8 Settings load failures are invisible
**What.** A failed settings fetch is caught and passed to `console.error`. No error
state renders.
**Why it matters.** The page appears to work and shows stale or empty values. Silent
failure in a settings screen leads directly to users believing they changed
something they did not.
**Effort.** S.
**Where.** `services/webapp/src/routes/settings/`.
**Status.** Open.

### 1.9 Documents table caps at 15 rows client-side
**What.** The full document list is fetched and then truncated to 15 rows in the
browser. There is no pagination.
**Why it matters.** Documents beyond the first 15 are unreachable in the UI, and the
fetch cost grows with the corpus while the display does not.
**Effort.** M for real server-side pagination, S for client-side paging over the
fetched list.
**Where.** `services/webapp/src/routes/documents/`.
**Status.** Open.

### 1.10 Bulk delete has no partial-failure handling
**What.** Deleting several documents at once does not report which deletions
succeeded when some fail.
**Why it matters.** The user is left without an accurate picture of system state
after a partial failure.
**Effort.** S.
**Where.** `services/webapp/src/routes/documents/`.
**Status.** Open.

### 1.11 Upload progress is simulated before task IDs exist
**What.** Progress is animated with a timer until real task IDs arrive, then
switches to real polling.
**Why it matters.** Fabricated progress is actively misleading during the phase
where an upload is most likely to fail. A stalled upload shows a healthy bar.
**Effort.** S — an indeterminate state until real progress is available.
**Where.** `services/webapp/src/routes/upload/`.
**Status.** Open.

### 1.12 Status is conveyed by colour alone
**What.** Outside the `HealthBadge` component, status indicators are coloured dots
with no text or shape distinction.
**Why it matters.** Accessibility. Red and green dots are indistinguishable to a
substantial fraction of users.
**Effort.** S.
**Where.** `services/webapp/src/lib/components/analytics/`.
**Status.** Open.

### 1.13 Dead client code
**What.** `fetchEvalDatasets` is defined and never called; `clearChatSession` is
imported and unused.
**Effort.** S.
**Where.** `services/webapp/src/lib/`.
**Status.** Open — both still present (`api/evals.ts:181`, `api.ts:477` imported at
`routes/chat/+page.svelte:8`).

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
**Status.** Open.

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
**Status.** Open.

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
**Status.** Open. Not to be confused with the PII judge gate added in `2131914`
(2026-08-01): `validate_privacy_posture` rejects a non-local judge provider when
`pii.enabled` is true, which is a data-egress check, not the self-preference
warning asked for here. Nothing compares the `active.inference` and `active.eval`
providers.

### 2.5 Calibration covers half the judge prompts
**What.** `calibrate` checks faithfulness against adherence labels and context
relevance against relevance labels. `answer_correctness` and `answer_relevancy` are
never checked against ground truth.
**Why it matters.** Two metrics users rely on have no evidence of agreeing with a
human on anything.
**Effort.** M.
**Where.** `services/evals/evals/calibration.py`.
**Status.** Open.

### 2.6 The richer exporters are unreachable
**What.** `export_for_review`, `export_scorecard`, and `export_run_report` are
implemented and called from nowhere. The CLI's `export` subcommand has its own
simpler inline logic.
**Why it matters.** `export_for_review` produces per-question CSV and Markdown with
blank reviewer columns — a human-review workflow that would directly mitigate 2.4,
already written and unusable.
**Effort.** S — wire them to CLI flags.
**Where.** `services/evals/evals/export.py`, `services/evals/evals/cli.py`.
**Status.** Open — still exported from `evals/__init__.py` and called by nothing.
(`export.py` was touched by `e26a4d2`, but only for the 2.1 "Disabled" bug.)

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
**Status.** Open.

### 2.8 Stale artifacts from the previous framework
**What.** `evals/data/golden_baseline.json` and old run files reference metrics
(`contextual_precision`, `hallucination`) that no longer exist. Nothing reads them.
**Why it matters.** Anyone browsing `data/` concludes those metrics exist.
**Effort.** S — delete.
**Where.** `services/evals/evals/data/`.
**Status.** Open — `golden_baseline.json` is still there.

### 2.9 Smaller items
| Item | Effort | Where | Status |
|---|---|---|---|
| No caching of query or judge responses — re-running an identical config repeats all work | M | `runner.py` | Open |
| `cleanup_on_failure` is declared and never read | S | `config.py` | Open |
| One active job process-wide; a second request gets a 409 with no queue | M | `api/job_manager.py` | Open |
| The `qasper` loader is documented as broken with `datasets>=4.0` | M | `datasets/qasper.py` | Open |
| Eval runs are flat JSON with no backup; deleting a file loses the run permanently | M | `runner.py` | Open |
| `data/calibration/` is not bind-mounted, so calibration results are lost whenever the container is recreated — unlike `data/eval_runs/`, which is mounted | S | `docker-compose.yml` | Open |
| `evals/README.md` is stale — says to run from `services/rag_server/`, names Claude Sonnet as the judge default when `active.eval` is an OpenAI model | S | `evals/evals/README.md` | Open |

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
**Status.** Open — still hardcoded at `core/config.py:105`.

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

### 4.1 ★ Deleting a document leaves its vectors in ChromaDB
**What.** Document deletion removes the Postgres rows and the stored file. Nothing
removes the corresponding ChromaDB embeddings.
**Why it matters.** Orphaned vectors accumulate indefinitely and remain retrievable,
so deleted content can still surface in answers. For a system whose selling point is
data control, "delete does not delete" is a serious defect — and a plausible
compliance problem for anyone relying on deletion.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/database/documents.py`,
`services/rag_server/infrastructure/search/vector_store.py`.
**Status.** ✅ Done — 2026-08-02, commit `e26a4d2`. Pre-existing orphans still need
a manual `just reconcile-vectors-apply`.

**✅ FIXED (2026-08-02).** Vectors are keyed on the `document_id` metadata field
written at `pipelines/ingestion.py:459` — which is also exactly what llama-index's
`ChromaVectorStore.delete(ref_doc_id)` filters on (`collection.delete(where={"document_id": ...})`,
verified in the installed package), so no ingestion change was needed. A new
`services/document_service.py` is the single entry point used by both call sites
(the HTTP route and the worker's pre-retry reset — the latter now also cleans up
vectors a *failed* ingestion left behind, the same bug in another guise).

**Ordering:** vectors first, then the Postgres row. If ChromaDB is unreachable the
call raises before Postgres is touched, so the document stays visible and the delete
is retryable, and the route returns 500 instead of "deleted successfully". The
accepted tradeoff is that a Postgres failure after a successful vector delete leaves
a listed document with no vectors — a silent dead entry, far less bad than a phantom
retrievable one.

**Pre-existing orphans** (anything deleted before this shipped) are not swept
automatically: run `just reconcile-vectors` to see what would be deleted, then
`just reconcile-vectors-apply`. Covered by `services/rag_server/tests/test_document_deletion.py`.

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
**Status.** Open.

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
**Status.** Open — the failing test was skipped on 2026-08-02 (`e26a4d2`) so CI is
honest; the dead function and the wrong assertion are untouched. See the note at
the end of this section.

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
**Where.** `services/rag_server/infrastructure/search/bm25_retriever.py`.
**Status.** Open.

### 4.6 The startup banner names the wrong technologies
**What.** `services/rag_server/main.py` logs "pg_search BM25 + pgvector". The actual
stack is `pg_textsearch` and ChromaDB; `pgvector` is a listed but unused dependency.
**Effort.** S.
**Status.** Open — `main.py:138` still logs "pg_search BM25 + pgvector".

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
**Status.** Open — both wrong statements survive (`config.yml:299`,
`models_config.py:429-431`).

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
**Status.** Open — recorded and skipped on 2026-08-02 (`e26a4d2`); the eleven tests
have still not been moved and still do not run.

### 4.9 Importing the task worker performs live network I/O
**What.** Importing `services/rag_server/infrastructure/tasks/task_worker.py`
triggers a real `httpx.get()` Ollama reachability check at module scope. With no
Ollama running this doesn't just fail a test — it crashes the whole pytest
collection with `INTERNALERROR`/`SystemExit`, taking the entire rag-server suite
with it. `config.yml`'s active embedding is `ollama` at `host.docker.internal:11434`,
so a CI runner hits this too.
**Why it matters.** Import-time side effects that reach the network make a module
untestable and can take down an unrelated suite. Worked around at the test level
(mocking `core.config.check_ollama_reachable`); the import-time call itself is
untouched.
**Fix.** Make the reachability check lazy, at first use rather than at import.
**Effort.** S.
**Where.** `services/rag_server/infrastructure/tasks/task_worker.py`,
`services/rag_server/core/config.py`.
**Status.** Partially done — worked around at the test level on 2026-08-02
(`e26a4d2`, `tests/conftest.py`). The import-time network call itself is unchanged,
so the fix (make the check lazy) is still open.

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
**Status.** Open — still defined at `schemas/metrics.py:159`, still unconstructed.
The 2.1 fix harvested part of its shape (`rrf_k`, reranker `top_n`) into the evals
snapshot's `additional` field but did not delete or adopt this model.

> **Note on 4.4.** `test_pgsearch_retriever_uses_bm25_search_for_raw_user_queries`
> was failing on an unmodified tree (confirmed against a clean worktree at `HEAD`) —
> the live retriever emits `to_bm25query`, the test asserts `bm25_search(`, exactly
> as **4.4** describes. It is now `@pytest.mark.skip`-ped with a reason citing 4.4,
> so the suite is green without the defect being papered over. The underlying fix —
> delete the unused `search_chunks_bm25` and correct the test — is still open.

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
85% is gone. The measurement has not been taken.

### 5.4 `docs/BENCHMARKS.md` — **substantiated, and narrow**
**Finding.** A real run on a 3-file, 6-chunk corpus, honest about its own limits. It
tested neither hybrid nor contextual retrieval and reported no measurable difference
at that corpus size. It cannot support any claim about either feature.
**Status.** No action required — informational.

---

## 6. Operations

| Item | Why it matters | Effort | Status |
|---|---|---|---|
| **No backups for any volume.** Postgres data, ChromaDB vectors, eval runs, and the Forgejo CI history are all unbacked-up named volumes. | Total data loss on volume removal. `docker compose down -v` is one flag away from destroying everything. | M | Open |
| **No resource limits on any container** in any compose file. | One runaway service can starve the host. | S | Open |
| **No request or correlation IDs** anywhere in logging. | Tracing a single request across webapp → rag-server → task-worker is impossible; debugging relies on timestamp correlation. | M | Open |
| **`EMBEDDING_MODEL` is never set** by any compose file, so `/models/info` always reports `unknown`. | The API misreports the active embedding model, and any consumer relying on it — including run records — gets nothing. | S | Open |
| **`RAG_SERVER_AUTH_TOKEN` (non-file variant)** is read as a fallback and set by no compose file. | Dead code path. | S | Open |

---

## Suggested priority

If picking a handful, these give the most value per unit of effort.

**Done (2026-08-02, commit `e26a4d2`):**

1. ~~**2.1** — the fabricated config snapshot.~~ ✅
2. ~~**4.1** — deleted documents leaving retrievable vectors.~~ ✅
3. ~~**3.2** — provider keys with no supported path.~~ ✅
4. ~~**4.2** — the broken CI eval job.~~ ✅ (also **3.3**, which was not on this list)

**Still the top of the queue:**

5. **1.1** — starting an eval run from the dashboard. The largest reachable gap
   between capability and usability.
6. **2.2** — bootstrap confidence intervals in `compare`. The largest improvement to
   the quality of conclusions users can draw.
7. **4.8** — the eleven skipped citation-extraction tests. S, and it restores
   coverage of what the citation metrics depend on; **4.4** is the same shape.
8. **3.1** — chunk size and overlap in `config.yml`. S, and it is the one documented
   tuning recipe that cannot be run without a rebuild.
