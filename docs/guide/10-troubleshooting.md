# Troubleshooting

Symptom, likely cause, how to check, and the fix — grouped by where in the
system's lifecycle the problem shows up.

## Startup

### A service exits immediately, or `docker compose up` reports a missing secret

**Likely cause**: one of the required secret files under `secrets/` doesn't
exist. Docker Compose secrets are declared as `file: secrets/<NAME>` — if the
source file is missing, the container that mounts it cannot start.

**Check**:
```bash
ls secrets/
```
Confirm `POSTGRES_SUPERUSER`, `POSTGRES_SUPERPASSWORD`, `RAG_SERVER_DB_USER`,
`RAG_SERVER_DB_PASSWORD` all exist (required for every deployment), plus
`OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY` if your active models need them.

**Fix**: create the missing file(s) — see "Secrets you must create before first
start" in the Getting Running chapter — then `just up` again.

### rag-server or task-worker exits with "Ollama is not reachable"

**Likely cause**: `active.inference` or `active.embedding` in `config.yml`
points at an `ollama`-provider model, but Ollama isn't running or isn't
reachable at the configured `base_url` (default
`http://host.docker.internal:11434`). The app checks this at startup
(`check_ollama_reachable`) and calls `sys.exit(1)` with a clear message rather
than starting in a broken state.

**Check**:
```bash
curl -sf http://localhost:11434/api/version
```
If this fails, Ollama itself isn't up. If it succeeds but the container still
fails, check that the model's `base_url` in `config.yml` actually matches how
your Docker setup reaches the host (this can differ between Docker Desktop,
OrbStack, and Podman).

**Fix**: start Ollama (`ollama serve`, or open the Ollama app), then restart
the affected services (`docker compose restart rag-server task-worker`). You
can also catch this before it happens with `just preflight`, which runs the
same check ahead of `just up`/`just deploy`.

### rag-server exits with "Reranker model not found in local cache"

**Likely cause**: reranking is enabled (`reranker.enabled: true`, the default)
and the active reranker model was never pre-fetched into
`.cache/huggingface`. The boot-time check (`ensure_reranker_model_cached`)
deliberately fails fast here — `HF_HUB_OFFLINE=1` is set whenever
`USE_CACHED_RERANKER` is true (which it is in the base compose file), so the
container will not silently fall back to a live Hugging Face download.

**Check**:
```bash
ls .cache/huggingface
```
Look for a directory matching the active reranker model name (default
`cross-encoder/ms-marco-MiniLM-L-6-v2`).

**Fix**:
```bash
just init
```
then restart. If you've changed `active.reranker` to a different model, run
`just init MODEL=<huggingface-model-id>` for that model instead.

### rag-server exits with "Embedding dimension mismatch"

**Likely cause**: you switched `active.embedding` to a model with a different
output dimension than the one used to build the existing ChromaDB collection
(e.g. moving between `nomic-embed` and an OpenAI embedding model). This check
(`check_embedding_dimension_match`) runs at startup whenever the ChromaDB
collection already holds vectors — it peeks one stored vector, measures its
dimension, and compares it against a live probe embedding from the currently
active model.

**Check**: the startup log will state both dimensions directly, e.g. "stores
768-dimensional vectors, but the active embedding model ... produces
1536-dimensional vectors."

**Fix**: either switch `active.embedding` back to the model that built the
existing index, or delete and fully re-ingest the corpus under the new
embedding model. There is no in-place re-embedding path — this is a hard
either/or.

### A cloud model choice fails at boot even though the API key file exists

**Likely cause**: you set `active.inference` (or `active.eval`) to
`gemini-pro`, `deepseek-chat`, or `moonshot-v1`. The application code knows how
to read `GOOGLE_API_KEY`/`DEEPSEEK_API_KEY`/`MOONSHOT_API_KEY`, but no compose
file declares any of the three as a Docker secret — there is no supported way
to deliver these three keys into the containers without hand-editing the
compose file yourself to add a `secrets:` entry and mount.

**Check**: `docker compose config` will show you the secrets actually wired to
each service; confirm the key you need isn't in that list.

**Fix**: pick a different model (`gemma3-4b`, `llama3-8b`, `gpt5-mini`,
`claude-sonnet`, `claude-opus` are all fully wired), or edit the relevant
compose file to add the missing secret declaration and container mount
yourself.

### rag-server refuses to boot after enabling PII masking

**Likely cause 1 — cloud embedding + PII**: `pii.enabled: true` is rejected at
config-load time if the active embedding provider isn't local (`ollama`).
Masking only covers the generation path by design; the embedding path and
reranker always stay local, so pairing `pii.enabled: true` with a cloud
embedding model is a hard invariant violation, not a soft warning.

**Likely cause 2 — GLiNER enabled but not installed**: `pii.gliner.enabled:
true` is rejected at boot if the `gliner` package isn't importable in the
image. This also fails fast rather than silently falling back to spaCy-only
detection.

**Check**: the startup error states which of the two conditions tripped,
naming either the embedding provider or the missing `gliner` package.

**Fix**: for the first case, set `active.embedding` to an Ollama-backed model
before enabling `pii.enabled`. For the second, either rebuild the image with
`--build-arg INSTALL_GLINER=true` (or `uv sync --extra gliner` locally), or set
`pii.gliner.enabled: false`.

## Ingestion

### Uploaded documents stay stuck in "processing" indefinitely

**Likely cause**: the task worker that was processing the document crashed or
was killed mid-task, leaving a `job_tasks` row stuck in `processing` state.
The worker runs a background check every 60 seconds
(`check_stuck_tasks`/`STUCK_CHECK_INTERVAL`) that resets any task that has been
`processing` for more than one hour (`STUCK_TIMEOUT = 3600` seconds) back to
`pending` so another worker claim picks it up — unless it has already hit its
retry limit (`max_attempts`), in which case it's marked `error` instead with
the message "Task exceeded maximum retry attempts (stuck worker)."

**Check**:
```bash
docker compose logs task-worker | grep -i "stuck"
```
A log line like `[WORKER] Reset N stuck task(s) to pending` confirms the
recovery mechanism ran. You can also query task status directly:
```bash
curl http://localhost:8001/tasks/<batch_id>/status
```

**Fix**: for a task genuinely stuck less than an hour, just wait — the
one-hour reset is automatic. If a task keeps failing and eventually lands in
`error`, check `docker compose logs task-worker` around the time it was
processing for the underlying exception, then re-upload the document.

### Upload fails with a 503 mentioning Ollama

**Likely cause**: the active embedding model is Ollama-backed and Ollama isn't
reachable at ingestion time (as opposed to at container boot — this can happen
if Ollama was up when the container started but has since stopped).

**Check**:
```bash
curl -sf http://localhost:11434/api/version
```

**Fix**: restart Ollama, then retry the upload. The Upload page in the webapp
shows a dedicated alert for this specific failure mode.

## Query

### Chat answers seem to ignore keyword matches that should be an easy hit

**Likely cause**: BM25 (the keyword half of hybrid search, via `pg_textsearch`)
failed for that query and degraded silently. The BM25 retriever catches any
exception around its SQL search, logs a warning, and returns an empty result
list rather than raising — so the query proceeds with vector-only results
fused through RRF, with no error surfaced to the API caller or the chat UI at
all. This is easy to miss because nothing in the response indicates it
happened.

**Check**:
```bash
docker compose logs rag-server | grep "\[BM25\] Search failed"
```
If you see this, BM25 is broken for some or all queries. A broken or missing
`idx_chunks_bm25` index, or a Postgres-side error in the `pg_textsearch`
extension, is the usual cause.

**Fix**: inspect the logged exception for the specific SQL error, then check
that the `pg_textsearch` extension and the `idx_chunks_bm25` index exist and
are valid in the `document_chunks` table. If hybrid search is not critical to
your use case in the short term, you can set `retrieval.enable_hybrid_search:
false` in `config.yml` to fall back to vector-only search explicitly (an
explicit, known-quantity degrade rather than a silent, intermittent one) while
you investigate.

### A query returns a generic connection error with no further detail

**Likely cause**: could be a downed Ollama instance (if the active LLM is
Ollama-backed), a cloud provider outage/timeout, or a genuine backend crash —
the chat UI's error handling doesn't distinguish these; a failed stream just
appends `[Error: Connection interrupted]` to the partial message.

**Check**:
```bash
docker compose logs rag-server -f
```
and reissue the same query to see the underlying exception in real time.

**Fix**: depends on what the logs show — restart Ollama if that's the
provider, check your cloud API key/quota if it's a cloud model, or check
`docker compose ps` for a crashed rag-server container.

## Eval

### Starting an eval run returns HTTP 409 "An eval job is already running"

**Likely cause**: the eval service only allows one active job at a time. If a
previous run is still `queued` or `running` (including one you forgot about,
or one that's hung), a new `POST /eval/runs` call is rejected outright rather
than queued.

**Check**:
```bash
curl http://localhost:8002/eval/runs/active
```
This tells you the currently active job's id and status.

**Fix**: wait for the active job to finish, or cancel it first:
```bash
curl -X DELETE http://localhost:8002/eval/runs/active
```
then retry your run.

### An eval run's judge-dependent metrics look sparse or incomplete

**Likely cause**: the eval judge model failed on some questions (timeout,
rate limit, malformed response). Per this project's design, judge failures on
individual questions are excluded from that metric's average rather than
scored as 0 — so a bad run doesn't silently show as "the model did poorly," it
shows as "fewer samples contributed to this metric's average" instead.

**Check**: the run's stored JSON result (under `data/eval_runs` on the host) —
compare `sample_size` for the affected metric against the run's overall
question count. The dashboard does not surface `sample_size` anywhere in the
UI; you need the raw run detail or CLI to see it.

**Fix**: check `docker compose logs evals` around the run's timeframe for
judge-call errors (rate limits, timeouts). If the judge provider is
unreliable, consider re-running with a different `active.eval` model or after
the provider issue clears.

## Performance

### Ingestion of a document set is much slower than expected

**Likely cause**: contextual retrieval (if enabled,
`retrieval.enable_contextual_retrieval: true`) issues one LLM call per chunk to
generate a contextual prefix before embedding — this is the dominant cost of
ingestion when it's on, and is proportional to your chunk count and the LLM's
latency.

**Check**:
```bash
just show-config-full
```
Look at the "Retrieval" section for whether contextual retrieval is enabled.

**Fix**: this is expected behavior, not a bug, if contextual retrieval is on —
budget ingestion time accordingly, or turn it off
(`retrieval.enable_contextual_retrieval: false`, also toggleable live via the
Settings page or `PATCH /api/settings`) if you don't need the quality/recall
improvement it's meant to provide. See the Configuration Tour and Experiment
Cookbook chapters for the quality trade-off.

### First query after startup is noticeably slower than subsequent ones

**Likely cause**: this is expected if the reranker model needed to load from
disk into memory on its first use — the postprocessor is created and used
lazily rather than during the earlier boot-time cache check, which only
verifies the model files exist on disk. Fetching the model into the cache with
`just init` avoids a network download, but does not avoid the one-time
in-process model load.

**Check**:
```bash
docker compose logs rag-server | grep -i rerank
```

**Fix**: nothing to fix — this is a one-time warm-up cost per container
lifetime. If you need consistently low first-query latency, keep the
container running rather than restarting it between sessions.

### A stopped-and-restarted stack seems to be missing recent chat history or documents

**Likely cause**: you ran `docker compose down -v` instead of `docker compose
down` (or `just down`, which does not pass `-v`). The `-v` flag deletes named
Docker volumes, including `postgres_data` (all chat/session/document metadata)
and `chroma_data` (the vector index).

**Check**:
```bash
docker volume ls | grep -E "postgres_data|chroma_data"
```
If these don't exist, they were removed.

**Fix**: there is no recovery for a destroyed named volume in this project —
no backup mechanism exists for `postgres_data` or `chroma_data`. You will need
to re-ingest documents from scratch; original source files under
`data/indexed_documents` (a host bind mount, not a named volume) survive `-v`
and remain available to re-upload.
