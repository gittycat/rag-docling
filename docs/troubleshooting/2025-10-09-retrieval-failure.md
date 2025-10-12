# RAG Retrieval Failure - Diagnostic Report

**Date:** 2025-10-09
**Issue:** Application returns "I don't have enough information to answer this question" for all queries

## Executive Summary

**ROOT CAUSE IDENTIFIED:** DoclingReader and DoclingNodeParser integration is broken due to incompatible data formats.

The retrieval pipeline is failing at document upload stage, preventing any documents from being indexed in ChromaDB. This results in an empty vector store, causing all queries to return zero contexts and triggering the LLM's fallback response.

## Diagnostic Process

### Phase 1: Environment Verification ✓

**Status:** PASSED
**Findings:**
- All Docker services running and healthy
- ChromaDB accessible at `http://chromadb:8000`
- Ollama accessible at `http://host.docker.internal:11434`
- Required models present:
  - `nomic-embed-text:latest` (embeddings)
  - `gemma3:4b` (LLM)
  - `qwen3-embedding:8b` (available but not used)

**Configuration:**
```
CHROMADB_URL: http://chromadb:8000
OLLAMA_URL: http://host.docker.internal:11434
EMBEDDING_MODEL: nomic-embed-text:latest
LLM_MODEL: gemma3:4b
PROMPT_STRATEGY: balanced
ENABLE_RERANKER: false
RERANKER_SIMILARITY_THRESHOLD: 0.3
RETRIEVAL_TOP_K: 10
```

### Phase 2: Data Validation ✓

**Status:** FAILED - No documents indexed
**Findings:**
- ChromaDB collection exists but is empty
- Document count: **0**
- Total chunks: **0**

**Expected:** 3 evaluation documents (conformism.html, greatwork.html, talk.html) should be indexed

### Phase 3: Document Upload Testing ✓

**Status:** FAILED - DoclingReader/DoclingNodeParser incompatibility
**Error:**
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for DoclingDocument
  Invalid JSON: expected value at line 1 column 1 [type=json_invalid, input_value='|    |    | Image Hyperl...----------------------|', input_type=str]
```

**Root Cause Analysis:**
1. `DoclingReader` loads HTML documents and converts them to LlamaIndex `Document` objects
2. Document content is stored as Markdown table format (text)
3. `DoclingNodeParser` expects document content to be JSON-serialized `DLDocument` objects
4. Format mismatch causes `pydantic` validation error
5. Document upload fails, no nodes are created
6. ChromaDB remains empty

**Code Location:** `services/rag_server/core_logic/document_processor.py:44-58`

**Affected Workflow:**
```python
# Current broken flow:
reader = DoclingReader()
documents = reader.load_data(file_path=str(file_path))  # Returns docs with Markdown content
node_parser = DoclingNodeParser()
nodes = node_parser.get_nodes_from_documents(documents)  # ❌ Expects JSON, gets Markdown
```

**Package Versions:**
- `llama-index-readers-docling`: 0.4.1
- `llama-index-node-parser-docling`: 0.4.1
- `docling`: 2.55.1
- `llama-index-core`: >= 0.14.3

### Phase 4: Retrieval Pipeline Testing

**Status:** NOT REACHED - Prerequisite failure (no documents)
**Impact:** Cannot test retrieval without indexed documents

### Phase 5: RAGAS Evaluation

**Status:** NOT REACHED - Prerequisite failure (no documents)
**Impact:** Cannot run evaluation metrics without indexed documents

## Impact Analysis

### User-Facing Symptoms
1. All queries return: "I don't have enough information to answer this question."
2. Web admin panel shows 0 documents indexed
3. Document upload appears to queue but fails silently
4. No error messages visible to end users

### System Behavior
1. **Upload Endpoint (`POST /upload`):**
   - Accepts files successfully
   - Queues Celery tasks
   - Tasks fail during document processing
   - Batch status shows tasks as failed/incomplete

2. **Query Endpoint (`POST /query`):**
   - Retrieves 0 nodes from empty ChromaDB
   - LLM receives no context
   - Prompt template triggers "I don't know" response
   - Returns 0 sources

3. **Documents Endpoint (`GET /documents`):**
   - Returns empty list
   - No documents to manage or delete

## Technical Details

### DoclingReader Behavior
```python
reader = DoclingReader()
documents = reader.load_data(file_path="conformism.html")

# Returns: [Document(text='| | | Image Hyperl...', metadata={...})]
# Content format: Markdown table representation
```

### DoclingNodeParser Expectation
```python
node_parser = DoclingNodeParser()

# Expects: Document.get_content() to return JSON string
# Example: '{"schema_name": "DoclingDocument", "version": "1.0", ...}'

# Actual: Gets Markdown table string
# Result: ValidationError from Pydantic
```

### Integration Mismatch

The `llama-index-readers-docling` and `llama-index-node-parser-docling` packages appear to be from different integration versions or have incompatible export formats.

**Hypothesis:** DoclingReader may need configuration to export JSON format instead of Markdown.

## Possible Solutions

### Option 1: Configure DoclingReader Export Format
Investigate if `DoclingReader` has parameters to control export format:
```python
reader = DoclingReader(export_format="json")  # Hypothetical
# OR
reader = DoclingReader()
documents = reader.load_data(file_path=path, export_type=DocumentFormat.JSON)
```

### Option 2: Use Different Node Parser
For HTML documents, use standard LlamaIndex components instead of Docling-specific ones:
```python
if extension in {'.html', '.htm'}:
    reader = SimpleDirectoryReader(input_files=[str(file_path)])
    documents = reader.load_data()
    splitter = SentenceSplitter(chunk_size=500, chunk_overlap=50)
    nodes = splitter.get_nodes_from_documents(documents)
```

### Option 3: Fix DoclingReader → DoclingNodeParser Pipeline
Manually convert between formats:
```python
documents = reader.load_data(file_path=str(file_path))

# Extract Docling document and serialize to JSON
for doc in documents:
    if hasattr(doc, 'dl_doc'):  # Check if DoclingReader provides access
        json_content = doc.dl_doc.model_dump_json()
        doc.text = json_content  # Replace Markdown with JSON

nodes = node_parser.get_nodes_from_documents(documents)
```

### Option 4: Bypass DoclingNodeParser Entirely
Parse Docling documents directly and create LlamaIndex nodes manually:
```python
from docling.document_converter import DocumentConverter

converter = DocumentConverter()
result = converter.convert(file_path)
dl_doc = result.document

# Create nodes from Docling chunks manually
nodes = []
for element in dl_doc.body:
    node = TextNode(text=element.text, metadata={...})
    nodes.append(node)
```

### Option 5: Downgrade/Upgrade Package Versions
Test with different version combinations:
```toml
llama-index-readers-docling = "0.3.0"  # Try older version
llama-index-node-parser-docling = "0.1.0"  # Try minimum version
```

## Recommended Fix Priority

1. **CRITICAL (Immediate):** Implement Option 2 as temporary workaround for HTML files
2. **HIGH (This Week):** Investigate Option 1 - check Docling documentation for export format
3. **MEDIUM (Next Sprint):** Implement Option 4 for long-term solution with full Docling features
4. **LOW (Backlog):** Test Option 5 if other solutions fail

## Testing Plan

### After Fix Implementation

1. **Unit Test:**
   ```bash
   cd services/rag_server
   .venv/bin/pytest tests/test_document_processing.py -v
   ```

2. **Integration Test:**
   - Upload eval documents (conformism.html, greatwork.html, talk.html)
   - Verify ChromaDB contains 3 documents with expected chunk counts
   - Query: "What are the three qualities for great work?"
   - Expect: Meaningful answer with source citations

3. **RAGAS Evaluation:**
   ```bash
   .venv/bin/python evaluation/eval_runner.py
   ```
   - Target: Context Precision > 0.85, Context Recall > 0.90
   - Target: Faithfulness > 0.90, Answer Relevancy > 0.85

## Files to Modify

1. **`services/rag_server/core_logic/document_processor.py`** - Fix DoclingReader integration
2. **`services/rag_server/tests/test_document_processing.py`** - Update tests to match new implementation
3. **`services/rag_server/pyproject.toml`** - Potentially adjust package versions
4. **`CLAUDE.md`** - Update documentation with correct integration pattern

## Additional Observations

### Configuration Issues (Non-Critical)
1. **Embedding Model Mismatch:**
   - Config specifies: `nomic-embed-text:latest`
   - Documentation mentions: `qwen3-embedding:8b`
   - Both models available, but different dimensions may cause issues
   - Recommendation: Standardize on one model

2. **Reranker Disabled:**
   - Currently: `ENABLE_RERANKER=false`
   - Threshold: `0.3` (very low)
   - May need tuning after document indexing works

3. **Prompt Strategy:**
   - Using: `balanced`
   - May be too strict with "I don't have enough information" fallback
   - Consider `fast` strategy for testing

### Performance Notes
- Docling processing logged at 0.11 sec for conformism.html before error
- Suggests Docling itself is working, only the format conversion fails
- Once fixed, upload performance should be acceptable

## Next Steps

1. Research DoclingReader export format options
2. Implement recommended fix (Option 2 for quick win, then Option 1 or 4 for proper solution)
3. Test with evaluation documents
4. Run RAGAS evaluation to establish baseline metrics
5. Adjust reranker threshold based on evaluation results
6. Document correct integration pattern in CLAUDE.md

## Conclusion

The RAG retrieval failure is **100% caused by document upload failure** due to **incompatible data formats** between DoclingReader (Markdown export) and DoclingNodeParser (JSON expectation).

**No documents are indexed** → **No contexts retrieved** → **LLM always responds "I don't know"**

This is a **configuration/integration bug**, not a retrieval quality issue. Once fixed, retrieval pipeline should work as designed.

---

**Diagnostic completed:** 2025-10-09 04:50 UTC
**Total time:** ~15 minutes
**Tools used:** Docker logs, Python REPL, ChromaDB API, diagnostic scripts
