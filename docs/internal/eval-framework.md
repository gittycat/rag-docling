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
| `qasper` | QA over scientific papers with evidence spans | end_to_end only | citation + generation focus; loads via the `refs/convert/parquet` revision and handles both the dict-of-lists and list-of-dicts `qas` shapes. Verified working on `datasets` 4.5 — the in-repo "broken under `datasets>=4.0`" note was stale |
| `squad_v2` | Reading comprehension including unanswerable questions | generation only | abstention focus; naturally ~50% unanswerable, ratio adjustable |
| `hotpotqa` | Multi-hop QA requiring reasoning across documents | end_to_end only | retrieval + generation; gold passages built from supporting-fact sentence indices |
| `msmarco` | Large-scale reading comprehension for retrieval ranking | end_to_end only | retrieval only |
| `golden` | Local curated Q&A pairs authored against the operator's own documents | generation | No network access — reads a local JSON file. Currently 10 entries, none annotated. Accepts optional `gold_passages` (full dicts or bare strings), `gold_doc_ids` (document-level shorthand) and `context_passages` per entry; without them retrieval and citation metrics report `None` (undefined) rather than 0.0 or a fabricated 1.0 |

All loaders normalize into a common schema (question, expected answer, gold
passages, distractor context passages, query type, difficulty, domain). Dataset
loads are cached to disk keyed by dataset name, split, sample count, and seed;
`--no-cache` bypasses this.

RAG-server responses and judge calls have their own content-addressed disk cache
(`evals/cache.py`, under `data/eval_cache/`), keyed by a hash of everything that
determines the answer. The judge cache is **on** by default — the judge runs at
temperature 0, so an identical prompt is an identical call — and disabled with
`--no-judge-cache`. The query cache is **off** by default (`--cache-queries`)
because its key covers the server's reported configuration but *not the indexed
corpus*: after a re-ingest a cached answer is stale while looking fresh. It also
self-disables when the server did not report its retrieval configuration, since
the fingerprint then cannot distinguish two pipelines. A cache hit replays the
originally measured latency, not the hit time, so latency metrics stay honest.

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
implementation behind both metric groups. Citation matching adds a document-level
path for gold passages that carry no text (produced by `gold_doc_ids`), which
would otherwise be unmatchable and score a spurious 0.

### `None` is not `0.0`

`MetricResult.value` is `float | None`. `None` means the metric is **undefined for
the data it was given**, and it is never rendered as a number: the CLI and exports
print `n/a`, the API serializes `null`, the dashboard shows a muted `n/a`, and the
weighted score drops the objective and redistributes its weight.

Cases that produce it:

| Case | Previously | Why the old value was wrong |
|---|---|---|
| Citation metrics, no gold passages | `1.0` | A golden-set run displayed perfect citation scores that measured nothing |
| Retrieval metrics, no gold passages | `0.0` | A dataset without retrieval annotations looked like a retrieval regression |
| `abstention_false_positive_rate` on an unanswerable question | `0.0` | Counted as "did not falsely abstain", pulling the rate down by however many unanswerable questions happened to be present |
| `abstention_false_negative_rate` on an answerable question | `0.0` | Same, mirrored |
| Every sample failed or was inapplicable | `0.0` | Indistinguishable from a genuinely zero score |

`BaseMetric.compute_batch` excludes `None` results from the average and counts
them under `details.not_applicable_count`, so `sample_size` reflects what was
actually measured.

### Per-question scores

`compute_batch` records `details.per_question` — a `{question_id: score}` map —
alongside the aggregate. Question ids rather than a bare list, because a list
misaligns as soon as one question errors in one run only, and pairing two runs by
position would then compare different questions. This map is what makes
significance testing possible; the metrics that override `compute_batch`
(`unanswerable_accuracy`, `cost_per_query`) populate it too, and the runner adds
it for `latency_avg_ms`.

## Statistical comparison

`evals/stats.py` turns per-question scores into interval estimates. Reached from
`python -m evals.cli compare` (on by default, `--no-significance` to skip) and
`GET /eval/runs/compare?ids=a,b` (`significance` field). The first run is the
baseline; every later run is compared against it.

| Component | Choice | Why |
|---|---|---|
| Interval | Percentile paired bootstrap, B = 10,000, seeded | Works identically for continuous judge scores and binary hit/miss metrics; makes no normality assumption, which matters because judge scores cluster on rubric points. The seed is fixed so two invocations on unchanged inputs cannot disagree |
| Binary metrics | McNemar's exact test + discordant counts | Exact rather than chi-square because discordant counts on a 100-question eval are routinely under 25. The counts ("38 improved, 18 regressed") are usually more informative than the rate delta |
| Family correction | Benjamini-Hochberg at the same alpha | Scanning ~20 metrics uncorrected gives ~64% chance of at least one spurious mover. The uncorrected arithmetic is also printed, so the correction is auditable rather than magic |
| Underpowered flag | n < 100 paired questions | Normal-approximation-scale intervals substantially understate uncertainty below a few hundred datapoints |

Only questions present in **both** runs for a given metric are paired; a question
that errored in one run is dropped from that metric rather than scored zero.
Metrics with no per-question data on either side — aggregate-only metrics like
`latency_p50_ms`, or runs saved before per-question capture existed — are listed
under `skipped` rather than being given invented statistics.

`numpy` is a direct dependency for this: a vectorized bootstrap keeps a 20-metric
comparison well under a second, where a pure-Python resample loop would make the
API endpoint unusable.

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

A single weighted score combines metric groups using objective weights read from
`eval.scoring` in the repo-root `config.yml`: accuracy 0.30, faithfulness 0.20,
citation 0.20, retrieval 0.15, cost 0.10, latency 0.05 by default. The latency and
cost normalization thresholds live there too
(`latency_threshold_ms_generation` / `latency_threshold_ms_end_to_end`,
`max_cost_per_query_usd`) — they used to be constants in the runner, so a
latency-sensitive deployment could not change what the headline number rewarded
without editing code. `ScoringConfig.from_models_config()` reads them, falling
back to the module constants when the config is unavailable. The resolved values
are recorded in each run's `metadata.scoring`, so an old run stays interpretable
after the thresholds change.

A metric whose value is `None` (undefined for the dataset) contributes nothing:
its objective is dropped and the weight redistributed, rather than the objective
being scored 0. The weighted score is also the basis for Pareto-frontier comparisons
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

`answer_correctness` and `answer_relevancy` have **no corresponding RAGBench
label**, so they get a weaker check rather than none: a **discrimination test**.
Each item's reference response is scored against its own reference/question (known
correct) and against a neighbouring item's (known wrong), and the result reports
mean matched score, mean mismatched score, separation, and the fraction of pairs
ranked correctly.

This is a floor, not a calibration. Passing it says the prompt distinguishes an
obviously-right pairing from an obviously-wrong one; it says nothing about whether
mid-range scores track human judgement. Reported as
`correctness_discrimination` / `relevancy_discrimination` in the saved result, and
the CLI prints the caveat alongside the numbers.

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
- Each run also writes a per-question sidecar, `{run}_samples.json`, holding the
  question/response pairs the review exporters need. The run index skips these when
  scanning, and every run is additionally copied to `eval_runs/backup/` — a run is
  hours of compute with no database behind it.
- Exactly one eval job runs at a time, tracked via in-memory state guarded by a
  lock. Further triggers **queue** (FIFO, depth `EVAL_QUEUE_DEPTH`, default 5) and
  the head is promoted when the active job finishes; only a full queue returns
  `429`. `GET /eval/queue` lists pending jobs and `DELETE /eval/queue/{job_id}`
  drops one. The queue is in-memory: a service restart loses it.

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

- **Single judge model, no ensemble or inter-rater agreement.** Exactly one LLM
  scores every generation metric on every run; there is no multi-judge consensus
  or human-in-the-loop cross-check wired into the pipeline. The runner does warn
  when the judge shares a provider with `active.inference` — self-preference bias
  is documented to extend across a model family, which makes the shipped
  all-OpenAI default a non-neutral referee for local-versus-cloud comparisons —
  and records the warning in `metadata.judge_independence_warning`, but a warning
  is not an ensemble.
- **The bootstrap resamples questions, not judge calls.** Judge variance on
  identical inputs is invisible to the intervals `compare` reports.
- **The dashboard shows point deltas only.** The significance data is on the API
  response (`significance`) but the analytics UI does not render it yet.
- **`ConfigSnapshot` records "unknown" rather than guessing.** Retrieval `top_k`,
  hybrid-search enabled and contextual-retrieval enabled are read from the RAG
  server's `/metrics/retrieval` endpoint at run start, alongside the model fields
  from `/models/info`. If that call fails the three fields are stored as `null`
  and reports render them as "Unknown" — deliberately, so a run whose config was
  never captured cannot be mistaken for one that really ran with those settings.
  (They were previously hardcoded to `top_k=10` / hybrid off / contextual off on
  every saved run, which silently corrupted every comparison.) The full endpoint
  response is also kept under `config.additional.retrieval`, so `rrf_k`, the
  reranker `top_n` and `final_top_n` are recoverable from a saved run.
- **Review exports need a samples sidecar.** `export --format review-csv|review-md|
  review-json` reconstructs question/response pairs from `{run}_samples.json`.
  Runs completed before that sidecar existed cannot be exported for review; the
  command says so rather than emitting an empty sheet.
