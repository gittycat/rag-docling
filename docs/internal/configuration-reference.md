# Configuration reference

RAGBench configuration comes from four layers that partition, rather than
override, the surface: `config.yml` (model selection, retrieval, PII, prompts),
Docker secrets (API keys, DB credentials), environment variables (infra
plumbing: hosts, ports, log level), and compose-file overlays (which of the
above are wired into which containers for a given deployment tier). This
document is the exhaustive reference for all four, plus the config that is
parsed but never acted on, and the values that are hardcoded and not
configurable at all.

Two independent config loaders exist for `config.yml`: rag-server's
(`ModelsConfig` in `services/rag_server/infrastructure/config/models_config.py`)
and evals' (`services/evals/infrastructure/config/models_config.py`). They are
near-duplicate copies of the same Pydantic schema, both loading the same root
`config.yml`. Any divergence between the two copies is noted where it occurs.

There is also a third, unrelated config surface: `EvalConfig`, a dataclass in
`services/evals/evals/config.py` that controls eval *runs* — datasets, sample
counts, judge model, scoring weights. It is never loaded from root
`config.yml`; it comes from CLI arguments or an optional `--config` YAML file.
Do not confuse it with the `eval:` block below, which only sets citation
scope/format and abstention phrases.

## Configuration precedence

Resolution order, most to least authoritative:

1. **Docker secrets files** (`/run/secrets/<NAME>`) — the only source read for
   API keys and DB credentials. Both services' settings classes restrict
   `pydantic-settings` to `file_secret_settings` only, so a bare environment
   variable of the same name (e.g. `OPENAI_API_KEY` set outside
   `/run/secrets`) is silently ignored by this layer, even though
   `BaseSettings` would normally also check it.

2. **Runtime in-memory override** — rag-server exposes a
   `set_runtime_api_key()` store that takes precedence over the secrets file
   when set; the lookup path checks the runtime store before falling back to
   the secrets file. Evals' settings copy has no equivalent runtime-override
   mechanism — it is secrets-file only.

3. **`config.yml`** — loaded once via `ModelsConfig.load()`. For any model
   field flagged `requires_api_key: true`, the loader injects the resolved
   secret (from steps 1–2) into that entry's `api_key` field, merging
   provider/model selection with credentials into one config object.
   `config.yml` values themselves have no environment-variable override —
   there is no `${VAR}` substitution inside the file; it is parsed as plain
   YAML.

4. **Environment variables** (docker-compose `environment:` blocks) — apply to
   a disjoint set of concerns that `config.yml` does not cover at all: DB
   host/port, log level, worker concurrency, upload-size reporting, auth-token
   file path. There is no
   overlap/precedence conflict between `config.yml` and environment variables
   for any single setting — they partition the surface rather than layering
   on the same key. The Postgres server-side connection limit lives only in the
   compose `command:` value; there is no `config.yml` counterpart to conflict
   with it.

5. **Compose-file overlays** (`-f docker-compose.yml -f
   docker-compose.<tier>.yml`) — standard Compose merge semantics, later file
   wins per key; `!reset null` / `!reset []` explicitly clears a base value
   (for example `build: !reset null` in the cloud overlay to force `image:`
   instead, or `ports: !reset []` in the server overlay to unpublish ports).
   This layer only changes which env vars, secrets, and ports are wired to a
   container — it never touches `config.yml` contents, which is bind-mounted
   (not baked into the image) and therefore identical across tiers unless the
   mounted host file itself differs.

6. **Live in-place mutation via `PATCH /settings`** — rewrites
   `retrieval.enable_contextual_retrieval` in the mounted `config.yml` with an
   in-place regex line-replace that preserves comments and formatting, then
   resets the in-memory config cache. This is the only `config.yml` key
   writable at runtime through the application itself; every other key
   requires editing the file and waiting for (or triggering) a reload.

7. **Auto-reload on mtime** — the config manager checks the file's mtime on
   every access and reloads if it changed on disk. Manual edits to the
   bind-mounted `config.yml` take effect without a container restart;
   rag-server and task-worker share the same bind mount, so both pick up a
   change at the same time.

## Exhaustive `config.yml` reference

Root file: `config.yml` at the repo root. Roughly 123 leaf keys total: 73
across the 19 named model definitions under `models.*`, plus about 50 across
`active`, `eval`, `reranker`, `retrieval`, `vector_store`, `database`,
`chat_memory`, `prompts`, and `pii`. Every key is listed below, grouped by
top-level section.

### `models.inference.*`

Eight named model definitions (a ninth, `qwen-vllm`, is commented out and not
live). Each is resolved into the top-level `llm` object based on
`active.inference`, then consumed when building the LLM client.

| model key | provider | model | base_url | timeout (s) | keep_alive | requires_api_key |
|---|---|---|---|---|---|---|
| `gemma3-4b` | ollama | gemma3:4b | `http://host.docker.internal:11434` | 120 | 10m | — |
| `llama3-8b` | ollama | llama3:8b | `http://host.docker.internal:11434` | 120 | 10m | — |
| `gpt5-mini` | openai | gpt-5-mini | `https://api.openai.com/v1` | 120 | — | true |
| `claude-sonnet` | anthropic | claude-sonnet-4-20250514 | `https://api.anthropic.com` | 120 | — | true |
| `claude-opus` | anthropic | claude-opus-4-6 | `https://api.anthropic.com` | 120 | — | true |
| `gemini-pro` | google | gemini-pro | — | 120 | — | true |
| `deepseek-chat` | deepseek | deepseek-chat | — | 120 | — | true |
| `moonshot-v1` | moonshot | moonshot-v1-8k | `https://api.moonshot.cn/v1` | 120 | — | true |

`timeout` is an int (seconds); `requires_api_key` is a bool; all other fields
are strings. `gemini-pro` and `deepseek-chat` have no `base_url` set in
`config.yml` — they rely on the provider SDK's own default endpoint.

### `models.embedding.*`

Four named definitions, resolved into the top-level `embedding` object based
on `active.embedding`.

| model key | provider | model | base_url | requires_api_key | embed_batch_size |
|---|---|---|---|---|---|
| `nomic-embed` | ollama | nomic-embed-text:latest | `http://host.docker.internal:11434` | — | 64 |
| `openai-ada` | openai | text-embedding-ada-002 | `https://api.openai.com/v1` | true | not set (falls back to provider default, 100) |
| `openai-3-small` | openai | text-embedding-3-small | `https://api.openai.com/v1` | true | 100 |
| `openai-3-large` | openai | text-embedding-3-large | `https://api.openai.com/v1` | true | not set (falls back to provider default, 100) |

Effective batch size is `embed_batch_size` from the entry if present,
otherwise a per-provider default (64 for ollama, 100 for openai) baked into
the embeddings module. Two of the four openai entries omit the field and
silently rely on that fallback.

### `models.eval.*`

Four named definitions, resolved into the top-level `eval` object (merged
with the `eval.*` settings block below) based on `active.eval`. This is the
model used both for the citation-behavior config surfaced to clients and, when
not overridden by the separate `EvalConfig` CLI/YAML surface, as the eval
LLM judge.

| model key | provider | model | requires_api_key |
|---|---|---|---|
| `claude-sonnet` | anthropic | claude-sonnet-4-20250514 | true |
| `claude-opus` | anthropic | claude-opus-4-5-20251101 | true |
| `gpt5-mini` | openai | gpt-5-mini | true |
| `gpt5-2` | openai | gpt-5.2 | true |

### `models.reranker.*`

Three named definitions, resolved into `reranker.model` / `reranker.top_n`
(merged with the `reranker.*` settings block below) based on
`active.reranker`.

| model key | model | top_n |
|---|---|---|
| `minilm-l6` | cross-encoder/ms-marco-MiniLM-L-6-v2 | 5 |
| `bge-reranker-large` | BAAI/bge-reranker-large | 5 |
| `bge-reranker-base` | BAAI/bge-reranker-base | 5 |

`top_n` here is effectively dead at runtime — see Dead configuration below.

### `active.*`

| key | type | default | effect |
|---|---|---|---|
| `active.inference` | str | `gpt5-mini` | selects `models.inference.<key>` as the live `llm` config |
| `active.embedding` | str | `nomic-embed` | selects `models.embedding.<key>` as the live `embedding` config |
| `active.eval` | str | `gpt5-2` | selects `models.eval.<key>` as the live `eval` model config |
| `active.reranker` | str | `minilm-l6` | selects `models.reranker.<key>` as the live `reranker` config |

### `eval.*` (non-model-specific evaluation settings)

| key | type | default | effect |
|---|---|---|---|
| `eval.citation_scope` | `"retrieved"` \| `"explicit"` | `retrieved` | whether eval treats all retrieved chunks as citations, or only explicitly cited ones. Read by rag-server's own inference path; separately dead on the evals-runner warning path — see Dead configuration below |
| `eval.citation_format` | `"numeric"` | `numeric` | citation style appended to generation prompts |
| `eval.abstention_phrases` | list of 6 strings | see `config.yml` | phrases meant to detect "no answer" responses for eval scoring; exposed via the API but not actually used by the evals abstention metric — see Dead configuration below |

### `reranker.*` (non-model-specific reranker settings)

| key | type | default | effect |
|---|---|---|---|
| `reranker.enabled` | bool | `true` | master on/off switch for reranking, checked in the inference pipeline and reflected in health/config endpoints |

### `retrieval.*`

| key | type | default | effect |
|---|---|---|---|
| `retrieval.top_k` | int | 10 | number of chunks retrieved before reranking |
| `retrieval.enable_hybrid_search` | bool | `true` | BM25 + vector RRF fusion vs. vector-only retrieval |
| `retrieval.rrf_k` | int | 60 | Reciprocal Rank Fusion constant |
| `retrieval.enable_contextual_retrieval` | bool | `false` | Anthropic-style contextual chunk prefixing at ingestion time; the only `config.yml` key that is runtime-toggleable via `PATCH /settings`, which rewrites this key in the mounted `config.yml` |
| `retrieval.contextual_concurrency` | int | 8 | max concurrent LLM calls during contextual prefix generation |

The Pydantic field default for `enable_contextual_retrieval` actually differs
between the two schema copies (`True` in rag-server's schema, `False` in
evals'), but `config.yml` always sets it explicitly to `false`, so the
schema-default divergence never surfaces in practice — a dataclass default
only matters if the key were absent from the file.

### `vector_store.*`

| key | type | default | effect |
|---|---|---|---|
| `vector_store.dimension` | int | 768 | output dimension of the active embedding model; must match the `vector(768)` declaration of `document_chunks.embedding` in `init.sql` |

`dimension` is not a knob that reshapes anything at runtime — the column type is
the real constraint, and `init.sql` does not re-run against an existing volume.
The value is read by `probe_vector_index()` to build its probe vector, which is
what makes a divergence between config and schema visible in
`/metrics/system`'s `component_status.vector_store` rather than only at query
time. Changing embedding models means recreating the schema and re-ingesting
every document.

### `database.*`

| key | type | default | effect |
|---|---|---|---|
| `database.pool_size` | int | 10 | SQLAlchemy async engine persistent pool size |
| `database.max_overflow` | int | 20 | SQLAlchemy burst capacity above the persistent pool |
| `database.pool_pre_ping` | bool | `true` | health-check a pooled connection before handing it out |
| `database.pool_recycle` | int | 3600 | seconds before a pooled connection is recycled |

### `chat_memory.*`

| key | type | default | effect |
|---|---|---|---|
| `chat_memory.persistent.max_sessions` | int | 500 | LRU cap on the in-RAM cache fronting the Postgres chat store |
| `chat_memory.persistent.ttl_seconds` | int | 3600 | idle-eviction timeout for that cache |
| `chat_memory.temporary.max_sessions` | int | 200 | LRU cap on the cache for DB-less temporary sessions |
| `chat_memory.temporary.ttl_seconds` | int | 1800 | idle-eviction timeout for temporary sessions — note this cache is the *only* copy of that session's history, so eviction ends the conversation, not just the cache entry |

### `prompts.*`

| key | type | default | effect |
|---|---|---|---|
| `prompts.system` | str (multiline) | see `config.yml` | system prompt used for all LLM interactions |
| `prompts.context` | str (multiline, has `{context_str}` / `{citation_instructions}` placeholders) | see `config.yml` | RAG grounding instructions template |
| `prompts.citation_instructions.numeric` | str | see `config.yml` | appended to the context prompt when numeric citations are enabled |
| `prompts.condense` | str or null | `null` | custom question-condensation prompt; `null` uses the LlamaIndex default |
| `prompts.contextual_prefix` | str (multiline, has `{document_name}` / `{document_type}` / `{chunk_preview}` placeholders) | see `config.yml` | prompt used to generate contextual chunk prefixes at ingestion |

### `pii.*`

| key | type | default | effect |
|---|---|---|---|
| `pii.enabled` | bool | `false` | master toggle for the PII masking tier (cloud-generation path); also read by evals' own PII config copy |
| `pii.allow_cloud_judge` | bool | `false` | opt-out allowing a cloud LLM judge to run against a PII-sensitive corpus; only evals actually branches on this — rag-server's copy declares the field but does not enforce it |
| `pii.entities` | list of 7 strings | see `config.yml` | Presidio entity types to detect and mask |
| `pii.masking_strategy` | `"tokens"` | `tokens` | dead — only one literal value is legal and nothing branches on it, see below |
| `pii.token_format` | str | `[[[{entity_type}_{index}]]]` | template for mask tokens |
| `pii.score_threshold` | float (0–1) | 0.5 | Presidio detection confidence threshold |
| `pii.language` | str | `en` | spaCy/Presidio language code |
| `pii.spacy_model` | str | `en_core_web_md` | spaCy NLP model used by the Presidio analyzer |
| `pii.gliner.enabled` | bool | `false` | registers GLiNER as a second-opinion NER recognizer |
| `pii.gliner.model_name` | str | `urchade/gliner_multi_pii-v1` | GLiNER model id |
| `pii.gliner.threshold` | float | 0.4 | GLiNER confidence threshold |
| `pii.gliner.map_location` | str or null | `null` | force CPU/GPU placement for GLiNER |
| `pii.gliner.load_onnx_model` | bool | `false` | use the ONNX backend, for CPUs without AVX2 |
| `pii.validation.enabled` | bool | `true` | validate that mask tokens survive the LLM round-trip |
| `pii.validation.max_retries` | int | 2 | dead — parsed but never read, see below |
| `pii.validation.alert_on_failure` | bool | `true` | dead — parsed but never read, see below |
| `pii.output_guardrails.enabled` | bool | `true` | scan the unmasked LLM response for leaked PII before it goes out |
| `pii.output_guardrails.block_on_detection` | bool | `false` | raise instead of returning the response with a warning when a leak is detected |
| `pii.session_mapping.max_sessions` | int | 500 | LRU cap on the in-RAM PII token-mapping cache |
| `pii.session_mapping.ttl_seconds` | int | 3600 | idle-eviction timeout for that cache |
| `pii.audit.enabled` | bool | `true` | gate on audit-log emission for mask/unmask operations |
| `pii.audit.log_level` | str | `INFO` | log level for the dedicated PII audit logger |

### Inspecting configuration

`just show-config` and `just show-config-full` both run against rag-server's
config loader/schema only (not evals'), with secret validation disabled so
they work without live API keys.

`show-config` (compact) prints: inference provider/model (+ `keep_alive` if
set), embedding provider/model, reranker model and `top_n` (or "disabled"),
and eval judge provider/model.

`show-config-full` additionally prints: inference provider, model, base_url,
timeout, keep_alive, and whether an API key is configured (never the key
itself); embedding provider, model, base_url; reranker enabled/model/`top_n`;
retrieval `top_k`, hybrid search on/off (+ RRF k if on), contextual retrieval
on/off; eval provider, model, citation scope, citation format, API-key
configured y/n; and PII enabled y/n with entities, spaCy model, score
threshold, and output-guardrail status if enabled.

Two things to know when reading either banner:

- The reranker `top_n` shown is the *configured* `config.yml` value, not what
  the reranker actually uses at runtime — see Dead configuration below.
- Neither banner prints `database.*` or `chat_memory.*` at all. Both sections
  are read and enforced elsewhere in the app, but they are invisible to both
  `just show-config` and `just show-config-full`.

## Environment variables

Application environment variables, read via `os.getenv`/`os.environ` in
Python or `$env/dynamic/private` in the webapp.

| variable | purpose | default | set by |
|---|---|---|---|
| `DATABASE_HOST` | Postgres host | `postgres` | `docker-compose.yml` (rag-server, task-worker); `.bench.yml` (`postgres-bench`) |
| `DATABASE_PORT` | Postgres port | `5432` | `docker-compose.yml`, `.bench.yml` |
| `DATABASE_NAME` | Postgres database name | `ragbench` | `docker-compose.yml`, `.bench.yml` |
| `SHARED_UPLOAD_DIR` | shared tmp directory for uploads between rag-server and task-worker | `/tmp/shared` | `docker-compose.yml` (both services) |
| `LOG_LEVEL` | log verbosity | `INFO` for the core logger, `WARNING` for the task worker and evals API | `docker-compose.yml` sets `WARNING` everywhere; the cloud overlay re-sets `WARNING` again (a no-op) |
| `MAX_UPLOAD_SIZE` | max upload size in MB, surfaced via the config API | `80` | `docker-compose.yml` (rag-server, task-worker, and webapp — the webapp's copy is unread, see the auth-token gap below) |
| `USE_CACHED_RERANKER` | when truthy, sets `HF_HUB_OFFLINE=1` to skip Hugging Face network calls for a pre-cached reranker | falsy (unset) | `docker-compose.yml` (`true`, rag-server + task-worker) |
| `OLLAMA_URL` | Ollama endpoint for metrics/cost lookups | `http://host.docker.internal:11434` | not set in `docker-compose.yml` (relies on the default); set only in test fixtures |
| `WORKER_CONCURRENCY` | concurrent document-processing claim loops, capped by a hardcoded ceiling of 8 | `2` | `docker-compose.yml` (task-worker only) |
| `RAG_SERVER_URL` | URL evals/webapp use to call rag-server | `http://localhost:8001` | `docker-compose.yml` (webapp, evals) |
| `EVALS_SERVICE_URL` | URL the webapp proxies `/api/eval/*` to | `http://localhost:8002` | `docker-compose.yml` (webapp) |
| `ORIGIN` | CSRF-safe origin for SvelteKit form actions, consumed by `@sveltejs/adapter-node` | none | `docker-compose.yml` (webapp: `http://localhost:8000`); overridden via `WEBAPP_ORIGIN` in the cloud overlay |
| `RAG_SERVER_AUTH_TOKEN_FILE` | path to the bearer-token secret file for server-tier auth | unset (auth disabled) | `docker-compose.server.yml` (rag-server, webapp) |
| `RAG_SERVER_AUTH_TOKEN` | direct token value, used by the webapp only as a fallback if `_FILE` is unset or unreadable | unset | never set by any compose file — a dead code path in practice |
| `SERVER_DOMAIN` | TLS/domain name for the reverse proxy, substituted by Caddy itself | `localhost` | `docker-compose.server.yml` (caddy) |
| `EMBEDDING_MODEL` | embedding model name surfaced in the models-info endpoint | `unknown` | never set by any compose file — always resolves to `"unknown"` in every real deployment; only set in test fixtures |
| `WEBAPP_ORIGIN` | overrides the webapp's `ORIGIN` in the cloud tier (compose-level substitution only) | `http://localhost:8000` | host shell / `.env`, consumed by `docker-compose.cloud.yml` |
| `OLLAMA_HOST` | overrides the `extra_hosts` mapping for the cloud tier (compose-level substitution only) | `host-gateway` | host shell / `.env`, consumed by `docker-compose.cloud.yml` |
| `REGISTRY`, `VERSION` | container registry/tag for cloud deploys (compose-level substitution only) | `latest` | host shell / `.env`, consumed by `docker-compose.cloud.yml` |

Test-only environment variables (`DATABASE_HOST`, `DATABASE_PORT`,
`DATABASE_NAME`, `OLLAMA_URL`, `EMBEDDING_MODEL`, `LLM_MODEL`,
`ANTHROPIC_API_KEY`) are set directly by test fixtures and are not part of the
runtime config surface described here.

Secrets-backed settings (API keys, DB credentials) are technically
env-var-shaped — `pydantic-settings` normally also checks env vars as a
fallback source — but both services restrict the source list to the secrets
file only, so a plain environment variable of the same name is ignored. See
Docker secrets below and item 1 of the precedence order above.

## Docker secrets

Declared once per compose file's top-level `secrets:` block, pointing at
`secrets/<NAME>` on the host.

| secret | mounted by | container path | read by |
|---|---|---|---|
| `OPENAI_API_KEY` | rag-server, task-worker, evals (base, bench, and server tiers) | `/run/secrets/OPENAI_API_KEY` | rag-server and evals settings modules |
| `ANTHROPIC_API_KEY` | rag-server, task-worker, evals (base, bench, and server tiers) | `/run/secrets/ANTHROPIC_API_KEY` | rag-server and evals settings modules |
| `POSTGRES_SUPERUSER` | postgres (base and bench) | `/run/secrets/POSTGRES_SUPERUSER` | the official Postgres entrypoint via `POSTGRES_USER_FILE`, and the roles-init script / healthcheck — not read by rag-server or evals Python |
| `POSTGRES_SUPERPASSWORD` | postgres (base and bench) | `/run/secrets/POSTGRES_SUPERPASSWORD` | same as above, via `POSTGRES_PASSWORD_FILE` |
| `RAG_SERVER_DB_USER` | rag-server, task-worker, postgres (base, bench, and server tiers) | `/run/secrets/RAG_SERVER_DB_USER` | rag-server settings |
| `RAG_SERVER_DB_PASSWORD` | rag-server, task-worker, postgres (base, bench, and server tiers) | `/run/secrets/RAG_SERVER_DB_PASSWORD` | rag-server settings |
| `RAG_SERVER_AUTH_TOKEN` | rag-server, webapp (server tier only) | `/run/secrets/RAG_SERVER_AUTH_TOKEN` | rag-server auth module (via `RAG_SERVER_AUTH_TOKEN_FILE`); webapp server hooks |

**Gap: three providers are unusable out of the box.** Both settings classes
declare `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, and `MOONSHOT_API_KEY` as
recognized secrets, with accessor functions for each, and `config.yml` offers
model definitions for `gemini-pro`, `deepseek-chat`, and `moonshot-v1`. But
none of the five compose files declares any of these three as a Docker
secret. Setting `active.inference` to one of them will pass YAML validation
but fail provider-requirement validation at boot, unless an operator manually
creates a `secrets/<NAME>` file and edits the relevant compose file
themselves — there is no supported path today for selecting these providers.

## Compose overlays

Base file: `docker-compose.yml`.

| file | relation to base | key differences | intended use |
|---|---|---|---|
| `docker-compose.yml` | base | webapp, rag-server, postgres, task-worker, evals; `public`/`private` bridge networks; all ports published to host | local development / default `just up` |
| `docker-compose.bench.yml` | standalone stack — own `-bench` service names, networks, and volumes, but shares the `secrets/` directory and `config.yml` mount | `postgres-bench` uses `tmpfs` for its data directory (ephemeral, wiped on stop); `rag-server-bench` published on host port 8003 instead of 8001; no `evals` or `webapp` services at all; `config.yml` mounted read-only | ephemeral benchmark runs, isolated from the main stack's data |
| `docker-compose.ci.yml` | fully independent stack, not an overlay — no `services:` in common with the base | own network for Forgejo + runner; nothing shared with the base | self-hosted CI/CD infrastructure, unrelated to the RAG application; run with its own `-f` flag, never combined with the base |
| `docker-compose.cloud.yml` | overlay (`-f docker-compose.yml -f docker-compose.cloud.yml`) | replaces `build:` with `image: <name>:${VERSION:-latest}` for webapp, rag-server, and task-worker; parameterizes the webapp's `ORIGIN` via `WEBAPP_ORIGIN`; parameterizes the Ollama host via `OLLAMA_HOST` | deploying pre-built images to a cloud host instead of building on-target |
| `docker-compose.server.yml` | overlay | adds a Caddy reverse-proxy service (automatic HTTPS via `SERVER_DOMAIN`); unpublishes ports on webapp, rag-server, and evals so only Caddy is internet-facing; adds the `RAG_SERVER_AUTH_TOKEN` secret and `RAG_SERVER_AUTH_TOKEN_FILE` environment variable to rag-server and webapp, turning on bearer-token auth | confidential-compute VM or thin-client tier, single public entrypoint through Caddy |

`just deploy` for the server or cloud environment runs `docker compose -f
docker-compose.yml -f docker-compose.<env>.yml up -d --build`.

## Runtime mutation and mtime auto-reload

Two mechanisms change configuration without an operator manually restarting a
container:

**`PATCH /settings`** is the only supported runtime-mutation endpoint. It
handles exactly one key, `retrieval.enable_contextual_retrieval`, and does an
in-place regex line-replace on the mounted `config.yml` that preserves the
rest of the file's comments and formatting, then resets the in-memory config
cache so the new value takes effect on the next request. No other key is
writable through the application itself.

**mtime auto-reload** applies to every key. The config manager checks the
bind-mounted `config.yml`'s file modification time on every access; if it
changed since the last load, the file is re-parsed and the in-memory config is
replaced. Because rag-server and task-worker share the same bind mount, a
manual edit to the host's `config.yml` — whether by hand or by the `PATCH
/settings` regex-replace above — takes effect in both services without a
restart. This is the mechanism that makes hand-editing `config.yml` a
supported way to change configuration in a running stack.

## Dead configuration

These keys are parsed by the config schema and, in most cases, even
surfaced through an API response or the config-inspection banners — but
nothing in the running system actually acts on the value. Changing them in
`config.yml` has no effect on behavior.

**`models.reranker.<name>.top_n`** (all three named rerankers set it to `5`)
looks like it controls how many chunks the reranker keeps. What actually
happens: it is resolved into `reranker.top_n` and even round-trips through the
inference config dict under the key `reranker_top_n` — but the reranker's
actual instantiation ignores that value completely and computes its own top_n
as `max(5, retrieval_top_k // 2)`. With the current `retrieval.top_k` of 10,
the live reranker keeps 10 chunks, not the 5 configured. `just show-config`
and `just show-config-full` both print the configured `5`, which is
misleading — it is not what runs. An operator should treat the
`models.reranker.*.top_n` value in `config.yml` as informational only, and if
they want to actually change how many chunks are kept post-rerank, they need
to change `retrieval.top_k` (which moves the formula's result) or edit the
formula itself in code.

**`pii.masking_strategy`** looks like it selects between masking approaches.
What actually happens: the schema only permits one literal value (`tokens`)
and nothing in the codebase branches on it — it is parsed and immediately
ignored. It is also not shown by either config-inspection banner. There is
nothing for an operator to do here except understand that no other masking
strategy exists or is selectable.

**`pii.validation.max_retries`** and **`pii.validation.alert_on_failure`**
look like they bound and alert on failures of the PII round-trip validation
step. What actually happens: both are parsed into the config object and never
read anywhere else. The fuzzy-recovery routine they should govern runs
unconditionally exactly once per response, with no retry loop keyed on
`max_retries` and no alerting call tied to `alert_on_failure`. An operator
changing either value in `config.yml` changes nothing about retry behavior or
alerting — there is no alerting path to enable at all today.

**`eval.abstention_phrases`** looks like it configures which phrases the eval
framework treats as a refusal-to-answer for scoring purposes. What actually
happens: it is plumbed into the config object and exposed via the API, but the
evals service's own abstention metric never reads it — every call site
constructs the metric without passing the config value in, so the metric
falls back to its own hardcoded phrase list baked into the metric module. An
operator editing `eval.abstention_phrases` in `config.yml` changes nothing
about actual eval scoring; the phrase list to edit is the hardcoded constant
in the evals codebase, not this config key.

**`eval.citation_scope`**, specifically on the evals-runner warning path, is
a narrower case: this key genuinely is read and honored by rag-server's own
inference pipeline (it is not dead in general). But the evals runner also
tries to read it back from rag-server's config API, to warn when a local eval
run's citation-scope assumption diverges from the server's actual setting.
That read goes through the models-info response, which has no `eval` key at
all — so the runner's lookup always returns an empty object, and the
divergence-warning logic always falls back to comparing against the hardcoded
default (`"retrieved"`) rather than the server's real configured value. The
warning can therefore fail to fire, or fire on a false premise, regardless of
what `eval.citation_scope` is actually set to in `config.yml`.

## Hardcoded values that are not configurable

The following operationally meaningful values have no `config.yml` key at
all — they are Python (or compose) constants that must be changed in code to
change behavior.

| location | value | why it matters |
|---|---|---|
| Core LlamaIndex settings init (`core/config.py`, around lines 105–106) | `chunk_size = 500`, `chunk_overlap = 50` | The chunking parameters for ingestion — one of the highest-leverage RAG tuning knobs — are hardcoded at global-settings initialization, not exposed in `config.yml` at all. |
| Task worker module constants | `POLL_INTERVAL = 1.0`, `MAX_ATTEMPTS = 3`, `STUCK_TIMEOUT = 3600`, `STUCK_CHECK_INTERVAL = 60`, `RETRY_DELAYS = [5, 15, 60]`, `MAX_WORKER_CONCURRENCY = 8` | Six constants governing the async document-processing worker's polling, retries, and stuck-task recovery — none are in `config.yml`. `MAX_WORKER_CONCURRENCY` silently caps the `WORKER_CONCURRENCY` environment variable, which is surprising if undocumented; `STUCK_TIMEOUT` directly determines how long a crashed task blocks reprocessing of its document. |
| Inference pipeline reranker call | `top_n = max(5, retrieval_top_k // 2)` | The formula that silently overrides `config.yml`'s `models.reranker.*.top_n` — see Dead configuration above. Neither the `5` floor nor the `// 2` divisor is a config key. |
| Inference pipeline context-window budgeting | roughly a 50% chat-history / 40% context / 10% response split, with a `3000`-token fallback when LLM metadata introspection fails | An operator switching LLM providers (different context windows) has no way to tune this split without a code change. The 3000-token fallback is used silently whenever a provider's context-window metadata cannot be determined. |
| Ingestion contextual-prefix preview | `chunk_preview = node.get_content()[:400]` | The 400-character chunk preview length fed into the (paid) contextual-retrieval prompt is a magic number affecting both prompt quality and per-request token cost. |
| Embeddings module | `_DEFAULT_BATCH_SIZE = {"ollama": 64, "openai": 100}` | Per-provider fallback batch size used whenever a model definition omits `embed_batch_size` — true today for `openai-ada` and `openai-3-large`. An operator editing those entries would not know the effective batch size without reading the code. |
| Provider API-key validation calls (five call sites) | `httpx.AsyncClient(timeout=10.0)` | A fixed 10-second timeout for validating a provider API key at boot, independent of the per-model `timeout` set in `config.yml`. |
| rag-server health route | an inline dict of roughly 14 hardcoded model price entries | Duplicates — with different, and drifting, values — the separate cost tables in the evals CLI config. Two independent hardcoded pricing tables exist for overlapping sets of models, neither sourced from `config.yml` or an external pricing feed. |
| Evals CLI config (`evals/config.py`) | default scoring weights (accuracy, faithfulness, citation, retrieval, cost, latency) and per-model USD-per-token cost tables | Eval scoring weights and model costs are Python constants, editable only through the separate `EvalConfig.from_yaml()` / CLI surface described in the introduction above — not through `config.yml`. |
| Postgres service compose command | `max_connections=200` | The only place that sets the Postgres server-side connection limit. It has no `config.yml` counterpart — the application-side pool (`database.pool_size` + `database.max_overflow`) must be kept under it by hand. |
| Auth module | no token rotation or expiry; a single static secret file | Adequate for the stated scope, but there is no TTL or rotation configuration for `RAG_SERVER_AUTH_TOKEN` at all. |
