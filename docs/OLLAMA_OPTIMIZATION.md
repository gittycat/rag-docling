# Ollama Optimization Guide

**Last Updated**: 2025-10-16

## Overview

This document covers Ollama-specific optimizations for the RAG pipeline, focusing on reducing latency and memory usage during document processing and query execution.

## Background: Prompt Caching Investigation

### Anthropic's Prompt Caching vs. Ollama

**Anthropic's Approach**:
- Supports explicit prompt caching API
- Allows caching of document context across multiple chunks
- Can reduce contextual retrieval costs by up to 90%
- Implemented via cache_control parameter in the API

**Ollama's Current State**:
- Does NOT have Anthropic-style prompt caching API
- GitHub issues (#1573, #2023) show community requests for this feature
- Prompt caching was previously enabled but disabled due to stability issues
- No timeline for re-enabling this feature

**Conclusion**: Ollama does not currently support the same prompt caching mechanism that Anthropic uses for efficient contextual retrieval.

## Available Ollama Optimizations

Despite the lack of explicit prompt caching, Ollama provides several optimization features that can improve performance:

### 1. Keep-Alive Parameter ✅ IMPLEMENTED

**Purpose**: Keep models loaded in memory between calls to reduce latency.

**Default Behavior**: Models stay loaded for 5 minutes after last use, then unload.

**Configuration**:
```yaml
# In docker-compose.yml
environment:
  - OLLAMA_KEEP_ALIVE=10m  # Keep loaded for 10 minutes
  # OR
  - OLLAMA_KEEP_ALIVE=-1   # Keep loaded indefinitely
  # OR
  - OLLAMA_KEEP_ALIVE=0    # Unload immediately after each call
```

**Impact on Contextual Retrieval**:
- First chunk: Normal latency (model loads from disk)
- Subsequent chunks: Reduced latency (model already in memory)
- For a 50-chunk document: Saves model loading overhead 49 times

**Performance Improvement**:
- Can provide 10x performance gains for repeated calls
- Especially valuable for contextual retrieval (multiple sequential LLM calls)
- Reduces average response time from 15-30s to under 3s for cached models

**Current Settings**:
- RAG Server: `10m` (10 minutes)
- Celery Worker: `10m` (10 minutes)

**Recommendation**: Use `-1` (indefinite) for dedicated Ollama instances serving only this RAG system.

### 2. KV Cache Quantization ⚠️ HOST-LEVEL CONFIGURATION

**Purpose**: Reduce memory usage of the Key-Value attention cache by 50-75%.

**How It Works**:
- KV Cache stores precomputed attention vectors for previous tokens
- Default: Uses FP16 (16-bit floating point) precision
- Quantization: Reduces to Q8_0 (8-bit) or Q4_0 (4-bit) with minimal quality loss

**Configuration** (must be set on host machine where Ollama runs):
```bash
# For macOS/Linux (add to ~/.zshrc or ~/.bashrc)
export OLLAMA_KV_CACHE_TYPE=q8_0

# Then restart Ollama
ollama serve
```

**Memory Savings**:
- `q8_0`: ~50% reduction in KV cache memory
- `q4_0`: ~75% reduction in KV cache memory
- No significant quality degradation reported

**Limitations**:
- Cannot be set via Modelfile
- Cannot be set per-request via API
- Cannot differentiate K and V cache quantization levels
- Must be configured at Ollama startup (environment variable)

**Current Status**: NOT configured by default (users must enable on host).

### 3. Context Window Caching (Automatic)

**Purpose**: Ollama automatically caches KV cache for recent conversations.

**How It Works**:
- When you send a new message in a conversation, context is already cached
- Switching conversations or starting new chat clears the cache
- No configuration needed - happens automatically

**Limitation for Contextual Retrieval**:
- Each chunk is processed as a separate request
- Context is not automatically reused between chunks
- Cannot manually control cache reuse without explicit API support

## Implementation Status

### ✅ Implemented

1. **Keep-Alive Parameter**
   - Added to `llm_handler.py`
   - Configurable via `OLLAMA_KEEP_ALIVE` environment variable
   - Default: `10m` (10 minutes)
   - Location: `services/rag_server/core_logic/llm_handler.py:15`

2. **Contextual Retrieval Toggle**
   - Disabled by default to prioritize speed over accuracy
   - Configurable via `ENABLE_CONTEXTUAL_RETRIEVAL` environment variable
   - Default: `false`
   - Location: `docker-compose.yml:46,111`

### ⚠️ Manual Configuration Required

1. **KV Cache Quantization**
   - Requires host-level environment variable
   - Must be set before starting Ollama
   - Not configurable via Docker Compose (Ollama runs on host)

### ❌ Not Available

1. **Anthropic-Style Prompt Caching**
   - Not supported by Ollama
   - No API for explicit cache control
   - No timeline for implementation

## Performance Benchmarks

### Keep-Alive Impact (Estimated)

**Without Keep-Alive** (default 5m timeout):
```
Chunk 1: 11.78s (includes model loading)
Chunk 2: 11.78s (model may still be loaded)
Chunk 10: 11.78s (model likely unloaded if >5m elapsed)
```

**With Keep-Alive=10m**:
```
Chunk 1: 11.78s (includes model loading: ~2-3s)
Chunk 2: 8.78s (model already loaded: saves ~3s)
Chunk 50: 8.78s (model still loaded)
```

**Expected Savings**: ~20-25% reduction in total processing time for multi-chunk documents.

### KV Cache Quantization Impact

- **Memory Reduction**: 50% with q8_0, 75% with q4_0
- **Inference Speed**: Minimal impact (< 5% slower)
- **Quality**: No significant degradation reported
- **Use Case**: Enables larger context windows or running larger models on same hardware

## Recommendations

### For Development/Testing
```yaml
# docker-compose.yml
- OLLAMA_KEEP_ALIVE=10m              # Reasonable timeout
- ENABLE_CONTEXTUAL_RETRIEVAL=false  # Faster preprocessing
```

### For Production (High Accuracy)
```yaml
# docker-compose.yml
- OLLAMA_KEEP_ALIVE=-1               # Keep loaded indefinitely
- ENABLE_CONTEXTUAL_RETRIEVAL=true   # Maximum retrieval accuracy
```

### For Production (High Speed)
```yaml
# docker-compose.yml
- OLLAMA_KEEP_ALIVE=-1               # Keep loaded indefinitely
- ENABLE_CONTEXTUAL_RETRIEVAL=false  # Fast preprocessing
```

### Host-Level Optimization (All Scenarios)
```bash
# On Ollama host machine
export OLLAMA_KV_CACHE_TYPE=q8_0
ollama serve
```

## Monitoring

### Check Keep-Alive Status

Look for log entries during LLM initialization:
```
[LLM] Initializing Ollama LLM: gemma3:4b, keep_alive=10m
```

### Verify Model Loading

```bash
# Check loaded models on Ollama host
curl http://localhost:11434/api/ps

# Response shows loaded models and memory usage
```

### Monitor Performance Impact

```bash
# Check celery worker logs for timing
docker compose logs celery-worker -f | grep "CONTEXTUAL"

# Example output:
# [CONTEXTUAL] LLM call completed in 8.78s (total: 8.78s)  # Model already loaded
# [CONTEXTUAL] LLM call completed in 11.78s (total: 11.78s) # Model loading included
```

## Future Improvements

### If Ollama Adds Prompt Caching

When Ollama implements Anthropic-style prompt caching:

1. **Update `document_processor.py`**:
   ```python
   # Cache the full document context once
   cached_context = llm.cache_prompt(document_text)

   # Reuse cached context for each chunk
   for chunk in chunks:
       context = llm.complete_with_cache(cached_context, chunk)
   ```

2. **Expected Impact**:
   - Up to 90% cost reduction (if using cloud Ollama)
   - Potentially 50-70% time reduction for contextual retrieval
   - Would make contextual retrieval much more practical

3. **Watch**:
   - GitHub Issue #1573: https://github.com/ollama/ollama/issues/1573
   - GitHub Issue #2023: https://github.com/ollama/ollama/issues/2023

### Alternative: Switch to Anthropic Claude

If prompt caching is critical:

1. **Configuration Change**:
   ```yaml
   # Use Anthropic Claude instead of Ollama for contextual retrieval
   - CONTEXTUAL_LLM_PROVIDER=anthropic
   - ANTHROPIC_API_KEY=sk-...
   - ANTHROPIC_MODEL=claude-3-haiku-20240307  # Fast, cheap model
   ```

2. **Expected Cost**: $1.02 per million document tokens (one-time)

3. **Expected Speed**: Comparable to current Ollama performance with caching

## Related Documentation

- [Performance Analysis](PERFORMANCE_ANALYSIS.md) - Document processing bottlenecks
- [Phase 2 Implementation](PHASE2_IMPLEMENTATION_SUMMARY.md) - Contextual retrieval implementation
- [CLAUDE.md](../CLAUDE.md) - System architecture

## References

- **Ollama Keep-Alive**: https://github.com/ollama/ollama/blob/main/docs/faq.md#how-do-i-keep-a-model-loaded-in-memory
- **Ollama KV Cache Quantization**: https://smcleod.net/2024/12/bringing-k/v-context-quantisation-to-ollama/
- **Ollama Caching Strategies**: https://markaicode.com/ollama-caching-strategies-improve-repeat-query-performance/
- **Prompt Caching Issue #1573**: https://github.com/ollama/ollama/issues/1573
- **Prompt Caching Issue #2023**: https://github.com/ollama/ollama/issues/2023
