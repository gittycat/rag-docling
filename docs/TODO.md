# TODO

## Speedup contextual retrieval

Contextual retrieval is slow (~3s per chunk, LLM call per chunk in `services/rag_server/pipelines/ingestion.py`).

- [x] **Batch/parallel LLM calls** — Done: `asyncio.gather` + `Semaphore` bounded by `retrieval.contextual_concurrency`.
- [ ] **Cache contextual prefixes** — Hash chunk content, skip LLM call if prefix already exists for that hash. Helps on re-uploads.
- [ ] **Disable as fallback** — `enable_contextual_retrieval: false` in config.yml. Hybrid search (BM25 + vector + RRF + reranking) is already strong without it.
