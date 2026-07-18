# TODO

## Speedup contextual retrieval

Contextual retrieval is slow (~3s per chunk, LLM call per chunk in `services/rag_server/pipelines/ingestion.py`).

- [x] **Batch/parallel LLM calls** — Done: `asyncio.gather` + `Semaphore` bounded by `retrieval.contextual_concurrency`.
- [ ] **Use a faster/local model for context generation** — Use a local Ollama model (e.g., `llama3.2:3b`) specifically for contextual prefix generation to eliminate network latency. 2-10x faster.
- [ ] **Cache contextual prefixes** — Hash chunk content, skip LLM call if prefix already exists for that hash. Helps on re-uploads.
- [ ] **Disable as fallback** — `enable_contextual_retrieval: false` in config.yml. Hybrid search (BM25 + vector + RRF + reranking) is already strong without it.
