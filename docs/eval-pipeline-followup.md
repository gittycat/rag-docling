# Follow-up plan: close out the eval-pipeline remediation

**Audience.** One implementing agent (Sonnet, high effort) starting from a clean
context. Read this file and `docs/eval-pipeline-remediation.md` (the parent plan)
before touching anything.

**Status going in.** The parent plan's tracks A–G are implemented. Both unit
suites are green on the current working tree:

- `cd services/evals && uv run pytest tests/ -q` → **469 passed, 23 skipped**
- `cd services/rag_server && .venv/bin/pytest tests/ --ignore=tests/integration -q` → **214 passed, 2 skipped, 1 xfailed**

Baselines before the remediation were 413 and 198, so ~72 tests are new. Nothing
is committed: 26 modified files and 4 new ones sit uncommitted on `main`.

**The one thing to internalise.** The parent plan's warning still binds, and it
already caught the previous agent once. A fault-localization test was written
whose fixture used gold `chunk_id`s that matched the retrieved ids — it passed
against the *unfixed* tree and therefore proved nothing. It only became a real
test once the fixture used source-coordinate evidence. **Before claiming any new
test proves a fix, run it against the pre-fix code and paste the failure.** Use a
detached worktree for this:

```bash
git worktree add /tmp/base-hd HEAD --detach   # HEAD = eef6b63, pre-remediation
# copy the test in, run it, confirm it FAILS, then remove the worktree
git worktree remove /tmp/base-hd --force
```

---

## Decisions already made — do not relitigate

| Decision | Ruling |
|---|---|
| Ground-truth resolution | Relevant-set resolves against the **full current chunk catalog**, never the ranking being scored. Absent/empty catalog → `value=None`, note `"chunk catalog unavailable"`, `details["catalog_unavailable"]=True`. |
| Source fidelity | **Ingest real source files.** Locator `document_hash` = sha256 of the file's bytes = `documents.file_hash`. |
| Attribution thresholds | **0.5**, matching `calibration.py:175`'s `judged >= 0.5`. Not 1.0 — an exact bar was the original defect. |
| `pytrec-eval-terrier` / gcc | **Keep `ir_measures`; add the compiler.** (Item 1 below.) User's call, already made. |

---

## Invariants — still binding

1. **`None` is not `0.0`**, and `0.0` is not `None`. No data → `None`. Defined and zero → `0.0`.
2. **Judge-free stays judge-free.** No new LLM calls in retrieval/attribution code.
3. **Do not change pipeline behaviour.** No change to `rrf_k`, `top_k`, chunking defaults, scoring weights, prompts, or the embedding model. These are measurement fixes.
4. **Every new or renamed metric registers** in `METRIC_GROUPS` and declares `requires_judge` / `requires_gold`.
5. **House style** (`CLAUDE.md`): module-level functions over classes; query builders or explicit SQL, no ORM; `uv` for Python; no docstrings on private helpers.
6. **Privacy gate is load-bearing.** Never bypass `enforce_judge_boundary()`.
7. **The live Postgres volume must not be destroyed.** `init.sql` has already been applied additively to the running database (it is entirely `CREATE ... IF NOT EXISTS`) and grants re-issued to the `rachel` role. **Do not run `docker compose down -v`.**

---

## Item 1 — evals image cannot build on arm64

**Decided: add the compiler.**

### The defect

`docker compose build evals` fails:

```
× Failed to build `pytrec-eval-terrier==0.5.10`
  ╰─▶ error: [Errno 2] No such file or directory: 'gcc'
```

Root cause is **not** that the package always needs a compiler. `pytrec-eval-terrier`
0.5.10 publishes 31 wheels — macOS universal2, Linux **x86_64** manylinux/musllinux,
Windows — and **zero Linux aarch64**. This machine builds arm64 (OrbStack on Apple
Silicon), so uv falls back to the sdist and needs a toolchain. The same image
builds fine on an x86_64 host, which is why this was never hit before.

`pytrec-eval-terrier` arrives via `ir-measures>=0.4.3` (`services/evals/pyproject.toml:25`),
which `services/evals/evals/metrics/retrieval.py:11-12` uses for `R`, `RR`, `nDCG`, `P`.

### Build

1. Add `gcc`, `g++` (and `make` if the build needs it) to `services/evals/Dockerfile`
   before `uv sync --frozen`, mirroring how `services/rag_server/Dockerfile` already
   handles pystemmer. Use a single `apt-get update && apt-get install -y --no-install-recommends ... && rm -rf /var/lib/apt/lists/*` layer.
2. Add a short comment naming the reason (no aarch64 wheel for `pytrec-eval-terrier`,
   pulled in by `ir-measures`) so the next person does not delete it as cruft.
3. Consider dropping the build tools in a later stage if the Dockerfile is
   multi-stage; do **not** restructure it into multi-stage if it is not already.

### Verify

- `docker compose build evals` succeeds on arm64.
- `docker compose run --rm evals python -c "import ir_measures; print(ir_measures.parse_measure('nDCG@10'))"` works.
- Do **not** rebuild `rag-server`/`task-worker`; they are already built and running with current code.

---

## Item 2 — attribution thresholds are declared but not wired (HALF DONE)

### Exact current state — read carefully

Already done by the previous agent:

- `DEFAULT_CORRECTNESS_THRESHOLD = 0.5` and `DEFAULT_SUPPORTING_METRIC_THRESHOLD = 0.5`
  now live in `services/evals/evals/config.py` (~line 170-176).
- `services/evals/evals/attribution.py` imports both from `evals.config` and
  re-exports them. **Direction matters:** `attribution` already depends on `config`
  transitively, so `config` must never import `attribution` — that would cycle.
- `EvalConfig` gained `correctness_threshold` and `supporting_metric_threshold`
  fields (`config.py` ~line 350-357).

**Not done — this is the actual work:** `services/evals/evals/runner.py:796` still calls

```python
attributions = attribute_questions(all_questions, all_responses, scorecard)
```

positionally, so the two new `EvalConfig` fields are **declared and unused**. The
module constants remain the only effective values in a real run.

### Build

1. Pass the config values at the call site:
   `attribute_questions(..., correctness_threshold=self.config.correctness_threshold, supporting_metric_threshold=self.config.supporting_metric_threshold)`.
2. Surface both in the config snapshot so a run records the thresholds its
   verdicts were made under (see how `config.py:466` records the scoring
   thresholds — follow that pattern). A verdict whose bar is not recorded is not
   reproducible.
3. Optionally accept them from `config.yml` under `eval:` if that is where the
   other eval settings are read; match whatever `EvalConfig.from_yaml` already does.

### Verify

- A test constructing `EvalConfig(correctness_threshold=0.9)` and running a
  question that scores 0.8 gets `generation_drift`, while the same question under
  the default 0.5 gets `correct`. Write it first; confirm it fails now (the
  override is ignored today), then fix.
- The recorded config snapshot for a run contains both thresholds.

---

## Item 3 — the HTTP rechunk sweep cannot run

### The defect

`services/evals/tests/integration/test_rechunk_invariance.py` is written and
correct but **skips**: it needs to change `chunk_size` between two ingestions, and
there is no endpoint for that. `chunk_size` lives in `config.yml:301`; the routes
under `services/rag_server/api/routes/` expose `/settings` (contextual retrieval
only), not chunking.

The *ingestion* half of the criterion is already proven in-process by
`services/rag_server/tests/test_rechunk_lineage.py`, which runs the real
parse+chunk path at chunk sizes 500 and 1000 for both a `.txt` and a `.pdf`
fixture and passes. What is unproven is the HTTP round trip.

### Build

Pick one and say which:

- **Preferred: extend `PATCH /settings`** to accept `chunk_size` / `chunk_overlap`,
  writing through `update_config_file("chunking.chunk_size", ...)` exactly as the
  contextual-retrieval toggle already does. Add them to `schemas/settings.py`'s
  `SettingsUpdate` / `SettingsResponse`. This mirrors an existing, working pattern
  and is the smallest change.
- Alternative: a dedicated `PATCH /config/chunking` route.

Then update the integration test to use whichever endpoint exists (it currently
probes `PATCH /config/chunking` and skips on 404).

**Invariant 3 check:** this adds an operator-facing setting; it does not change
any default. Confirm `config.yml`'s `chunk_size: 500` is untouched.

### Verify

- `cd services/evals && uv run pytest tests/integration -q --run-integration`
  runs `test_gold_evidence_survives_a_rechunk` for both `txt` and `pdf` **without
  skipping**, and both pass: the same unmodified gold question resolves to the
  evidence-bearing chunk set at chunk_size 500 and 1000, `recall_at_5 == 1.0` in
  both, and `details["ground_truth"] == "source_coordinate"`.
- Restore the server's original chunk_size afterwards (the test must not leave
  the setting flipped — follow `contextual_ab.py`'s restore-in-`finally` pattern).

---

## Item 4 — the live fault-localization run

**REQUIRES EXPLICIT USER AUTHORIZATION BEFORE RUNNING. Do not run it on your own
initiative; ask, and wait.** It writes fixture documents into the user's live
database and, unless `--no-judge` is passed, spends money on judge LLM calls.

### What exists

`services/evals/tests/test_fault_localization.py` proves the criterion at metric
level: a bad reranker raises `rerank_demotions` and leaves `candidate_recall_ceiling`
flat; a degraded embedder drops the ceiling and leaves rerank behaviour flat. It
fails against pre-remediation HEAD with `AssertionError: ceiling must be defined
on a miss, not None`, which is exactly the parent plan's diagnosis. That evidence
is real but fixture-based.

### Build / run (once authorized)

1. The zero-token variant first: `--retrieval-only --no-judge` routes through
   `POST /search` and spends nothing. `rerank_demotions` and
   `candidate_recall_ceiling` are retrieval metrics, so this is sufficient for the
   criterion.
2. Ingest the two fixtures (`services/evals/evals/data/documents/freedonia_facts.txt`,
   `sylvania_report.pdf`), run the golden dataset's two evidence-bearing questions,
   and clean up the uploaded documents afterwards.
3. Record the observed metric values, not just "it passed".

### Verify

Both faults move disjoint metrics on the live stack, matching the fixture-level
result. If they do not, that is a genuine finding — report it, do not paper over it.

---

## Item 5 — record the defects found outside the parent plan

Add to `docs/suggestions.md` (check it first; do not duplicate existing entries):

1. **Docling bbox origin.** Docling emits PDF provenance with
   `coord_origin: BOTTOMLEFT`, where the top edge has a *larger* y than the bottom.
   `_valid_bbox` asserted `value[1] < value[3]` and therefore rejected every real
   PDF bbox as malformed, making every PDF locator unusable and the whole PDF
   evidence path a lineage failure. Fixed in `services/evals/evals/evidence.py` via
   `_normalized_bbox`, which orders both axes. Regression tests in
   `services/evals/tests/test_source_coordinate_authoring.py::TestDoclingBboxOrigin`.
2. **PDF locators carry `element_id`, not `block_id`.** `_locator_is_usable`
   accepted only `block_id` or a bbox, so Docling's actual output was unusable.
   Fixed in the same file.
3. **`pytrec-eval-terrier` publishes no aarch64 wheel** — see item 1. Record it so
   the gcc line in the Dockerfile is not later deleted as unnecessary.
4. **`context_truncated` still has no real measurement.** The engine returns
   `_aget_nodes()`'s output straight out of `_run_c3`, so the `context_assembly`
   trace is the reranker's own list. Attribution now detects the mirrored list and
   marks the stage unassessable with an explicit reason, rather than shipping a
   label that can never fire. Genuinely measuring the packed context would mean
   instrumenting the response synthesizer — out of scope, worth recording.

---

## Item 6 — commit the work

Nothing is committed. Do this **last**, after items 1–3 and 5 are green.

1. Branch off `main` first — do not commit to `main`.
2. Group into reviewable commits along track lines rather than one giant commit,
   e.g.: retrieval ground truth + chunk-id namespace; evidence resolver; failure
   attribution + store; server observability/concurrency/ingestion; cost
   accounting; source-coordinate authoring + fixtures; contextual A/B; follow-up
   fixes.
3. Short one-line commit messages (`CLAUDE.md`).
4. Do **not** push or open a PR unless the user asks.

---

## Reporting

For each item: the failing test written first with its pasted output, the diff,
the verification evidence, and anything found that this plan does not describe. An
item that cannot be completed reports what was left and why — do not narrow scope
silently.

Do not close this on green tests. Items 3 and 4 are the end-to-end proof; item 4
needs the user's explicit go-ahead before it runs.
