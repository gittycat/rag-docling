# RAG Pipeline Test Plan

**Date:** 2025-12-08
**Status:** Proposed
**Framework:** pytest + pytest-asyncio + DeepEval

## Executive Summary

This document outlines a comprehensive test strategy for detecting RAG pipeline errors. The plan focuses on **integration tests** that catch real-world failures rather than achieving 100% code coverage. Current test suite (40 unit tests + 27 evaluation tests) extensively mocks external dependencies but misses integration failures.

## Framework Assessment

### Current Stack
- **pytest** (v8.3.3+) - Primary test framework
- **pytest-asyncio** (v0.24.0+) - Async test support
- **pytest-cov** (v6.0.0+) - Coverage reporting
- **DeepEval** (v3.6.9+) - RAG evaluation metrics

### Verdict: Keep Current Framework ✓

**Rationale:**
- pytest is the Python standard with no serious alternatives
- DeepEval (2024) is superior to RAGAS for CI/CD integration
  - "Pytest for LLMs" philosophy with explicit pass/fail
  - Better than RAGAS's opaque numeric scores
  - Optimized for production workflows vs research
- LlamaIndex's built-in evaluators are less comprehensive

**Optional Addition:** `pytest-docker` for container orchestration in tests (can also use existing docker-compose setup)

### Industry Context (2025)

**Sources:**
- [DeepEval vs RAGAS](https://deepeval.com/blog/deepeval-vs-ragas) - DeepEval offers broader LLM evaluation with explicit criteria
- [Best RAG Evaluation Tools 2025](https://www.deepchecks.com/best-rag-evaluation-tools/) - Comprehensive comparison
- [RAG Evaluation Metrics](https://www.patronus.ai/llm-testing/rag-evaluation-metrics) - Best practices
- [LlamaIndex vs LangChain 2025](https://latenode.com/blog/langchain-vs-llamaindex-2025-complete-rag-framework-comparison) - Framework comparison
- [Top 5 AI Evaluation Frameworks](https://www.gocodeo.com/post/top-5-ai-evaluation-frameworks-in-2025-from-ragas-to-deepeval-and-beyond)

## Current Test Gap Analysis

### What We Have (40 Unit Tests)
- API endpoint validation (8 tests)
- Component unit tests with extensive mocking (32 tests)
- Evaluation framework tests (27 tests)

### What We're Missing
- **Integration tests** with real services (ChromaDB, Redis, Ollama)
- **Pipeline flow tests** without mocking LlamaIndex components
- **Error recovery tests** for graceful degradation
- **Concurrent operation tests** for race conditions

### Critical Failure Points Identified

| Component | Failure Mode | Current Coverage | Risk |
|-----------|--------------|------------------|------|
| `document_processor.py` | Docling parsing errors, metadata incompatibility | Unit only | High |
| `hybrid_retriever.py` | BM25/Vector desync after upload/delete | None | Critical |
| `rag_pipeline.py` | Context assembly failures, retrieval bugs | Mocked only | High |
| `tasks.py` | Celery execution errors, file cleanup failures | None | Medium |
| `chroma_manager.py` | ChromaDB connection issues, metadata type errors | Unit only | Medium |

## Test Plan

### Tier 1: Integration Tests (Highest Value)

**Purpose:** Validate component interactions with real services

#### 1.1 Document Processing Pipeline
**File:** `tests/integration/test_document_pipeline.py`
**Services Required:** ChromaDB, Ollama (for contextual retrieval)

```python
def test_pdf_full_pipeline():
    """Upload real PDF → Docling parses → nodes created → ChromaDB stores → queryable

    Validates:
    - DoclingReader.ExportType.JSON format requirement
    - Metadata extraction and cleaning for ChromaDB
    - Node creation and storage
    - Content retrievability

    Test Data: tests/fixtures/sample.pdf (< 1MB)
    """

def test_docx_with_tables():
    """DOCX with tables/images → Docling extracts → structured nodes

    Validates:
    - DoclingReader handles complex layouts
    - Table content extracted as nodes
    - Metadata includes document structure

    Test Data: tests/fixtures/sample_with_tables.docx
    """

def test_txt_fallback_pipeline():
    """Text files use SimpleDirectoryReader, not Docling

    Validates:
    - Code path selection based on file extension
    - SentenceSplitter creates appropriate chunks
    - Simpler processing for plain text

    Test Data: tests/fixtures/sample.txt
    """

def test_unsupported_format_rejection():
    """Upload .exe → rejected with clear error

    Validates:
    - Extension validation before processing
    - Clear error message returned
    - No temp file left behind
    """

def test_metadata_cleaning_for_chroma():
    """Complex metadata (nested dict, lists) → cleaned for ChromaDB

    Validates:
    - clean_metadata_for_chroma() handles edge cases
    - Only flat types (str, int, float, bool, None) stored
    - Nested dicts flattened appropriately

    Test Cases:
    - Nested dict with filename/mimetype
    - Lists (should be skipped)
    - Complex objects (should be stringified)
    """

def test_contextual_retrieval_integration():
    """Contextual prefix generation with real LLM

    Validates:
    - add_contextual_prefix() calls LLM successfully
    - Context prepended to node text before embedding
    - Graceful fallback on LLM failure

    Requires: ENABLE_CONTEXTUAL_RETRIEVAL=true
    """
```

#### 1.2 Hybrid Search Integration
**File:** `tests/integration/test_hybrid_search.py`
**Services Required:** ChromaDB

```python
def test_hybrid_retriever_initialization():
    """BM25 + Vector both return results for same query

    Validates:
    - Both retrievers initialized successfully
    - RRF fusion combines results
    - No single retriever dominates
    """

def test_bm25_exact_keyword_match():
    """BM25 finds exact acronym that vector search misses

    Setup:
    - Document: "The API uses OAuth2 protocol for authentication"
    - Query: "OAuth2"

    Expected:
    - BM25 ranks higher than vector for exact match
    - Hybrid fusion includes BM25 result in top-3
    """

def test_rrf_fusion_scoring():
    """RRF combines rankings correctly

    Validates:
    - Score formula: 1/(rank + k) where k=60
    - Fusion produces different order than either retriever alone
    - Top results include contributions from both retrievers
    """

def test_bm25_refresh_after_upload():
    """Upload new doc → BM25 index includes new content immediately

    Critical Test - Catches Index Desync Bug:
    1. Query "keyword" → 0 results
    2. Upload doc with "keyword"
    3. refresh_bm25_retriever() called
    4. Query "keyword" → 1+ results
    """

def test_bm25_refresh_after_delete():
    """Delete doc → BM25 no longer returns deleted content

    Critical Test - Prevents Stale Results:
    1. Upload doc, query returns it
    2. Delete doc by document_id
    3. refresh_bm25_retriever() called
    4. Query → doc not returned
    """

def test_hybrid_fallback_on_bm25_failure():
    """If BM25 init fails, vector-only still works

    Validates:
    - Graceful degradation when no nodes available
    - Warning logged
    - Query still succeeds with vector search
    """

def test_rrf_k_parameter_effect():
    """Different RRF_K values produce different rankings

    Validates:
    - k=60 (default) vs k=10 changes fusion behavior
    - Lower k favors higher-ranked items more strongly
    """
```

#### 1.3 Full Query Flow
**File:** `tests/integration/test_query_flow.py`
**Services Required:** ChromaDB, Redis, Ollama (can mock LLM response)

```python
def test_retrieval_to_response():
    """Query → retrieves correct docs → generates answer with sources

    Flow:
    1. Upload 3 documents with distinct content
    2. Query targets content in doc #2
    3. Verify doc #2 in sources
    4. Mock LLM response, validate context passed correctly
    """

def test_reranker_improves_order():
    """Top-k after reranking differs from raw retrieval order

    Validates:
    - SentenceTransformerRerank changes node order
    - Top-n selection (default: 5) applied
    - Scores updated after reranking

    Requires: ENABLE_RERANKER=true
    """

def test_context_window_not_exceeded():
    """Large doc → retrieved context fits LLM window

    Validates:
    - Total context length < LLM limit (typically 4096 tokens)
    - top_n in reranker limits context size
    - Context length logged
    """

def test_session_memory_persists():
    """Q1 → Q2 follow-up → Q2 references Q1 answer

    Flow:
    1. Query 1: "What is Python?" (session_id="test-session")
    2. Query 2: "What did you just tell me?" (same session_id)
    3. Verify Q2 response references Q1

    Validates:
    - RedisChatStore persists conversation
    - CondensePlusContextChatEngine uses history
    - Session TTL (1 hour) works
    """

def test_no_context_warning():
    """Query with no matching docs → warning logged, response generated

    Validates:
    - LLM responds without context (knowledge-based answer)
    - Warning logged: "No context nodes retrieved"
    - sources list empty but response still returned
    """

def test_hybrid_vs_vector_only_comparison():
    """Same query with ENABLE_HYBRID_SEARCH=true vs false

    Validates:
    - Different results between modes
    - Both modes work without errors
    - Logs indicate which mode used
    """
```

#### 1.4 Async Upload Flow
**File:** `tests/integration/test_async_upload.py`
**Services Required:** Redis, Celery, ChromaDB, Ollama

```python
def test_celery_task_completes():
    """Upload via API → Celery processes → status shows completed

    Flow:
    1. POST /upload with file
    2. Receive batch_id
    3. Poll GET /tasks/{batch_id}/status
    4. Verify status progresses: pending → processing → completed

    Requires: Celery worker running
    """

def test_progress_tracking_accuracy():
    """Multi-chunk doc → progress increments correctly

    Validates:
    - set_task_total_chunks() called
    - increment_task_chunk_progress() updates Redis
    - completed_chunks matches total_chunks at end

    Test Data: Document producing 20+ chunks
    """

def test_file_cleanup_after_processing():
    """Temp file deleted after successful processing

    Validates:
    - File saved to /tmp/shared
    - Processing completes
    - File deleted (finally block in tasks.py)
    """

def test_task_retry_on_failure():
    """Transient error → Celery retries up to 3 times

    Simulate:
    - ChromaDB connection fails once, succeeds on retry
    - Verify retry_kwargs={'max_retries': 3} works
    - Task eventually succeeds
    """

def test_concurrent_uploads_no_race():
    """Upload 3 files simultaneously → all indexed correctly

    Validates:
    - No race condition in BM25 refresh
    - All documents queryable
    - Progress tracking accurate for each task
    """

def test_batch_progress_aggregation():
    """Multiple files in batch → aggregate progress calculated

    Validates:
    - batch_id links multiple task_ids
    - total/completed counts aggregate correctly
    - Status reflects all tasks
    """
```

---

### Tier 2: Component Integration Tests

**Purpose:** Test component interactions without full end-to-end flow

**File:** `tests/integration/test_component_integration.py`

```python
def test_index_sync_after_delete():
    """Delete document → VectorStore + BM25 both updated

    Validates:
    - delete_documents_by_id() removes from ChromaDB
    - refresh_bm25_retriever() called automatically
    - Query no longer returns deleted nodes
    """

def test_chat_memory_window_limit():
    """Long conversation → old messages pruned

    Validates:
    - ChatMemoryBuffer token_limit enforced
    - Only recent messages in context
    - Redis stores full history
    """

def test_reranker_with_no_results():
    """Query returns 0 results → reranker handles gracefully

    Validates:
    - No crash when node_postprocessors receive empty list
    - Warning logged
    - Empty sources returned
    """

def test_embedding_batch_vs_single():
    """Batch embedding produces same result as individual

    Validates:
    - OllamaEmbedding batch processing
    - Deterministic results (same input → same embedding)
    """
```

---

### Tier 3: Error Recovery Tests

**Purpose:** Validate graceful degradation and error handling

**File:** `tests/integration/test_error_recovery.py`

```python
def test_corrupted_pdf_handling():
    """Invalid PDF → task fails cleanly with error status

    Validates:
    - DoclingReader raises clear exception
    - Task status updated to "error"
    - Error message in progress tracker
    - No crash, no hanging

    Test Data: tests/fixtures/corrupted.pdf (malformed)
    """

def test_contextual_retrieval_llm_timeout():
    """LLM timeout during prefix generation → node saved without prefix

    Validates:
    - add_contextual_prefix() exception handling
    - Original node returned on failure
    - Warning logged
    - Processing continues

    Simulate: Mock LLM.complete() to raise timeout
    """

def test_chromadb_connection_error():
    """ChromaDB down → clear error, not hang

    Validates:
    - Connection error raised immediately
    - Task marked as "error"
    - Retry logic triggers (up to 3x)
    """

def test_ollama_unavailable():
    """Ollama not running → embedding fails with meaningful error

    Validates:
    - Clear error: "Cannot connect to Ollama at http://..."
    - Not generic connection error
    - Task fails without retry (permanent failure)
    """

def test_redis_connection_loss():
    """Redis unavailable → progress tracking fails gracefully

    Validates:
    - Processing continues without progress updates
    - Warning logged
    - Final status still recorded (when Redis returns)
    """

def test_empty_document():
    """Zero-byte file → clean error

    Validates:
    - DoclingReader handles empty input
    - Error: "Could not load document"
    - No nodes created
    """

def test_bm25_initialization_with_empty_index():
    """Query before any documents uploaded

    Validates:
    - BM25 returns None or empty results
    - No crash
    - Warning: "No nodes found in ChromaDB"
    """
```

---

### Tier 4: Edge Case Tests

**Purpose:** Handle unusual but valid inputs

**File:** `tests/integration/test_edge_cases.py`

```python
def test_very_large_document():
    """10MB PDF → memory/timeout handling

    Validates:
    - Processing completes within timeout (default: 1 hour)
    - Memory usage reasonable (<2GB)
    - Progress tracking shows incremental updates

    Test Data: Generate or use large PDF fixture
    """

def test_special_characters_in_query():
    """Unicode, emojis, injection attempts in query

    Test Cases:
    - Unicode: "What is 日本語?"
    - Emojis: "Tell me about 🐍 Python"
    - SQL-like: "'; DROP TABLE documents; --"

    Validates:
    - No crashes
    - Query sanitized appropriately
    - Results returned (if matching)
    """

def test_document_with_no_text():
    """Image-only PDF → Docling extracts OCR or fails gracefully

    Validates:
    - If OCR available, text extracted
    - If no text, empty nodes or clear error
    - No crash
    """

def test_duplicate_document_upload():
    """Same file uploaded twice → two separate document_ids

    Validates:
    - No deduplication (by design)
    - Both documents queryable
    - Different document_ids assigned
    """

def test_query_longer_than_context_window():
    """Query > 2048 tokens → truncated or error

    Validates:
    - LLM handles gracefully (truncates or errors cleanly)
    - No crash
    """

def test_delete_nonexistent_document():
    """DELETE /documents/{fake_id} → 404 or success

    Validates:
    - Idempotent deletion
    - No error when deleting already-deleted doc
    """
```

---

## Test Infrastructure

### Test Fixtures

**Directory:** `tests/fixtures/`

```
tests/fixtures/
├── sample.pdf              # 500KB, 5 pages, mixed text/images
├── sample_with_tables.docx # Tables, bullet lists, headings
├── sample.txt              # Plain text, 1000 words
├── sample.md               # Markdown with code blocks
├── large_document.pdf      # 10MB for performance testing
├── corrupted.pdf           # Malformed header
└── empty.txt               # Zero bytes
```

### Test Configuration

**File:** `services/rag_server/pyproject.toml`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: Tests requiring real services (docker-compose up)",
    "slow: Tests taking > 30s",
    "eval: RAG evaluation tests (require --run-eval flag and ANTHROPIC_API_KEY)",
]
addopts = "--strict-markers -v"
```

### Running Tests

```bash
# Fast unit tests only (CI default - ~30s)
cd services/rag_server
.venv/bin/pytest tests/ --ignore=tests/integration --ignore=tests/evaluation --ignore=tests/test_rag_eval.py

# Integration tests (requires docker-compose up - ~2-5min)
docker compose up -d  # Start services first
.venv/bin/pytest tests/integration -v -m integration

# Full suite including slow tests (~10-15min)
.venv/bin/pytest tests/ -v --run-slow

# Evaluation tests (requires ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/pytest tests/evaluation/ --run-eval --eval-samples=5 -v

# Single test for debugging
.venv/bin/pytest tests/integration/test_hybrid_search.py::test_bm25_refresh_after_upload -v -s
```

---

## Priority Implementation Order

### Phase 1: Critical Path (1 week)
**Goal:** Catch the most common pipeline failures

1. **`test_pdf_full_pipeline`** - Validates entire document → retrieval chain
2. **`test_bm25_refresh_after_upload`** - Catches index desync (frequent bug)
3. **`test_celery_task_completes`** - Validates async processing end-to-end
4. **`test_corrupted_pdf_handling`** - Ensures errors don't crash system

**Justification:** These cover document ingestion → indexing → retrieval, the core RAG flow.

### Phase 2: Robustness (1 week)
**Goal:** Ensure system handles errors gracefully

5. **`test_hybrid_fallback_on_bm25_failure`** - Graceful degradation
6. **`test_contextual_retrieval_llm_timeout`** - LLM failure handling
7. **`test_session_memory_persists`** - Conversational memory works
8. **`test_concurrent_uploads_no_race`** - Race condition prevention

### Phase 3: Edge Cases (ongoing)
**Goal:** Handle unusual inputs

9. **`test_very_large_document`** - Performance under load
10. **`test_special_characters_in_query`** - Input sanitization
11. **Remaining edge cases as needed**

---

## CI/CD Integration

### Forgejo Workflow Updates

**File:** `.forgejo/workflows/ci.yml`

```yaml
jobs:
  core-tests:
    # Existing: 40 unit tests, ~30s
    steps:
      - run: pytest tests/ --ignore=tests/integration --ignore=tests/evaluation --ignore=tests/test_rag_eval.py -v

  integration-tests:
    # New: Integration tests with real services
    runs-on: ubuntu-latest
    services:
      chromadb:
        image: chromadb/chroma:latest
        ports:
          - 8000:8000
      redis:
        image: redis:alpine
        ports:
          - 6379:6379
    steps:
      - name: Start Ollama
        run: |
          docker run -d -p 11434:11434 ollama/ollama:latest
          docker exec ollama ollama pull nomic-embed-text
          docker exec ollama ollama pull gemma2:2b

      - name: Run integration tests
        run: |
          cd services/rag_server
          uv sync
          .venv/bin/pytest tests/integration -v -m integration
        timeout: 10m

  eval-tests:
    # Existing: Evaluation tests (optional, ~2-5min)
    if: contains(github.event.head_commit.message, '[eval]')
```

---

## Metrics & Success Criteria

### Test Coverage Goals
- **Unit tests:** 80%+ coverage (current: ~75%)
- **Integration tests:** Cover all critical paths (4 Tier 1 test files)
- **Error recovery:** 100% of identified failure modes tested

### Performance Baselines
- **Unit test suite:** < 60s
- **Integration test suite:** < 10 minutes
- **Full suite (including eval):** < 20 minutes

### Failure Detection Rate
- Target: Catch 90%+ of production-like failures before deployment
- Key metrics:
  - Index desync detected by tests
  - Error handling verified
  - Race conditions caught

---

## Future Enhancements

### Potential Additions

1. **Load Testing**
   - `locust` or `pytest-benchmark` for performance regression detection
   - Concurrent query handling (10+ simultaneous queries)

2. **Chaos Engineering**
   - `pytest-randomly` for test order randomization
   - Random service failures during integration tests

3. **Contract Testing**
   - Schema validation for API responses
   - Backward compatibility checks

4. **Visual Regression Testing**
   - If web UI added, use `playwright` or `selenium`

5. **Data Quality Monitoring**
   - Embedding drift detection over time
   - Retrieval quality regression tests

---

## Appendix: Testing Best Practices

### From Industry Research

**Key Findings:**

1. **RAG Index Testing** (2025 Best Practices)
   - Test not just retrieval metrics, but index structure and query patterns
   - Validate vector database stores/retrieves/ranks correctly
   - Monitor index drift as data grows

2. **Common Pitfalls to Avoid**
   - Not testing edge cases: empty queries, long queries, special characters
   - Ignoring cold start (first query after restart slower)
   - Not monitoring index quality degradation over time

3. **RAGAS vs DeepEval Philosophy**
   - RAGAS: Lightweight, research-backed metrics (good for experimentation)
   - DeepEval: Production-focused, CI/CD integration, explicit pass/fail
   - Our choice (DeepEval) aligns with production readiness goals

4. **LlamaIndex Evaluation Best Practices**
   - Use both built-in evaluators AND external tools (DeepEval/RAGAS)
   - No single metric captures truth
   - Faithfulness + relevancy + recall = comprehensive evaluation

### Test Data Management

- **Golden Datasets:** Maintain `tests/fixtures/` with versioned test documents
- **Synthetic Data:** Generate edge cases programmatically (very long docs, special chars)
- **Real-World Samples:** Anonymized production documents (if available)

### Continuous Improvement

- **Weekly Review:** Analyze test failures, add regression tests
- **Quarterly Audit:** Review test coverage, remove obsolete tests
- **Post-Incident:** Add tests for every production bug discovered

---

## References

- [DeepEval Documentation](https://docs.confident-ai.com/)
- [LlamaIndex Testing Guide](https://developers.llamaindex.ai/python/framework/optimizing/production_rag/)
- [RAG Evaluation Metrics Explained](https://langcopilot.com/posts/2025-09-17-rag-evaluation-101-from-recall-k-to-answer-faithfulness)
- [pytest Best Practices](https://docs.pytest.org/en/stable/goodpractices.html)

---

**Next Steps:**
1. Review and approve test plan
2. Set up test fixtures (`tests/fixtures/`)
3. Implement Phase 1 tests (4 critical tests)
4. Update CI/CD workflow for integration tests
5. Document test results and iterate
