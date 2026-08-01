# Eval framework

## Design and the two tiers

Evaluation lives in the separate `evals` service (`services/evals/`), which talks
to `rag-server` over HTTP like any other client (see `architecture.md`). Metrics
and the LLM-as-judge are implemented in this repo — no third-party eval framework
(RAGAS, DeepEval, Phoenix) is used. See the "In-house vs. third-party" section
below, and `design-decisions.md` for the full narrative.

An eval run operates in one of two tiers:

- **`generation`**: gold and distractor passages are injected directly as context
  via `/query/with-context` — retrieval itself is not exercised. This isolates
  generation-quality metrics (faithfulness, correctness, relevancy) from whatever
  the corpus and retrieval configuration would otherwise contribute.
- **`end_to_end`**: gold and distractor passages are first uploaded as real
  documents through `rag-server`'s ingestion pipeline, then queried through the
  normal `/query` path with `include_chunks=True`. This exercises the full
  pipeline — retrieval, reranking, generation — and is the tier retrieval metrics
  require.

Each dataset declares which tier(s) it supports; an incompatible combination
raises a config error rather than silently running.

## Dataset adapters

| Dataset | What it tests | Tier support | Notes |
|---|---|---|---|
| `ragbench` | Multi-domain RAG benchmark with TRACe annotations (adherence, relevance, utilization, completeness), 12 industry subsets | generation, end_to_end | Default dataset; default subset mix is a curated four-subset sample |
| `qasper` | QA over scientific papers with evidence spans | end_to_end only | citation + generation focus; documented in-repo as broken under `datasets>=4.0` |
| `squad_v2` | Reading comprehension including unanswerable questions | generation only | abstention focus; naturally ~50% unanswerable, ratio adjustable |
| `hotpotqa` | Multi-hop QA requiring reasoning across documents | end_to_end only | retrieval + generation; gold passages built from supporting-fact sentence indices |
| `msmarco` | Large-scale reading comprehension for retrieval ranking | end_to_end only | retrieval only |
| `golden` | Local curated Q&A pairs authored against the operator's own documents | generation, end_to_end (nominally) | No network access — reads a local JSON file. Currently 10 entries. **No `gold_passages` are ever populated for this dataset**, so retrieval and citation metrics against it are meaningless regardless of declared tier support — it effectively only exercises generation-quality judging |

All loaders normalize into a common schema (question, expected answer, gold
passages, distractor context passages, query type, difficulty, domain). Dataset
loads are cached to disk keyed by dataset name, split, sample count, and seed;
`--no-cache` bypasses this. There is no caching of RAG server responses or judge
calls — every eval run re-executes every query and every judge call from scratch.

## Metric catalogue

| Metric | Group | Computation | Range / direction | Judge required |
|---|---|---|---|---|
| `recall_at_{k}` | retrieval | matched retrieved chunks ∩ gold / total gold | 0–1, higher better | No |
| `precision_at_{k}` | retrieval | matched ∩ gold / min(k, retrieved count) | 0–1, higher better | No |
| `mrr` | retrieval | 1 / rank of first relevant retrieved chunk | 0–1, higher better | No |
| `ndcg_at_{k}` | retrieval | standard DCG/IDCG over retrieved ranking | 0–1, higher better | No |
| `faithfulness` | generation | are answer claims grounded in retrieved context | 0–1, higher better | Yes |
| `answer_correctness` | generation | semantic equivalence of answer to expected answer (requires gold answer) | 0–1, higher better | Yes |
| `answer_relevancy` | generation | does the answer address the question | 0–1, higher better | Yes |
| `citation_precision` | citation | cited ∩ gold / citations count | 0–1, higher better | No |
| `citation_recall` | citation | cited ∩ gold / gold count | 0–1, higher better | No |
| `section_accuracy` | citation | fraction of citations whose doc+chunk id exactly matches a gold passage | 0–1, higher better | No |
| `unanswerable_accuracy` | abstention | (true positive + true negative) / total, over an abstain-vs-should-abstain confusion matrix | 0–1, higher better | No |
| `abstention_false_positive_rate` | abstention | rate of incorrect abstention on answerable questions | 0–1, lower better | No |
| `abstention_false_negative_rate` | abstention | rate of incorrectly answering (hallucinating) on unanswerable questions — the hallucination-risk metric | 0–1, lower better | No |
| `latency_p50` / `latency_p95` | performance | median / 95th-percentile latency across the batch | ms, lower better | No |
| `cost_per_query` | performance | token counts × per-model rate, averaged over batch | USD, lower better | No |

Only the three generation metrics require an LLM judge. Retrieval, citation,
abstention, and performance metrics are computed by direct matching or arithmetic
— matching falls back from exact chunk-ID match to Jaccard token-overlap with a
0.3 threshold when IDs don't line up cleanly.

Retrieved-chunk matching against gold passages, and citation matching, both use the
same exact-ID-first, Jaccard-overlap-fallback logic — there is one shared matching
implementation behind both metric groups.

## The LLM judge

Three metrics — `faithfulness`, `answer_correctness`, `answer_relevancy` — each
have a dedicated prompt. All three ask for a score on a 0.0 / 0.5 / 1.0 rubric
described in the prompt text itself (fully supported / partially supported /
unsupported, or the equivalent framing for correctness and relevancy), but the
judge model can return any float in `[0, 1]` — the parser accepts plain decimals,
fraction notation, and percentages, and clamps the result into range. A fourth
prompt, context relevance, exists but is used only by the calibration tool, not by
any production metric.

**Model resolution**: the judge is a separate LLM instance from the main RAG
generation model, resolved from `config.yml`'s `active.eval` setting (any
supported provider — Ollama or a cloud provider). Temperature is forced to `0.0`
and retries to `3` regardless of what a bare judge-config dataclass default would
say, because the actual code path always loads its defaults from the live
`models_config.eval` setting, not from the dataclass's own field defaults.

**Retry and parsing**: a malformed response (no parseable `SCORE:` line, or an
unparseable value) raises a parse error *inside* the retry loop, so a malformed
response triggers a retry rather than being silently accepted as evidence — this
was a deliberate fix, since an earlier version treated unparseable output as a
valid `0.0`.

**Failure semantics — this is the load-bearing behavior of the whole framework**:
once retries are exhausted, a failed judge call raises rather than returning a
score. The failure is explicitly treated as missing data, not as evidence of a bad
answer, so it is never scored `0.0`. The batch-metric runner catches this,
excludes the failed sample from the average, and reports the reduced
`sample_size` — a run with some judge failures reports a smaller sample size and
an average computed only over the calls that succeeded, rather than a lower
average that silently includes zeros for the failures. The same pattern holds in
calibration: a failed judge call there drops the whole item and is tracked via a
`dropped_judge_failures` counter in the result metadata, so a calibration run over
a flaky judge is visibly thin rather than quietly averaged over whatever
succeeded. Genuine `0.0` scores are still possible and are a distinct case — no
context retrieved (`faithfulness`) or no expected answer defined
(`answer_correctness`) both legitimately score `0.0` rather than being excluded.

## Weighted score

A single weighted score combines metric groups using fixed objective weights:
accuracy 0.30, faithfulness 0.20, citation 0.20, retrieval 0.15, cost 0.10,
latency 0.05. These are the framework's own defaults, not user-tunable per run
via any exposed flag today (they live as a dataclass default in the eval config
module). The weighted score is also the basis for Pareto-frontier comparisons
across runs — a run "dominates" another if it is at least as good on every
objective and strictly better on at least one; this is a strict dominance check,
not a statistical test (see Known gaps).

## Calibration

`calibrate` measures agreement between the judge and RAGBench's own
human/GPT-annotated TRACe ground truth labels, answering "how much should we trust
the judge scores this framework reports?" It covers exactly two of the four judge
prompts:

- **Faithfulness vs. adherence**: judge faithfulness score compared against the
  RAGBench `adherence_score` ground-truth label (accuracy of a thresholded
  agreement, plus RMSE against the label).
- **Context relevance vs. relevance**: judge context-relevance score compared
  against the RAGBench `relevance_score` ground-truth label (RMSE).

**`answer_correctness` and `answer_relevancy` are never calibrated against any
ground truth** — there is no RAGBench label that corresponds to either, so no
calibration procedure exists for them. This is a real limitation, not an oversight
to be quietly worked around: those two metrics' scores rest entirely on the
judge's own rubric-following, with no external check on agreement.

Calibration runs on RAGBench items with TRACe fields, dropping any item where a
judge call fails outright rather than scoring it, and reports the drop count
alongside the aggregate metrics so a noisy run is visible.

## Persistence

There is no database backing for eval runs, results, or judge calls. Everything is
flat JSON files on disk:

- Each completed run is written as its own timestamped JSON file.
- The dataset cache and calibration results are each their own JSON files under
  separate data directories.
- The API's job manager keeps an in-memory index of past runs, but this index is
  rebuilt by scanning the run-file directory at process startup — it is a cache
  over the JSON files, not a source of truth, and is lost (until reindexed) on
  every restart.
- Exactly one eval job can be active at a time, tracked via in-memory state guarded
  by a lock; a second trigger while one is running gets a conflict response rather
  than queuing.

## In-house vs. third-party

The project used RAGAS, then DeepEval, then dropped DeepEval once nothing in the
codebase imported it and its metrics had all been replaced with hand-rolled ones.
Re-adopting a third-party framework was reconsidered and declined again, primarily
because it would trade the current *calibrated* judge (calibration measured
against RAGBench's own TRACe labels, see above) for an uncalibrated one whose
prompts the team doesn't control, plus a telemetry posture (DeepEval phones home
on import) that conflicts with a privacy-first product on exactly the one code
path — the judge — that PII masking doesn't cover. See `design-decisions.md` for
the full three-part rationale and what would justify revisiting it.

## Known gaps

Carried forward honestly rather than fixed or hidden:

- **No statistical significance testing anywhere.** Run comparison does raw
  per-metric value diffs and strict Pareto dominance checks only — no confidence
  intervals, no paired significance test, no accounting for the per-metric
  standard deviation that is computed internally but never surfaced in
  comparisons. A one-question swing can look identical in the comparison output
  to a thousand-question swing.
- **Single judge model, no ensemble or inter-rater agreement.** Exactly one LLM
  scores every generation metric on every run; there is no multi-judge consensus
  or human-in-the-loop cross-check wired into the pipeline.
- **The golden dataset has no gold passages at all.** Retrieval and citation
  metrics are meaningless against it; an operator building their own golden set
  gets generation-only coverage unless they extend the loader themselves.
- **`ConfigSnapshot` fields are partly hardcoded.** Several fields recorded on
  every saved run (retrieval `top_k`, hybrid-search enabled, contextual-retrieval
  enabled) are fixed defaults in code with comments admitting the real values
  aren't available from the RAG server's info endpoint — every saved run reports
  these as the same constants regardless of what the RAG server was actually
  configured with at the time, which undermines any comparison that assumes
  config varies meaningfully across runs.
- **Richer exporters are orphaned.** A per-question/response review exporter
  (JSON/CSV/Markdown, including a manual-review CSV with blank reviewer columns)
  exists as library code but is not called from the CLI's `export` subcommand or
  from the API — the CLI has its own simpler inline export logic instead. The
  manual-review workflow the richer exporter was built for is effectively
  unreachable from any documented entry point today.
- **Stale artifacts from the earlier deepeval-era framework remain in the data
  directory.** A leftover baseline file and at least one old run result reference
  metric names (e.g. contextual precision, hallucination as a named metric) that
  don't exist anywhere in the current metrics package and aren't read by any code
  path — they're dead files that could mislead anyone browsing the data
  directory into thinking those metrics still exist.
