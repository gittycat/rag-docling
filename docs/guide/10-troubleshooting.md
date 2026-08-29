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

### “TEI is not reachable”

**Cause:** an active model uses the `tei` provider, but the service cannot reach
the configured `base_url`'s `/health` endpoint at startup.

```bash
docker compose ps tei
docker compose exec tei curl -sf http://localhost:80/health
```

If `tei` is not running, start it: `docker compose up -d tei`. If it is running
but not yet healthy, see the next two entries — a cold container looks
unreachable for a while before it actually is one. If it is healthy but the app
still can't reach it, check `models.embedding.qwen3-embed.base_url` in
`config.yml` — it should be `http://tei:80` (in-compose DNS), not
`host.docker.internal` or a burst-stack IP left over from `just embed-up`. Then
restart:

```bash
docker compose restart rag-server task-worker
```

### `tei` looks hung on first boot

**Cause:** not a hang — a cold `tei_data` volume has to download
`Qwen/Qwen3-Embedding-0.6B`'s safetensors weights (~1.2GB) from HuggingFace
before the container can warm up and answer `/health`. Measured end-to-end,
cold, on a fast connection: **204 seconds** from `docker compose up -d tei` to
healthy (image pull, then ~170s of weight download, then ~18s of warmup). The
compose healthcheck's `start_period: 300s` is sized with headroom above that
measured figure — don't "tidy" it down to something like 120s, that will break
first boot on a fresh volume.

```bash
docker compose logs tei
```

Watch for `Downloading model.safetensors` progressing over time; that is
forward progress, not a stall. `just init` and `infra/assets/bake.sh` both
pre-warm `tei_data` so this cost is paid once, not on every `docker compose up`.
If it is genuinely stuck — no log progress for several minutes — suspect
network egress (see the next entry) rather than the download itself.

### `Could not start ORT backend ... onnx/model.onnx does not exist`

**Not an error.** `Qwen/Qwen3-Embedding-0.6B` publishes no ONNX weights. TEI
tries the ONNX runtime first, gets a 404, logs this line, and falls back to its
Candle backend — the same backend the CUDA image uses — logging `Starting
Qwen3 model on Cpu` and then `Downloading model.safetensors`. This is normal
and expected for this model; it happens on every cold `tei_data` volume. Do
not "fix" it by looking for ONNX weights to pre-provision — there are none to
find.

### `tei` cannot resolve `huggingface.co`

**Cause:** `tei` was put on the internal-only `private` network without
`public`. `private` is `internal: true` (no egress) — sufficient once weights
are cached, but a cold volume needs to reach `huggingface.co` to download them
in the first place. Compare against `docker-compose.yml`'s `tei` service,
which is deliberately dual-homed on both `private` and `public` for exactly
this reason (the same reason the Ollama service it replaced was dual-homed).

```bash
docker compose logs tei | grep -i "error\|resolve\|network"
```

If a custom overlay or a copy of the compose file dropped the `public` network
entry, add it back.

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

**Cause:** the active embedding model does not produce the dimension the schema
was created with. `document_chunks.embedding` is declared `vector(1024)` in
`services/postgres/init.sql` (matching `Qwen/Qwen3-Embedding-0.6B` via TEI),
and `vector_store.dimension` in `config.yml` must state the same number.

```bash
just show-config
docker compose exec postgres sh -c \
  'psql -U "$(cat /run/secrets/POSTGRES_SUPERUSER)" -d ragbench -c "\\d document_chunks"'
```

Switch back to a model of that dimension, or change both the column type and
`vector_store.dimension` and re-ingest everything. There is no in-place
conversion, and `init.sql` does not re-run against an existing volume, so a
dimension change means recreating the database. Same-dimension swaps are not
detected, so always re-ingest after any embedding-model change.

### The vector store reports `unavailable`

**Cause:** the `vector` or `vectorscale` extension is missing, or the
`idx_chunks_embedding` index was never created.

```bash
curl -s http://localhost:8001/metrics/system \
  | jq '.component_status.vector_store'
docker compose logs rag-server | grep "\[VECTOR\] Health probe failed"
docker compose exec postgres sh -c \
  'psql -U "$(cat /run/secrets/POSTGRES_SUPERUSER)" -d ragbench -c "\\dx"'
```

`\dx` must list `vector` and `vectorscale`. `docker-entrypoint-initdb.d` only
runs `init.sql` on a brand-new volume, so a database volume created before an
extension or index was added to that file won't have it. Fix it in place first:

```bash
just db-reconcile
```

Every statement in `init.sql` is idempotent (`CREATE EXTENSION IF NOT EXISTS`,
`CREATE INDEX IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`), so
re-running it against a live database adds only what's missing — no rebuild, no
volume recreation, no lost data. `just up` now runs this automatically, so it's
usually only needed as a manual step right after pulling code that changed
`init.sql`, before restarting the stack. Only rebuild the image
(`docker compose build postgres`) and recreate the volume if `\dx` still doesn't
list an extension after reconciling — that means the extension binary itself
isn't in the image, not just uncreated in the database.

### The RAG server fails after enabling PII

The startup error identifies one of two conditions:

| Cause | Fix |
|---|---|
| PII with a cloud embedding model | Select a local (`tei`) embedding model |
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

### Upload returns 503 and mentions TEI

**Cause:** the active local embedding model became unavailable. The upload
route pre-flight checks `tei`'s `/health` endpoint before accepting files.

```bash
docker compose exec tei curl -sf http://localhost:80/health
docker compose logs tei
```

Restart `tei` (`docker compose restart tei`) and retry the upload.

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

### Semantic matches are ignored

**Cause:** vector search failed and the query continued with BM25 only.

```bash
curl -s http://localhost:8001/metrics/system \
  | jq '.component_status.vector_store'
docker compose logs rag-server | grep "\[VECTOR\]"
```

`unhealthy` means the probe works but the last real search failed — read the
logged error, which is usually an unreachable embedding model. `unavailable`
means the extension or the index itself is broken; see
[the vector store section above](#the-vector-store-reports-unavailable).

This failure is easy to miss because it is quiet by design: a query embedding
failure is caught in `vector_retriever._aretrieve`, which logs and returns
`[]`, so hybrid search silently degrades to BM25-only and still answers —
just worse. `component_status.vector_store` also reports `unknown` (not
`unhealthy`) until a search has actually run in that process, so reading
`/metrics/system` right after startup won't catch it either. `just
demo-check` exists for exactly this: it forces a real query first, then
asserts `vector_store` reports `healthy` — run it before a demo rather than
trusting a cold `/metrics/system` read.

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

### “Judge … declares no execution_boundary” or “… which data_policy.allowed_judge_boundaries does not permit”

The corpus is declared confidential and the judge is not allowed to see it. Judge
prompts carry retrieved chunks and answers verbatim and are never masked, so this
refusal is deliberate and is not affected by `pii.enabled`.

| Cause | Fix |
|---|---|
| The `models.eval` entry for `active.eval` has no `execution_boundary` | Add one — unknown fails closed rather than being assumed safe |
| The judge's boundary is not in `data_policy.allowed_judge_boundaries` | Point `active.eval` at an allowed judge, or widen the allow-list deliberately |
| You are running `end_to_end` against a throwaway index that holds only the eval's own documents | Set `data_policy.eval_index_is_isolated: true` (or `EVAL_INDEX_IS_ISOLATED=true` for an ephemeral stack) |
| No document in the corpus is actually confidential | Set `data_policy.corpus_confidential: false` |
| You want judged metrics on your own documents | Start AWS private mode with `just llm-up`; it configures the in-boundary judge on the demo instance |

The gate reads the datasets and tier of *this run*, so `--datasets squad_v2 --tier
generation` can be allowed while `--datasets golden` is refused with the same
config. `just test-eval` is refused by default because `end_to_end` queries your
live index. See [Chapter 8](08-privacy-and-pii.md#where-evaluation-data-may-go).

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

`docker compose down -v` deletes the PostgreSQL volume, which holds the chunks
and their embeddings as well. `just down` does not. There is no built-in recovery; re-ingest the source files retained under
`data/indexed_documents`.

**Next:** [11. Limits and caveats](11-limits-and-caveats.md).
