# RAG Retrieval Diagnostic - Final Report

**Date:** 2025-10-09
**Status:** ✅ SYSTEM FUNCTIONAL - Tuning Recommended

## Executive Summary

Successfully identified and fixed the root cause of retrieval failure. The system is now operational with documents indexed and retrieval working. However, Docling's granular chunking strategy requires configuration tuning for optimal answer quality.

### Key Fixes Implemented

1. ✅ **DoclingReader Export Format** - Changed from default MARKDOWN to JSON export
2. ✅ **Metadata Compatibility** - Added ChromaDB metadata filtering
3. ✅ **Retrieval Coverage** - Increased from 3 to 10 nodes for better context

### Current Status

| Component | Status | Details |
|-----------|--------|---------|
| Document Upload | ✅ WORKING | 3 docs, 1471 chunks indexed |
| Vector Search | ✅ WORKING | Retrieving 10 nodes per query |
| Context Generation | ⚠️ PARTIAL | 655 chars context (fragmented) |
| Answer Quality | ⚠️ NEEDS TUNING | Incomplete answers due to chunk fragmentation |

## Root Cause Analysis

### Issue #1: DoclingReader/DoclingNodeParser Format Mismatch (FIXED)

**Problem:**
```python
# BROKEN CODE
reader = DoclingReader()  # Defaults to MARKDOWN export
node_parser = DoclingNodeParser()  # Expects JSON format
nodes = node_parser.get_nodes_from_documents(docs)  # ❌ ValidationError
```

**Error:**
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for DoclingDocument
  Invalid JSON: expected value at line 1 column 1 [type=json_invalid]
```

**Root Cause:**
- DoclingReader has two export modes: MARKDOWN (default) and JSON
- DoclingNodeParser requires JSON-serialized Docling format
- Without explicit `export_type` parameter, format mismatch occurs

**Fix Applied:**
```python
# FIXED CODE - services/rag_server/core_logic/document_processor.py:45
reader = DoclingReader(export_type=DoclingReader.ExportType.JSON)
```

**Source:** Official Docling documentation
- https://docling-project.github.io/docling/integrations/llamaindex/
- llama-index-readers-docling v0.4.1 README

### Issue #2: ChromaDB Metadata Validation (FIXED)

**Problem:**
```python
ValueError: Value for metadata doc_items must be one of (str, int, float, None)
```

**Root Cause:**
- Docling adds rich metadata: `doc_items` (list), `origin` (dict)
- ChromaDB only accepts flat types: str, int, float, bool, None
- Complex metadata causes insertion failure

**Fix Applied:**
```python
# services/rag_server/core_logic/document_processor.py:13-33
def clean_metadata_for_chroma(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Filter out complex types incompatible with ChromaDB"""
    cleaned = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, dict):
            # Extract useful fields from nested dicts
            if 'filename' in value:
                cleaned[f"{key}_filename"] = str(value['filename'])
            if 'mimetype' in value:
                cleaned[f"{key}_mimetype"] = str(value['mimetype'])
        elif isinstance(value, list):
            logger.debug(f"Skipping list metadata field: {key}")
        else:
            cleaned[key] = str(value)
    return cleaned
```

### Issue #3: Insufficient Retrieval Coverage (FIXED)

**Problem:**
- Default `n_results=3` too small for Docling's granular chunking
- Retrieval getting mostly headings/dates (9-66 chars) instead of content
- Context: 166 chars (3 nodes) → insufficient for answers

**Fix Applied:**
```python
# services/rag_server/core_logic/rag_pipeline.py:52-53
# Always use configured retrieval_top_k for better coverage with granular Docling chunks
retrieval_top_k = config['retrieval_top_k']  # Now always uses 10
```

**Result:**
- Before: 3 nodes, 166 characters
- After: 10 nodes, 641-655 characters (4x improvement)

## Current System Performance

### Successfully Indexed Documents

```
conformism.html:   215 chunks
greatwork.html:   1180 chunks
talk.html:          76 chunks
------------------------
TOTAL:            1471 chunks
```

### Retrieval Analysis

**Sample Query:** "What are the three qualities that work must have to do great work?"

**Retrieved Nodes (top 10):**
```
Node  Score    Content (truncated)
----  -----    -------------------
 74   0.496    "to prove that you have to work hard to do great things, but the"
1064  0.486    "counts as great work. Doing great work means doing something important"
1026  0.478    "The factors in doing great work are factors in the literal,"
 446  0.475    "to have a great deal of ability in other respects"
 934  0.474    "Morale compounds via work: high morale helps you do good work"
  10  0.473    "have a definite shape; it's not just a point labelled 'work hard.'"
  13  0.468    "needs to have three qualities: it has to be something you have a"
  87  0.468    "tell what most kinds of work are like except by doing them"
 311  0.467    "different thing from ambition to be good. Or maybe being good is"
 923  0.465    "Husband your morale. It's the basis of everything when you're working"
```

**Source Document Answer:**
```
"needs to have three qualities: it has to be something you have a
natural aptitude for, that you have a deep interest in, and that
offers scope to do great work."
```

**Issue:** Answer fragmented across 3 chunks:
1. Chunk 13 (retrieved, score 0.468): "needs to have three qualities: it has to be something you have a"
2. Chunk 14 (NOT retrieved): "natural aptitude for, that you have a deep interest in, and that"
3. Chunk 15 (NOT retrieved): "offers scope to do great work"

### Docling Chunking Characteristics

**Node Size Distribution:**
- Minimum: 9 chars (dates, labels)
- Maximum: 27,192 chars (tables, long sections)
- Typical headings: 16-66 chars
- Typical paragraphs: 200-500 chars

**Structural Elements:**
- Docling preserves document structure (headings, paragraphs, tables, lists)
- Creates one node per structural element
- Chunks mid-sentence to maintain structure
- Highly variable node sizes

**Trade-offs:**
- ✅ Preserves document structure and metadata
- ✅ Enables table/figure extraction
- ⚠️ Fragments semantic units (answers split across chunks)
- ⚠️ Many tiny nodes (headings, dates) dilute retrieval

## Recommendations

### Option 1: Enable Reranking (RECOMMENDED - Quick Win)

**Action:** Set `ENABLE_RERANKER=true` in docker-compose.yml

```yaml
environment:
  - ENABLE_RERANKER=true
  - RERANKER_SIMILARITY_THRESHOLD=0.65  # Adjust based on evaluation
```

**Benefits:**
- Cross-encoder reranker scores chunks based on query relevance
- Filters low-relevance chunks after retrieval
- Better selection among granular Docling chunks
- Minimal code changes

**Drawback:**
- Adds ~100-300ms latency per query
- Requires HuggingFace model download (~80MB, one-time)

### Option 2: Use Hierarchical Node Parsing (OPTIMAL - Long Term)

**Action:** Create larger parent chunks with Docling sub-chunks

```python
from llama_index.node_parser import HierarchicalNodeParser

# Parent chunks: semantic units (500-1000 chars)
parent_parser = SentenceSplitter(chunk_size=800, chunk_overlap=100)

# Child chunks: Docling structural elements
child_parser = DoclingNodeParser()

# Combine: retrieve children, return parent context
hierarchical_parser = HierarchicalNodeParser.from_defaults(
    parent_parser=parent_parser,
    child_parser=child_parser
)
```

**Benefits:**
- Best of both: Docling structure + semantic completeness
- Retrieve small chunks, return full context
- No answer fragmentation

**Drawback:**
- More complex implementation
- Requires refactoring document_processor.py

### Option 3: Custom Chunk Merging Strategy

**Action:** Post-process Docling nodes to merge small adjacent chunks

```python
def merge_small_chunks(nodes: List, min_size: int = 200):
    """Merge consecutive chunks smaller than min_size"""
    merged = []
    buffer = []
    buffer_size = 0

    for node in nodes:
        size = len(node.get_content())
        if buffer_size + size < min_size:
            buffer.append(node)
            buffer_size += size
        else:
            if buffer:
                merged.append(merge_nodes(buffer))
            buffer = [node]
            buffer_size = size

    if buffer:
        merged.append(merge_nodes(buffer))

    return merged
```

**Benefits:**
- Reduces chunk count
- Maintains semantic units
- Uses Docling's structure as guide

**Drawback:**
- May merge unrelated elements
- Loses some structural granularity

### Option 4: Hybrid Approach for Different File Types

**Action:** Use Docling only for PDFs/DOCX with complex layouts, SentenceSplitter for simple documents

```python
# services/rag_server/core_logic/document_processor.py
COMPLEX_DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.pptx', '.xlsx'}
SIMPLE_DOCUMENT_EXTENSIONS = {'.txt', '.md'}

if extension in COMPLEX_DOCUMENT_EXTENSIONS:
    # Use Docling for structure preservation
    reader = DoclingReader(export_type=DoclingReader.ExportType.JSON)
    node_parser = DoclingNodeParser()
else:
    # Use SentenceSplitter for semantic chunking
    reader = SimpleDirectoryReader(input_files=[str(file_path)])
    node_parser = SentenceSplitter(chunk_size=500, chunk_overlap=50)
```

**Benefits:**
- Optimizes chunking strategy per document type
- Docling benefits for complex layouts (tables, figures)
- Semantic chunking for text-heavy documents

**Drawback:**
- Inconsistent node structure across doc types
- More code complexity

## Immediate Action Plan

### Phase 1: Enable Reranking (TODAY - 15 mins)

1. Edit `docker-compose.yml`:
```yaml
# Line 36
- ENABLE_RERANKER=true
- RERANKER_SIMILARITY_THRESHOLD=0.65

# Line 98 (celery-worker)
- ENABLE_RERANKER=true
- RERANKER_SIMILARITY_THRESHOLD=0.65
```

2. Restart services:
```bash
docker compose up -d --force-recreate
```

3. Test queries:
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "query=What+are+the+three+qualities+for+great+work?"
```

### Phase 2: Run RAGAS Evaluation (TODAY - 30 mins)

1. Install evaluation dependencies:
```bash
cd services/rag_server
uv sync --group eval
```

2. Run evaluation:
```bash
.venv/bin/python evaluation/eval_runner.py
```

3. Analyze metrics:
- Target Context Precision: > 0.85
- Target Context Recall: > 0.90
- Target Faithfulness: > 0.90
- Target Answer Relevancy: > 0.85

4. Tune threshold based on results:
- If Context Recall < 0.90: Lower threshold to 0.55
- If too many "I don't know": Lower threshold to 0.60
- If hallucinations detected: Raise threshold to 0.70

### Phase 3: Consider Long-Term Solution (NEXT WEEK)

Evaluate Option 2 (Hierarchical Parsing) if:
- RAGAS Context Recall < 0.85 even with reranking
- Users frequently report incomplete answers
- Documents have complex multi-page answers

## Testing Validation

### Test Queries (from golden_qa.json)

1. **Factual Query:**
   - Q: "What are the three qualities for great work?"
   - Expected: "Natural aptitude, deep interest, and scope to do great work"
   - Current: Fragmented across chunks

2. **Simple Factual:**
   - Q: "What are the four quadrants of conformism?"
   - Expected: "Aggressively conventional-minded, passively conventional-minded, passively independent-minded, aggressively independent-minded"
   - Current: Partial answer ("The resulting four quadrants define four types of people")

3. **Reasoning Query:**
   - Q: "Why is informal language better for expressing complex ideas?"
   - Expected: Multi-sentence explanation
   - Current: Needs testing

### Success Criteria

✅ **Phase 1 Success:**
- Documents upload without errors
- ChromaDB shows expected chunk count
- Queries return non-zero contexts

✅ **Phase 2 Success (Reranking):**
- RAGAS Context Precision > 0.85
- RAGAS Context Recall > 0.90
- <10% queries return "I don't know"

✅ **Phase 3 Success (Long-term):**
- RAGAS Faithfulness > 0.90
- RAGAS Answer Relevancy > 0.85
- Users report satisfactory answer quality

## Technical Debt / Future Work

1. **Chunk Size Tuning:**
   - Experiment with DoclingNodeParser parameters (if configurable)
   - Research if Docling supports custom chunk size settings

2. **Embedding Model Alignment:**
   - Config specifies `nomic-embed-text:latest`
   - Documentation mentions `qwen3-embedding:8b`
   - Standardize on one model, document dimensions

3. **Prompt Strategy Evaluation:**
   - Test all 4 strategies (fast, balanced, precise, comprehensive)
   - Measure trade-offs: accuracy vs. refusal rate

4. **HTML Document Chunking:**
   - Eval docs are HTML (conformism.html, greatwork.html, talk.html)
   - For production PDF/DOCX, chunking behavior may differ
   - Validate with actual target document types

5. **Production Monitoring:**
   - Add metrics: avg chunks per query, context length distribution
   - Track "I don't know" frequency
   - Monitor retrieval score distribution

## Files Modified

### Core Fixes

1. **`services/rag_server/core_logic/document_processor.py`**
   - Added `clean_metadata_for_chroma()` function
   - Changed `DoclingReader()` → `DoclingReader(export_type=DoclingReader.ExportType.JSON)`
   - Added metadata cleaning step after node parsing

2. **`services/rag_server/core_logic/rag_pipeline.py`**
   - Changed `retrieval_top_k = config['retrieval_top_k'] if config['enabled'] else n_results`
   - To: `retrieval_top_k = config['retrieval_top_k']` (always use configured value)

### Configuration

3. **`docker-compose.yml`** (RECOMMENDED NEXT STEP)
   - Set `ENABLE_RERANKER=true`
   - Adjust `RERANKER_SIMILARITY_THRESHOLD` based on evaluation

## Conclusion

The RAG system is now **functional and operational**. Documents are successfully indexed, retrieval is working, and the LLM is generating responses based on retrieved context.

**Current Bottleneck:** Docling's granular structural chunking fragments answers across non-contiguous chunks. This is not a bug but a design choice that prioritizes document structure over semantic units.

**Recommended Path:**
1. **Short-term (TODAY):** Enable reranking to improve chunk selection
2. **Medium-term (THIS WEEK):** Run RAGAS evaluation and tune similarity threshold
3. **Long-term (NEXT SPRINT):** Implement hierarchical node parsing if answer quality remains suboptimal

The system architecture is sound. With reranking enabled and threshold tuning, answer quality should improve significantly.

---

**Diagnostic completed:** 2025-10-09 05:15 UTC
**Total investigation time:** ~1 hour
**System status:** ✅ OPERATIONAL - TUNING RECOMMENDED
