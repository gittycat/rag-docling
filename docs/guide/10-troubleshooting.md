# 10. Troubleshoot

Start with the symptom, confirm the cause, then apply the narrowest fix.

## Startup

### A service exits or Compose reports a missing secret

**Cause:** a required file under `secrets/` is absent.

```bash
ls secrets/
```

Every deployment needs the four PostgreSQL files. Active OpenAI or Anthropic
models also need their provider key. Create the missing file as described in
[Chapter 2](02-getting-running.md#create-secrets-first), then run `just up`.

### “Ollama is not reachable”

**Cause:** an active model uses Ollama, but the service cannot reach the configured
URL.

```bash
curl -sf http://localhost:11434/api/version
```

If this fails, start Ollama. If it succeeds, check the model’s `base_url`; Docker
Desktop, OrbStack, and Podman may reach the host differently. Then restart:

```bash
docker compose restart rag-server task-worker
```

### “Reranker model not found in local cache”

**Cause:** reranking is enabled and the model is absent from the offline Hugging
Face cache.

```bash
just init
# or
just init MODEL=BAAI/bge-reranker-base
```

Restart after the download.

### “Embedding dimension mismatch”

**Cause:** stored vectors came from a model with another output dimension.

Switch back, or rebuild the index by fully re-ingesting with the active model.
There is no in-place conversion. Same-dimension swaps are not detected, so always
re-ingest after any embedding-model change.

### The RAG server fails after enabling PII

The startup error identifies one of two conditions:

| Cause | Fix |
|---|---|
| PII with a cloud embedding model | Select an Ollama-backed embedding model |
| GLiNER enabled but unavailable | Build with `INSTALL_GLINER=true`, install the extra locally, or disable GLiNER |

## Ingestion

### A document remains in “processing”

**Cause:** the task worker stopped while holding a task.

```bash
docker compose logs task-worker | grep -i stuck
curl http://localhost:8001/tasks/<batch_id>/status
```

The worker checks every 60 seconds and returns tasks older than one hour to
`pending`. A task already at its maximum attempts becomes `error`. Wait for
automatic recovery, or inspect the worker exception and re-upload after fixing it.

### Upload returns 503 and mentions Ollama

**Cause:** the active local embedding model became unavailable.

```bash
curl -sf http://localhost:11434/api/version
```

Restart Ollama and retry the upload.

## Query

### Exact keyword matches are ignored

**Cause:** BM25 failed and the query continued with vector search only.

```bash
curl -s http://localhost:8001/metrics/system \
  | jq '.component_status.bm25'
docker compose logs rag-server | grep "\[BM25\] Search failed"
```

Inspect the logged SQL error, the `pg_textsearch` extension, and the
`idx_chunks_bm25` index on `document_chunks`. While investigating, disable hybrid
search so the degraded mode is explicit.

### The chat shows a generic connection error

The UI uses the same message for an unavailable local model, provider timeout,
quota error, or RAG-server crash.

```bash
docker compose logs rag-server -f
```

Repeat the query and use the underlying error to choose the fix.

## Evaluation

### HTTP 429: “Eval queue is full”

Only one run executes at a time. The queue has reached `EVAL_QUEUE_DEPTH`, which
defaults to 5.

```bash
curl http://localhost:8002/eval/runs/active
curl http://localhost:8002/eval/queue
curl -X DELETE http://localhost:8002/eval/queue/<job_id>
curl -X DELETE http://localhost:8002/eval/runs/active
```

Cancel a stuck active run or remove an unnecessary queued run.

### “No paired per-question data available”

One or both runs lack per-question scores, often because they predate that data.
Re-run both configurations. Point differences remain available, but they have no
paired uncertainty estimate.

### A metric is `n/a`

The metric is undefined, not zero. Common causes are retrieval metrics in a
generation-tier run or citation metrics without gold passages. Choose a compatible
tier and annotated dataset; see [Chapter 5](05-running-evals.md#annotating-gold-passages).

### Judge-dependent metrics have small samples

Judge timeouts, rate limits, or malformed responses are excluded rather than
scored zero. Compare each metric’s `sample_size` with `question_count`, then inspect:

```bash
docker compose logs evals
```

Rerun after the provider recovers or select another judge.

## Performance and persistence

### Ingestion is unexpectedly slow

Contextual retrieval makes one LLM call per chunk and often dominates ingestion.

```bash
just show-config-full
```

Disable `retrieval.enable_contextual_retrieval` or raise
`retrieval.contextual_concurrency` if the provider supports more parallel calls.
Re-ingest after changing the feature.

### The first query after startup is slow

The reranker loads lazily on first use. This is a one-time cost per container
lifetime. Warm it before measuring latency.

### Documents or chat history disappeared after restart

`docker compose down -v` deletes the PostgreSQL and ChromaDB volumes. `just down`
does not. There is no built-in recovery; re-ingest the source files retained under
`data/indexed_documents`.

**Next:** [11. Limits and caveats](11-limits-and-caveats.md).
