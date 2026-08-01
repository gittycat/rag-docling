# Documentation Overhaul — Work Order

**Status:** Complete
**Owner:** Bernard Duchesne
**Created:** 2026-08-01
**Repo:** `/Users/bernard/dev/code/rag/fulldoc` (RAGBench)

> This file is a **self-contained work order**. It assumes no prior conversation
> context. Everything needed to execute it is either stated here or reachable
> from the repository. Work through the phases in order and tick the checkboxes
> as you go. Update the **Status** line above as phases complete.

---

## 1. Mission

Rebuild this project's documentation into two purpose-built sets, replacing the
current mix of curated dev docs, stale planning documents, and root-level
marketing files.

1. **`docs/internal/`** — the engineering reference. What the system is, how it
   is built, why it was built that way. Audience: developers working on
   RAGBench itself (including AI coding assistants).
2. **`docs/guide/`** — an advanced user guide. Audience: **self-hosting
   operators** who configure and tune the system via `config.yml` + `just` +
   Docker, and **evaluators / RAG researchers** who care about eval methodology
   and statistical validity. Its spine is the tuning loop: *measure a baseline →
   change one thing → re-measure → decide whether the change was worth it.*
3. **`docs/suggestions.md`** — a separate, actionable backlog of improvements
   discovered during the exercise, with emphasis on dashboard gaps.

The guide must genuinely teach an operator how to use evals to decide what works
best **for their own document set**, covering quality, speed, and cost — and how
to quantify the effect of any change they make.

---

## 2. Locked decisions

These were decided before this file was written. Do not relitigate them.

| # | Decision |
|---|---|
| D1 | Existing `docs/dev/` content is **stripped, merged, and rewritten** into `docs/internal/`. `docs/dev/` is removed once its content has been absorbed. |
| D2 | Legacy `docs/*.md` (postmortems, completed plans, benchmark notes) are **mined for content, then moved to `docs/archives/`**. |
| D3 | `docs/ROADMAP.md` and `docs/TODO.md` **stay where they are**. They are forward-looking working documents, not system documentation. Do not archive them. |
| D4 | `README.md` and `OVERVIEW.md` stay at repo root as entry points. They are lightly edited to add pointers to the two new doc sets; their marketing framing is preserved. |
| D5 | `DEVELOPMENT.md` and `FRONT_END.md` are folded into `docs/internal/` and removed from root. |
| D6 | **Verification is static.** Documentation claims are derived by reading code and config. Do not bring up the stack, run evals, or invoke LLMs to verify behaviour. |
| D7 | **Targeted web research only** — limited to specific gaps the codebase leaves undocumented. Quarantined into clearly-marked sections. See §4. |
| D8 | Guide audience is operators + evaluators. Deep code-level extension walkthroughs belong in `docs/internal/`, not the guide. |

---

## 3. Hard constraints

**C1 — Ordering constraint on archival.**
`docs/archives/` is unreadable in the standard sandbox (`Operation not
permitted`). **All content mining from legacy docs must complete in Phase 1
before anything is moved in Phase 6.** Once a file is moved there, its content
is gone for the rest of this work.

**C2 — Citation discipline.**
Every factual claim about system behaviour must trace to code. During
extraction, record `path/to/file.py:LINE`. Citations do not need to survive into
the final prose, but the fact-files backing them must exist and be checkable.

**C3 — No invented measurements.**
Static verification means no measured before/after numbers are available.
Illustrative examples in the tuning chapters must be explicitly labelled as
illustrative. Never present a fabricated benchmark as measured. Existing
performance claims found in current docs (e.g. "~48% better retrieval", "~49%
fewer retrieval failures") must be traced to their source; if the source is an
external paper, cite it as such, and if no source exists, mark the claim as
unverified in `docs/suggestions.md` rather than repeating it.

**C4 — Recommendations are quarantined.**
Anything sourced from external best practice rather than this codebase goes in a
clearly-marked section (e.g. `## Recommendations (not currently implemented)`).
Opinion must never read as implemented behaviour.

**C5 — Cost policy.**
Mechanical work — code extraction, doc auditing, reference-chapter drafting,
fact-checking — is delegated to Sonnet subagents. Reserve the orchestrating
model for TOC design, the judgment-heavy guide chapters (see Phase 4), and final
coherence editing. Subagents write their output to files and return short
summaries; they must not dump large prose into the orchestrator's context.

**C6 — Working directory.**
Intermediate fact-files live in `.docwork/` at repo root so they survive across
sessions. This directory is gitignored and deleted at the end.

---

## 4. Target end state

```
README.md                      kept; adds "Documentation" section linking both sets
OVERVIEW.md                    kept; adds pointers
DEVELOPMENT.md                 REMOVED -> docs/internal/development.md
FRONT_END.md                   REMOVED -> docs/internal/frontend.md
CLAUDE.md                      updated: doc paths point at docs/internal/
.claude/skills/dev-docs/       updated: skill reads docs/internal/INDEX.md

docs/
  internal/                    NEW — engineering reference (~16 files)
  guide/                       NEW — advanced user guide (11 chapters)
  suggestions.md               NEW — actionable backlog
  ROADMAP.md                   unchanged
  TODO.md                      unchanged
  DOCS_OVERHAUL_PLAN.md        this file
  archives/                    legacy docs moved here in Phase 6
  dev/                         REMOVED once absorbed
```

### 4.1 `docs/internal/` file list

| File | Covers |
|---|---|
| `INDEX.md` | Topic table, same format as the current `docs/dev/INDEX.md` (it drives the `dev-docs` skill) |
| `architecture.md` | Services, network isolation, data flow, Docker topology |
| `rag-pipeline.md` | Ingestion: Docling → chunking → contextual retrieval → embedding → Chroma |
| `retrieval.md` | Hybrid BM25 + vector, RRF fusion, cross-encoder reranking |
| `chat-and-memory.md` | Sessions, `condense_plus_context`, chat memory cache + TTL/LRU bounds |
| `eval-framework.md` | Design, metrics, judges, calibration, in-house-vs-third-party rationale |
| `eval-service-api.md` | Eval service REST API (port 8002), job manager, dashboard endpoints |
| `rag-api.md` | RAG server REST API (port 8001) |
| `frontend.md` | SvelteKit app, routes, stores, components (absorbs `FRONT_END.md`) |
| `database.md` | Postgres, pooling, query patterns, `SKIP LOCKED` task queue |
| `configuration-reference.md` | Exhaustive `config.yml` × env vars × Docker secrets × compose overrides |
| `pii-masking.md` | Presidio/spaCy/GLiNER masking, coverage, audit logging |
| `observability.md` | Metrics API, health, cost/latency trackers, logs |
| `testing.md` | Test categories, markers, integration test design |
| `cicd-deployment.md` | Forgejo CI, compose environments, versioning, release flow |
| `development.md` | Prerequisites, local setup, `just`/`make` recipes (absorbs `DEVELOPMENT.md` + `docs/dev/setup.md`) |
| `design-decisions.md` | **New.** The *why*: in-house eval framework, NullPool incident, Docling+LlamaIndex JSON constraint, async postmortem lessons, PyTorch index strategy, no-separate-test-runner |

### 4.2 `docs/guide/` chapter list

| Chapter | Purpose |
|---|---|
| `INDEX.md` | Reading paths: "I want to tune quality" / "…cut cost" / "…verify privacy" |
| `01-what-this-does.md` | System model; one question traced end to end in plain language |
| `02-getting-running.md` | Deploy, ingest documents, first query, confirm health |
| `03-configuration-tour.md` | Every knob that matters, grouped by **what it moves**: quality / speed / cost / privacy. Include defaults and trade-offs |
| `04-evaluation-concepts.md` | What each metric means, how it is computed, and **what it cannot tell you**; judge limitations and failure modes |
| `05-running-evals.md` | Built-in datasets, **building a golden set from your own corpus**, running via CLI / API / dashboard, reading results |
| `06-tuning-workflow.md` | ★ The core loop: baseline → isolate one variable → re-run → compare → decide. Run comparison, config diffing, what counts as a real difference vs noise |
| `07-experiment-cookbook.md` | ★ Concrete recipes: *is reranking worth it? · local vs cloud LLM · chunk size · contextual retrieval on/off · top_k · embedding model swap · reranker on/off* — each with what to change, what to expect, how to measure |
| `08-privacy-and-pii.md` | How masking works, threat model, coverage gaps, how to verify it yourself, its cost in latency and quality |
| `09-reading-the-dashboard.md` | Every panel, what it is computed from, how to interpret it |
| `10-troubleshooting.md` | Operator-facing failure modes and diagnostics |
| `11-limits-and-caveats.md` | ★ Honest account of what these evals can and cannot prove |

★ = judgment-heavy; the orchestrating model writes these personally (C5).

---

## 5. Repository inventory (as of 2026-08-01)

Provided so a fresh session can orient without re-scanning.

**Services** (`services/`): `rag_server`, `evals`, `webapp`, `postgres`, `caddy`.
149 Python files, 39 Svelte/TS files.

**`services/rag_server/`**: `api/routes`, `app/` (anthropic_client, settings),
`core/` (config, logging), `infrastructure/` (auth, config, database, llm, pii,
search, tasks), `pipelines/` (ingestion.py, inference.py), `schemas/`,
`services/` (cost_tracker, latency_tracker, metrics, session, session_titles),
`scripts/benchmark_pipeline.py`, 23 test modules.

**`services/evals/`**: `api/` (app, dashboard, job_manager, routes, schemas),
`evals/` (runner, cli, calibration, config, export), `evals/datasets/` (golden,
hotpotqa, msmarco, qasper, ragbench, squad_v2, registry),
`evals/judges/llm_judge.py`, `evals/metrics/` (abstention, citation, generation,
performance, retrieval, text_match), `evals/schemas/`, `infrastructure/`.

**Eval CLI subcommands** (`services/evals/evals/cli.py`): `eval`, `calibrate`,
`cache {clear,status}`, `stats`, `datasets`, `export`, `compare`.

**`services/webapp/src/`**: routes `analytics`, `chat`, `documents`, `settings`,
`upload`. Components: `ChatSidebar`, `ConfigDiff`, `ExportButton`,
`RunSelector`, `ThemeToggle`, and `analytics/` (`AnalyticsTabs`,
`ConfigContext`, `ExperimentsTab`, `HealthBadge`, `HealthTab`, `InfoTip`,
`LatencyPanel`, `MetricBreakdown`, `MetricSparkline`, `StatPanel`,
`SystemHealthTab`).

**`config.yml`** (~13KB) top-level sections: `models`, `active`, `eval`,
`reranker`, `retrieval`, `chromadb`, `database`, `chat_memory`, `prompts`, `pii`.

**Compose files**: `docker-compose.yml`, `.bench.yml`, `.ci.yml`, `.cloud.yml`,
`.server.yml`.

**`justfile` recipes**: `build`, `preflight`, `up`, `down`, `logs`, `setup`,
`init`, `clean`, `test-unit`, `test-integration`, `test-integration-full`,
`test-eval`, `test-eval-full`, `eval`, `eval-datasets`, `eval-calibrate`,
`eval-compare`, `show-config`, `show-config-full`, `deploy`, `deploy-down`,
`release`. (`Makefile` is a thinner parallel set.)

**Current documentation** (to be mined, then replaced/archived):

| File | Lines | Disposition |
|---|---|---|
| `docs/dev/INDEX.md` | 15 | absorb → `docs/internal/INDEX.md` |
| `docs/dev/architecture.md` | 156 | absorb |
| `docs/dev/eval-framework.md` | 200 | absorb |
| `docs/dev/pii-masking.md` | 174 | absorb |
| `docs/dev/cicd-deployment.md` | 97 | absorb |
| `docs/dev/setup.md` | 90 | absorb → `development.md` |
| `docs/dev/database.md` | 83 | absorb |
| `docs/dev/testing.md` | 79 | absorb |
| `docs/dev/rag-api.md` | 70 | absorb |
| `docs/dev/observability.md` | 67 | absorb |
| `docs/dev/tech-stack.md` | 49 | absorb (fold into architecture/development) |
| `docs/dev/configuration.md` | 34 | absorb → `configuration-reference.md` |
| `docs/DEMO_POLISH_PLAN.md` | 553 | mine → archive |
| `docs/ROADMAP.md` | 482 | **leave in place** (D3) |
| `docs/LOGGING_IMPLEMENTATION_PLAN.md` | 395 | mine → archive |
| `docs/ASYNC_POSTMORTEM.md` | 360 | mine → `design-decisions.md` → archive |
| `docs/EVALS_README.md` | 125 | mine → archive |
| `docs/evals_articles.md` | 104 | mine (reference links) → archive |
| `docs/BENCHMARKS.md` | 53 | mine (verify claims, C3) → archive |
| `docs/TODO.md` | 10 | **leave in place** (D3) |
| `README.md` | — | keep, light edit |
| `OVERVIEW.md` | — | keep, light edit |
| `DEVELOPMENT.md` | — | absorb → `docs/internal/development.md` |
| `FRONT_END.md` | — | absorb → `docs/internal/frontend.md` |

---

## 6. Phases and tasks

### Phase 0 — Setup

- [x] **T0.1** Create `.docwork/` at repo root for intermediate fact-files.
- [x] **T0.2** Add `.docwork/` to `.gitignore`.
- [x] **T0.3** Confirm current branch is appropriate for this work (create a
      `docs-overhaul` branch if currently on `main`).

---

### Phase 1 — Extraction (parallel, delegated)

Launch the following as **parallel Sonnet subagents**. Each is read-only, writes
one fact-file to `.docwork/`, and returns only a short summary (C5). Each
fact-file must carry `file:line` citations (C2).

- [x] **T1.1 — Ingestion pipeline** → `.docwork/facts-ingestion.md`
      Cover `services/rag_server/pipelines/ingestion.py`,
      `infrastructure/search/`, Docling usage and the JSON export-type
      constraint, chunking strategy and parameters, contextual retrieval (what
      the LLM is asked, per-chunk cost), embedding generation, ChromaDB
      collection layout, the async task worker and its `SKIP LOCKED` claim
      pattern, progress tracking, supported file formats.

- [x] **T1.2 — Query path** → `.docwork/facts-retrieval.md`
      Cover `pipelines/inference.py`, BM25 (pg_textsearch) and vector retrieval,
      RRF fusion including the exact weighting/`k` constant used, the
      cross-encoder reranker (model, when it loads, cost), `top_k` and related
      knobs, prompt templates from `config.yml`, chat memory including the TTL +
      LRU bounds, `condense_plus_context` rewriting, citation generation.

- [x] **T1.3 — Eval system** → `.docwork/facts-evals.md`
      Cover every dataset adapter and what each dataset actually tests; every
      metric in `evals/metrics/` with its precise computation; the LLM judge
      (prompt, model, scoring weights, failure handling — note that failed judge
      calls are excluded from averages rather than scored 0.0); calibration;
      the runner; the CLI subcommands with **all** flags; export formats;
      `compare`; how results are persisted.

- [x] **T1.4 — Webapp & dashboard** → `.docwork/facts-webapp.md`
      Cover each route and each `analytics/` component: what it renders and
      which API field feeds it. **Critical deliverable:** an explicit diff of
      *data the eval/metrics APIs expose* vs *data the dashboard actually
      displays*. That gap list drives `docs/suggestions.md`. Also note UX rough
      edges: unclear labels, missing empty/error states, absent comparison
      affordances.

- [x] **T1.5 — Configuration surface** → `.docwork/facts-config.md`
      An exhaustive table of every `config.yml` key: path, type, default,
      what it affects, and where it is consumed in code. Add environment
      variables, Docker secrets, and per-compose-file overrides. Flag any key
      that is defined but never read, and any hardcoded value that arguably
      should be configurable.

- [x] **T1.6 — Ops, testing, CI** → `.docwork/facts-ops.md`
      Cover all five compose files and how they differ; `justfile` and
      `Makefile` recipes; the Forgejo workflow; test categories and markers;
      health/metrics endpoints; cost and latency trackers; PII masking
      configuration, coverage surface, and audit logging; secrets handling.

- [x] **T1.7 — Legacy documentation audit** → `.docwork/audit-existing-docs.md`
      Read **all** files listed in §5's documentation table, including
      `README.md`, `OVERVIEW.md`, `DEVELOPMENT.md`, `FRONT_END.md`, `CLAUDE.md`.
      Classify every substantive section as: **reusable** / **stale** /
      **contradicted by code** / **duplicated elsewhere**. The
      *contradicted-by-code* list is the single highest-value output of this
      phase — be rigorous. Also extract every performance claim and every
      external reference link for later verification under C3.

**Phase 1 gate:**
- [x] **T1.8** All seven fact-files exist and are non-trivial. Skim each for
      obvious gaps; re-task any agent whose output is thin. **Nothing may be
      archived or deleted until this gate passes (C1).**

---

### Phase 2 — Design

- [x] **T2.1** Read all seven fact-files. Reconcile contradictions between them.
- [x] **T2.2** Confirm or adjust the file/chapter lists in §4.1 and §4.2 against
      what the code actually contains. Record any deviation in this file.
- [x] **T2.3** Produce `.docwork/gap-list.md`: specific questions the codebase
      does **not** answer and that warrant external research (Phase 3).
- [x] **T2.4** Produce `.docwork/outline.md`: per-file section headings for both
      doc sets, so drafting agents have a fixed skeleton to fill.

---

### Phase 3 — Targeted research

- [x] **T3.1** Research only the items in `.docwork/gap-list.md`. Expected
      territory: RRF weighting conventions, chunk-size trade-offs, cross-encoder
      reranker selection, LLM-judge calibration and bias practice, golden-set
      construction and sizing, statistical significance for small eval sets,
      Presidio tuning and known recall limits. Output →
      `.docwork/research.md`, with sources.
- [x] **T3.2** Verify the performance claims extracted in T1.7 against their
      sources. Record verdicts (`substantiated` / `external source` /
      `unverified`) in `.docwork/research.md`.

---

### Phase 4 — Drafting

**Delegated to Sonnet subagents** (reference-shaped, fed the relevant fact-file
and outline; each writes its file directly):

- [x] **T4.1** `docs/internal/configuration-reference.md`
- [x] **T4.2** `docs/internal/rag-api.md` and `docs/internal/eval-service-api.md`
- [x] **T4.3** `docs/internal/testing.md` and `docs/internal/cicd-deployment.md`
- [x] **T4.4** `docs/internal/database.md` and `docs/internal/observability.md`
- [x] **T4.5** `docs/internal/frontend.md` and `docs/internal/development.md`
- [x] **T4.6** `docs/internal/rag-pipeline.md`, `retrieval.md`, `chat-and-memory.md`
- [x] **T4.7** `docs/internal/architecture.md`, `pii-masking.md`, `eval-framework.md`
- [x] **T4.8** `docs/internal/design-decisions.md`
- [x] **T4.9** `docs/guide/02-getting-running.md`, `09-reading-the-dashboard.md`,
      `10-troubleshooting.md`

**Written by the orchestrating model** (judgment is the product — C5):

- [x] **T4.10** `docs/guide/01-what-this-does.md`
- [x] **T4.11** `docs/guide/03-configuration-tour.md`
- [x] **T4.12** `docs/guide/04-evaluation-concepts.md`
- [x] **T4.13** `docs/guide/05-running-evals.md`
- [x] **T4.14** ★ `docs/guide/06-tuning-workflow.md`
- [x] **T4.15** ★ `docs/guide/07-experiment-cookbook.md`
- [x] **T4.16** `docs/guide/08-privacy-and-pii.md`
- [x] **T4.17** ★ `docs/guide/11-limits-and-caveats.md`

---

### Phase 5 — Assembly

- [x] **T5.1** Write `docs/internal/INDEX.md` in the existing topic-table format
      (the `dev-docs` skill depends on this shape).
- [x] **T5.2** Write `docs/guide/INDEX.md` with task-oriented reading paths.
- [x] **T5.3** Write `docs/suggestions.md`. Sources: the dashboard gap list
      (T1.4), unread/hardcoded config values (T1.5), eval-framework gaps (T1.3),
      unverified claims (T3.2), and any UX friction observed. Each entry:
      *what · why it matters · rough effort · where it lives*. Group by area, with
      dashboard suggestions first.
- [x] **T5.4** Cross-link both doc sets: guide chapters link to internal docs for
      depth; internal docs link back for operator-facing procedure.
- [x] **T5.5** Add a "Documentation" section to `README.md` and `OVERVIEW.md`
      pointing at both sets. Preserve their existing framing (D4).
- [x] **T5.6** Update `CLAUDE.md` so documentation paths reference
      `docs/internal/INDEX.md`.
- [x] **T5.7** Update `.claude/skills/dev-docs/` to read from `docs/internal/`.

---

### Phase 6 — Cleanup (destructive — only after Phase 5 completes)

- [x] **T6.1** Verify every file listed as "absorb" in §5 has its content
      represented in `docs/internal/`. Spot-check, do not assume.
- [x] **T6.2** Create `docs/archives/` if absent. Move: `DEMO_POLISH_PLAN.md`,
      `LOGGING_IMPLEMENTATION_PLAN.md`, `ASYNC_POSTMORTEM.md`,
      `EVALS_README.md`, `evals_articles.md`, `BENCHMARKS.md`.
      **Do not move `ROADMAP.md` or `TODO.md` (D3).**
- [x] **T6.3** Remove `docs/dev/` once fully absorbed.
- [x] **T6.4** Remove root `DEVELOPMENT.md` and `FRONT_END.md`.
- [x] **T6.5** Grep the whole repo for references to removed paths
      (`docs/dev/`, `DEVELOPMENT.md`, `FRONT_END.md`) and fix every hit —
      including `CLAUDE.md`, `AGENTS.md` (symlink to `CLAUDE.md`), skill files,
      CI config, and the docs themselves.

---

### Phase 7 — Verification

- [x] **T7.1** Launch a **fresh Sonnet subagent that has not seen the drafts**.
      Task: verify every factual claim in `docs/internal/` and `docs/guide/`
      against the codebase. Report discrepancies with file references. Do not
      let it edit.
- [x] **T7.2** Fix all confirmed discrepancies.
- [x] **T7.3** Check every internal markdown link resolves.
- [x] **T7.4** Confirm no fabricated measurements survive (C3) and every
      external recommendation sits in a marked section (C4).
- [x] **T7.5** Read `docs/guide/06-tuning-workflow.md` and
      `07-experiment-cookbook.md` end to end as if you were an operator. Can you
      actually execute the loop from the text alone, with real commands and real
      config keys? If not, fix.
- [x] **T7.6** Delete `.docwork/`.
- [x] **T7.7** Update the **Status** line at the top of this file to `Complete`.

---

## 7. Acceptance criteria

The work is done when all of the following hold:

1. `docs/internal/` and `docs/guide/` exist and are populated per §4.
2. `docs/suggestions.md` exists with concrete, actionable dashboard items.
3. No documentation file makes a claim contradicted by the code.
4. No fabricated benchmark numbers appear anywhere.
5. External recommendations are visibly separated from implemented behaviour.
6. An operator can read `docs/guide/` alone and run a full tune-and-measure
   cycle — including building a golden set from their own documents.
7. `docs/dev/`, root `DEVELOPMENT.md`, and root `FRONT_END.md` are gone, with no
   dangling references anywhere in the repo.
8. `docs/ROADMAP.md` and `docs/TODO.md` are untouched.
9. The `dev-docs` skill and `CLAUDE.md` point at the new locations and work.

---

## 8. Notes and deviations

> Record decisions, surprises, and deviations from this plan here as work
> proceeds, so a later session can pick up mid-flight.

### Phase 1–2 findings that change the plan's assumptions

**N1 — Eval results are not in Postgres.** T1.3 assumed database tables. They are
flat JSON files under `data/eval_runs/`, indexed by an in-memory dict rebuilt on
process start. `internal/database.md` must say so explicitly; `eval-framework.md`
documents the JSON layout instead of a schema.

**N2 — `docs/archives/` already existed** and is already gitignored (`/archives`
in `.gitignore`). T6.2's "create if absent" is a no-op; the move still applies.

**N3 — The two headline performance claims are unsubstantiated in-repo.**
`OVERVIEW.md:29-30` ("~48% better retrieval", "~49% fewer retrieval failures").
`docs/BENCHMARKS.md`'s only real run did not test either feature and reported no
measurable difference. Handled under C3 via T3.2; resolution recorded below.

**N4 — Structural findings that are defects, not doc gaps.** Recorded here
because they are the substance of `docs/suggestions.md`:
- `ConfigSnapshot` hardcodes `retrieval_top_k`, `hybrid_search_enabled`,
  `contextual_retrieval_enabled` (`evals/runner.py:590-602`), so every saved run
  misreports the config it ran under. This undermines run comparison directly and
  is called out in `guide/06-tuning-workflow.md` as a confound.
- The Makefile and the Forgejo CI eval job both reference
  `services/rag_server/tests/test_rag_eval.py`, which no longer exists.
- `GOOGLE_API_KEY` / `DEEPSEEK_API_KEY` / `MOONSHOT_API_KEY` are read by code and
  offered in `config.yml` but declared as secrets in no compose file.
- Six grep-confirmed dead `config.yml` keys.
- Document deletion does not remove the corresponding ChromaDB vectors.
- `compare` performs no significance testing of any kind.

**N5 — File and chapter lists confirmed unchanged.** §4.1 (17 files) and §4.2
(12 chapters) both survive contact with the code. No additions or removals.

**N5b — `docs/ROADMAP.md` link targets repaired.** D3 and acceptance criterion 8
say ROADMAP stays untouched; criterion 7 says no dangling references may remain.
Moving files in Phase 6 broke two links *inside* ROADMAP (`dev/pii-masking.md`
and `LOGGING_IMPLEMENTATION_PLAN.md`). Only those two link targets were
repointed — no content, structure, or wording was changed. Repairing collateral
damage from this work is treated as in scope; rewriting ROADMAP is not.

**N5c — `docker-compose.cloud.yml` comment corrected.** It pointed at
`DEVELOPMENT.md` (removed) and at a `just build-push` recipe that has never
existed. Comment now points at `docs/internal/cicd-deployment.md` and states the
step is manual.

**N6 — Guide chapter 07 caveat.** The chunk-size recipe cannot be executed by
configuration alone: `chunk_size`/`chunk_overlap` are hardcoded at
`services/rag_server/core/config.py:105-106`. The recipe states this rather than
implying a `config.yml` edit will work.
