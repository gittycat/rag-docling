# Retrieval

Audience: developers working on RAGBench. This covers the query-time
retrieval path — everything between a user's question arriving at
`/query` (or `/query/stream`) and a ranked, reranked set of chunks reaching
the LLM. Chat memory and the `condense_plus_context` chat engine are covered
in `chat-and-memory.md`.

## Query flow overview

A query request resets the token counter, loads the ChromaDB-backed vector
index and the current inference config, optionally masks the query and chat
history for PII, then builds a chat engine: chat memory, a hybrid retriever
(BM25 + vector, fused with RRF), a reranker postprocessor, and a PII-masking
postprocessor. The chat engine's `achat()` call is where condensation,
retrieval, reranking, and answer synthesis all happen. After the response
comes back, source nodes and the answer text are unmasked if PII masking was
active, sources are extracted for the response payload, and — if numeric
citations are requested — the answer text is scanned for bracket citations
that get mapped back to source indices.

A separate bypass path, used by the generation-tier eval, skips retrieval
entirely: it formats caller-supplied passages directly into a context block
and calls the LLM, with no retriever involved.

## BM25 via `pg_textsearch`

BM25 in this system is **not** a Python BM25 library (no `rank_bm25`,
no Whoosh) and **not** stock Postgres full-text search
(`tsvector`/`ts_rank`). It is the Timescale **`pg_textsearch`** extension,
which provides a real BM25 ranking function through a custom Postgres index
access method.

The index is created in `init.sql`:

```sql
CREATE INDEX idx_chunks_bm25 ON document_chunks
USING bm25 (content) WITH (text_config='english');
```

The text language config (`english`) is hardcoded in this DDL, not read from
`config.yml`.

The live retrieval query, issued by `PgSearchBM25Retriever`:

```sql
SELECT dc.id, dc.document_id, dc.chunk_index, dc.content,
       dc.metadata, dc.created_at, d.file_name, d.file_type, d.file_path,
       d.file_size_bytes, d.file_hash, d.uploaded_at,
       -(dc.content <@> to_bm25query(:query, 'idx_chunks_bm25')) as bm25_score
FROM document_chunks dc
JOIN documents d ON dc.document_id = d.id
WHERE dc.content <@> to_bm25query(:query, 'idx_chunks_bm25') < 0
ORDER BY dc.content <@> to_bm25query(:query, 'idx_chunks_bm25')
LIMIT :limit
```

The `<@>` operator is a distance operator: it returns **negative** BM25
scores, where lower (more negative) is a better match. The query therefore
orders ascending on the raw `<@>` value and negates it in the `SELECT` to
present a conventional positive score to callers. The query string is passed
as a bound parameter, not interpolated. `:limit` is the same `top_k` value
used for the vector leg.

The node text returned by this retriever is `dc.content`, which already
carries the contextual prefix when contextual retrieval is enabled — the
prefix is prepended to the chunk text before the row is written, so the BM25
index covers it (see `rag-pipeline.md`).

Any exception during this query is swallowed: the retriever logs an error,
records the failure for `/metrics/system` (`component_status.bm25`), and
returns an empty list rather than propagating the error (see "Failure
modes" below).

## Vector retrieval via ChromaDB

The vector leg is LlamaIndex's standard `VectorStoreIndex` retriever, backed
by a `ChromaVectorStore` wrapping a `chromadb.HttpClient`. Query embedding is
handled internally by LlamaIndex (`Settings.embed_model.get_query_embedding`)
— there is no custom embedding call in the retrieval code. The embedding
model is whatever `active.embedding` resolves to in `config.yml` (default
Ollama-served `nomic-embed-text`).

**No metadata filters are applied.** The vector retriever is constructed with
only `similarity_top_k` — no `MetadataFilters` of any kind are passed
anywhere in this retrieval path. A query has no way to narrow by document,
file type, upload date, or any other stored metadata field at retrieval time.

`similarity_top_k` for this leg equals `retrieval.top_k` from config — the
same value used to size the BM25 leg before fusion.

A startup check compares the currently configured embedding model's output
dimension against whatever is already stored in the Chroma collection, and
raises if they mismatch — this guards against silently corrupting the index
after switching embedding models mid-deployment.

## RRF fusion

Bare vector and BM25 result lists are combined with Reciprocal Rank Fusion.
Exact formula:

```
score(doc) = bm25_weight * (1 / (k + bm25_rank)) + vector_weight * (1 / (k + vector_rank))
```

Each result list is ranked independently (rank 1 = best), and a document
missing from one list simply contributes zero from that side rather than
being excluded. `k = 60` — sourced from `retrieval.rrf_k` in `config.yml`,
matching the hardcoded Python default of the same value.

**`bm25_weight` and `vector_weight` are both hardcoded to `1.0`** — plain,
unweighted RRF. These weights exist as constructor parameters on the fusion
retriever, but the factory function that builds it for live queries never
passes them through, and there is no `config.yml` key for either one. Making
BM25 and vector search contribute unequally to the fused ranking would
require new config plumbing, not a YAML edit.

Both legs run concurrently (via `asyncio.gather`) on the async query path;
the sync path runs them sequentially. After fusion, results are truncated to
`top_k` — the same value used to fetch each individual leg, so fusion
combines two `top_k`-sized lists and returns a `top_k`-sized result, not a
larger merged pool.

If `retrieval.enable_hybrid_search` is `false` (default `true`), fusion is
skipped entirely and the chat engine falls back to a vector-only retriever
via LlamaIndex's own `index.as_chat_engine(...)` path — a structurally
different code path, not just BM25 contributing zero weight.

## Cross-encoder reranker

The reranker is LlamaIndex's `SentenceTransformerRerank`, wrapping a
`CrossEncoder` from `sentence-transformers`. The active model is selected via
`active.reranker` in `config.yml`, default
`cross-encoder/ms-marco-MiniLM-L-6-v2`; `BAAI/bge-reranker-large` and
`BAAI/bge-reranker-base` are configured as alternatives but not active by
default.

**Loading is lazy but cached process-wide.** The `CrossEncoder` is not
constructed at process startup; the first query pays the model-load cost.
Once loaded, the instance is cached in a module-level global and reused for
every subsequent query in that process. This caching is not just an
optimization — it exists because `CrossEncoder` initialization is not
thread-safe under `transformers>=4.57` (its `init_empty_weights` context
manager races when invoked from multiple threads, producing meta-tensor
errors), so the model must be built exactly once per process and shared.

A separate boot-time check, independent of the lazy-load path above, fails
the process fast at startup if the reranker model isn't already present in
the local HuggingFace cache. It does this with a `local_files_only` snapshot
check and, if the model is missing, instructs the operator to pre-download it
(`just init`) into the local HuggingFace cache directory. This exists so that
a missing model surfaces as an immediate boot failure rather than as a
mysterious first-query latency spike or a deep-stack download failure.

**Effective `top_n`** is computed as:

```
top_n = max(5, retrieval_top_k // 2)
```

This is **not** read from the `top_n` value configured under the active
reranker in `config.yml` — that config value is parsed into the inference
config dict but never consulted by the code that actually constructs the
reranker postprocessor. With the current defaults (`retrieval.top_k = 10`),
the formula happens to produce `5`, which coincidentally matches the
configured value — but changing the config's `top_n` does nothing; only
`retrieval.top_k` moves the reranker's actual cutoff, and only indirectly.

Device selection is not set explicitly anywhere in this codebase — the
library's own auto-detection (CUDA/MPS/CPU) applies. Batch size is likewise
not configured; the sentence-transformers default is used.

In the postprocessor chain, the reranker runs first, and PII masking runs
after it — masking runs last so the reranker always sees original,
unmasked text for scoring quality.

## Retrieval knobs

| Knob | Default | Config key | Notes |
|---|---|---|---|
| Fused candidate pool size | `10` | `retrieval.top_k` | Used for both the BM25 and vector legs, and as the post-fusion cap |
| Hybrid search on/off | `true` | `retrieval.enable_hybrid_search` | `false` skips BM25/RRF entirely, falls back to vector-only |
| RRF constant `k` | `60` | `retrieval.rrf_k` | |
| BM25 source weight | `1.0` | not exposed | Hardcoded; no config key |
| Vector source weight | `1.0` | not exposed | Hardcoded; no config key |
| Reranker enabled | `true` | `reranker.enabled` | `false` removes the reranker postprocessor entirely |
| Reranker model | `cross-encoder/ms-marco-MiniLM-L-6-v2` | `models.reranker.<active.reranker>.model` | |
| Reranker `top_n` (config value) | `5` | `models.reranker.<active.reranker>.top_n` | Dead — see below |
| Reranker effective `top_n` | `max(5, top_k // 2)` | derived from `retrieval.top_k` | The value actually used |

No similarity/score threshold knob exists anywhere in this table — see
"Failure modes" below.

## Failure modes and discrepancies

**BM25 errors degrade to vector-only, but the degradation is now visible.**
The BM25 retriever still wraps its query in a bare `except Exception` and
returns an empty list — an individual request never fails because of a
BM25-side fault. It logs at `ERROR` and records the failure in module state
(`get_bm25_health()` in `bm25_retriever.py`). `/metrics/system` reports it as
`component_status.bm25`, combining two signals:

| Value | Meaning |
|---|---|
| `healthy` | probe query works and the last real search succeeded |
| `unhealthy` | probe works but the most recent search failed |
| `unavailable` | the probe itself fails — extension, index or permissions |

The probe (`probe_bm25`) runs the same `<@>`/`to_bm25query` pair against
`idx_chunks_bm25`, so a dropped index or missing extension surfaces there
even if no user query has run yet. The key is absent from `component_status`
when hybrid search is disabled.

**There is no similarity or score threshold anywhere in the retrieval path.**
Neither the vector retriever nor the BM25 retriever applies a minimum-score
cutoff, and RRF scores are ordinal (rank-based), not a calibrated similarity
value that could be thresholded. Whatever survives fusion and the reranker's
`top_n` truncation goes into the prompt — there is no "drop anything below
score X" gate anywhere in this codebase's retrieval knobs.

**`reranker.top_n` in `config.yml` is dead configuration.** As described
above, it is parsed and available in the inference config dict but never
read by the code that builds the reranker postprocessor, which recomputes
`top_n` from `retrieval.top_k` instead. Changing this config value has no
observable effect on the running system.

**There is one BM25 implementation.** A second, unused one
(`search_chunks_bm25` in the database layer, built on
`bm25_search(...)`/`websearch_to_tsquery(...)`) was deleted along with the
test that asserted the live retriever emitted its SQL shape
(`docs/suggestions.md` #4.4). `PgSearchBM25Retriever._search_bm25` — the
`to_bm25query`/`<@>` pair shown above — is the only path that runs, and
`tests/test_bm25_query_safety.py` now asserts against it.
