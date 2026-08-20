# 10. Troubleshooting

Symptom → cause → check → fix, grouped by where in the lifecycle the problem shows
up.

---

## Startup

### A service exits immediately, or Compose reports a missing secret

**Cause.** A required file under `secrets/` does not exist. Compose secrets are
declared as `file: secrets/<NAME>`; a missing source file blocks the container that
mounts it.

```bash
ls secrets/
```

`POSTGRES_SUPERUSER`, `POSTGRES_SUPERPASSWORD`, `RAG_SERVER_DB_USER`, and
`RAG_SERVER_DB_PASSWORD` are required for every deployment, plus
`OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` if your active models need them.

**Fix.** Create the missing files — see [chapter 2](02-getting-running.md#create-secrets-first)
— then `just up`.

### "Ollama is not reachable"

**Cause.** `active.inference` or `active.embedding` points at an `ollama` model,
but Ollama is not running or not reachable at the configured `base_url` (default
`http://host.docker.internal:11434`). The app checks at startup and calls
`sys.exit(1)` rather than starting broken.

```bash
curl -sf http://localhost:11434/api/version
```

If that fails, Ollama is down. If it succeeds and the container still fails, check
that the model's `base_url` matches how your Docker setup reaches the host — this
differs between Docker Desktop, OrbStack, and Podman.

**Fix.** Start Ollama (`ollama serve` or the app), then
`docker compose restart rag-server task-worker`. `just preflight` catches this
before it happens.

### "Reranker model not found in local cache"

**Cause.** Reranking is enabled (the default) and the active reranker was never
pre-fetched. `HF_HUB_OFFLINE=1` is set whenever `USE_CACHED_RERANKER` is true — as
it is in the base compose file — so the container will not silently fall back to a
live download.

```bash
ls .cache/huggingface
```

Look for a directory matching the active reranker (default
`cross-encoder/ms-marco-MiniLM-L-6-v2`).

**Fix.**

```bash
just init                                    # default model
just init MODEL=BAAI/bge-reranker-base       # if you changed active.reranker
```

Then restart.

### "Embedding dimension mismatch"

**Cause.** You switched `active.embedding` to a model whose output dimension
differs from the one that built the existing ChromaDB collection. The startup check
peeks one stored vector, measures its dimension, and compares against a live probe
from the active model.

**Check.** The startup log states both dimensions, e.g. "stores 768-dimensional
vectors, but the active embedding model ... produces 1536-dimensional vectors."

**Fix.** Either switch back to the model that built the index, or delete and fully
re-ingest under the new model. There is no in-place re-embedding path.

Note the check cannot catch a **same-dimension** swap between different models —
that passes and silently degrades retrieval. Always re-ingest after an embedding
change.

### rag-server refuses to boot after enabling PII masking

Two conditions trip this, and the startup error names which:

| Cause | Fix |
|---|---|
| **Cloud embedding + PII.** `pii.enabled: true` is rejected at config-load time unless the active embedding provider is `ollama`. Masking covers only the generation path, so this is a hard invariant, not a warning. | Set `active.embedding` to an Ollama-backed model before enabling `pii.enabled` |
| **GLiNER enabled but not installed.** `pii.gliner.enabled: true` is rejected if the `gliner` package is not importable — fails fast rather than falling back to spaCy-only. | Rebuild with `--build-arg INSTALL_GLINER=true` (or `uv sync --extra gliner` locally), or set `pii.gliner.enabled: false` |

---

## Ingestion

### Uploaded documents stay "processing" indefinitely

**Cause.** The task worker crashed or was killed mid-task, leaving a `job_tasks`
row stuck in `processing`.

A background check runs every 60 seconds and resets any task processing for more
than one hour back to `pending` for another worker to claim — unless it has already
hit `max_attempts`, in which case it is marked `error` with "Task exceeded maximum
retry attempts (stuck worker)."

```bash
docker compose logs task-worker | grep -i "stuck"
curl http://localhost:8001/tasks/<batch_id>/status
```

A line like `[WORKER] Reset N stuck task(s) to pending` confirms recovery ran.

**Fix.** Under an hour, wait — the reset is automatic. If a task keeps failing into
`error`, check `docker compose logs task-worker` around its processing time for the
underlying exception, then re-upload.

### Upload fails with a 503 mentioning Ollama

**Cause.** The active embedding model is Ollama-backed and Ollama is unreachable at
ingestion time — which can happen if it was up when the container started but has
since stopped.

```bash
curl -sf http://localhost:11434/api/version
```

**Fix.** Restart Ollama, then retry. The Upload page shows a dedicated alert for
this failure mode.

---

## Query

### Answers ignore keyword matches that should be an easy hit

**Cause.** BM25 failed for that query and degraded silently. The retriever catches
any exception around its SQL search, logs a warning, and returns an empty list
rather than raising — so the query proceeds vector-only, with **nothing in the
response indicating it happened.**

```bash
curl -s http://localhost:8001/metrics/system | jq '.component_status.bm25'
docker compose logs rag-server | grep "\[BM25\] Search failed"
```

**Fix.** Read the logged exception for the specific SQL error, then check that the
`pg_textsearch` extension and the `idx_chunks_bm25` index exist and are valid on
`document_chunks`. While you investigate, setting
`retrieval.enable_hybrid_search: false` gives you an explicit, known-quantity
degrade rather than a silent intermittent one.

### A query returns a generic connection error

**Cause.** Could be a downed Ollama, a cloud provider outage or timeout, or a
backend crash. The chat UI does not distinguish these — a failed stream just
appends `[Error: Connection interrupted]` to the partial message.

```bash
docker compose logs rag-server -f
```

Reissue the query to see the underlying exception in real time.

**Fix.** Depends on the logs: restart Ollama, check your cloud API key and quota,
or check `docker compose ps` for a crashed rag-server.

---

## Evaluation

### HTTP 429 "Eval queue is full"

**Cause.** One eval runs at a time and the rest queue behind it. A `429` means the
queue hit its depth limit (default 5, set by `EVAL_QUEUE_DEPTH`) — usually because
an earlier job is hung.

```bash
curl http://localhost:8002/eval/runs/active   # the running job
curl http://localhost:8002/eval/queue         # what is waiting
```

**Fix.**

```bash
curl -X DELETE http://localhost:8002/eval/queue/<job_id>   # drop a queued job
curl -X DELETE http://localhost:8002/eval/runs/active      # cancel the active one
```

### "No paired per-question data available"

**Cause.** One or both runs predate per-question score capture, so there is nothing
to pair on. Significance testing needs `details.per_question` in the scorecard, and
the framework will not invent statistics without it.

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); \
  print([m['name'] for m in d['scorecard']['metrics'] if m.get('details',{}).get('per_question')])" \
  data/eval_runs/<file>.json
```

**Fix.** Re-run both configurations. The point deltas above the significance block
are still correct; they just carry no uncertainty estimate.

### A metric shows "n/a"

**Not a fault.** The metric was undefined for that run's data — most often citation
or retrieval metrics on a dataset with no gold passages. It reports `n/a` rather
than 0.0 or 1.0 because either would be a fabricated score.

**Fix**, if you want it measured: annotate `gold_passages` or `gold_doc_ids` in
`golden_qa.json` ([chapter 5](05-running-evals.md#annotating-gold-passages)), or
run against a dataset that ships annotations.

### Judge-dependent metrics look sparse

**Cause.** The judge failed on some questions — timeout, rate limit, malformed
response. Judge failures are excluded from that metric's average rather than scored
0, so a bad run shows as "fewer samples contributed" rather than "the model did
poorly."

**Check.** Compare the metric's `sample_size` against the run's `question_count` —
in the run JSON, in `just eval-compare` output, or in the dashboard's metric
breakdown, which prints `n=` on every metric.

**Fix.** Check `docker compose logs evals` around the run for judge-call errors. If
the provider is unreliable, re-run with a different `active.eval` or after the issue
clears.

---

## Performance

### Ingestion is much slower than expected

**Cause.** Contextual retrieval issues one LLM call per chunk before embedding.
When on, this dominates ingestion, proportional to chunk count and LLM latency.

```bash
just show-config-full   # check the Retrieval section
```

**Fix.** Expected behaviour, not a bug. Budget for it, or turn it off
(`retrieval.enable_contextual_retrieval: false`, also toggleable live from the
Settings page or `PATCH /api/settings`). Raising
`retrieval.contextual_concurrency` above its default of 8 speeds it up if your
provider tolerates the parallelism. See
[chapter 7 recipe 4](07-experiment-cookbook.md#recipe-4--contextual-retrieval-on-or-off)
for the quality trade-off.

### First query after startup is noticeably slower

**Cause.** The reranker model loads from disk into memory on first use. The
postprocessor is created lazily, not during the boot-time cache check, which only
verifies the files exist. `just init` avoids a network download but not the
in-process load.

```bash
docker compose logs rag-server | grep -i rerank
```

**Fix.** Nothing — a one-time warm-up per container lifetime. Keep the container
running rather than restarting between sessions if you need consistent first-query
latency. Never include a cold first query in a latency measurement.

### A restarted stack is missing chat history or documents

**Cause.** You ran `docker compose down -v` rather than `docker compose down`
(`just down` does not pass `-v`). The `-v` flag deletes named volumes, including
`postgres_data` (chat, sessions, document metadata) and `chroma_data` (the vector
index).

```bash
docker volume ls | grep -E "postgres_data|chroma_data"
```

**Fix.** There is no recovery — no backup mechanism exists for either volume. You
must re-ingest. Original source files under `data/indexed_documents` are a host
bind mount, survive `-v`, and remain available to re-upload.

---

**Next:** [11. Limits and caveats](11-limits-and-caveats.md).
