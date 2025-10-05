# Reranker Research for RAG System

## Executive Summary

Research conducted on October 5, 2025 for implementing rerankers in private, on-premise RAG systems.

## Reranker Implementation Strategy

### Current Available Local Models

```
NAME                       ID              SIZE      MODIFIED
gemma3:4b                  a2af6cc3eb7f    3.3 GB    2 days ago
qwen3-embedding:8b         64b933495768    4.7 GB    2 days ago
qwen3:8b                   500a1f067a9f    5.2 GB    8 weeks ago
qwen3:0.6b                 7df6b6e09427    522 MB    8 weeks ago
nomic-embed-text:latest    0a109f422b47    274 MB    2 months ago
gemma3:12b                 f4031aab637d    8.1 GB    6 months ago
llama3.2:latest            a80c4f17acd5    2.0 GB    6 months ago
```

### Recommended Models for Reranking

**From Available Models:**
- **Best:** `gemma3:4b` (3.3GB) - Good instruction-following for LLM-based reranking
- **Alternative:** `llama3.2:latest` (2GB) - Smaller, faster

**Best to Download (Oct 2025):**
- **Qwen3-Reranker:0.6b** (~500MB) - State-of-the-art, MTEB #1, ultra-fast
- **Qwen3-Reranker:4b** (~3.3GB) - Highest quality under 10B params
- Purpose-built for reranking (better than repurposing chat LLMs)

Download: `ollama pull dengcao/Qwen3-Reranker-4B:Q5_K_M`

### Cross-Encoder vs LLM Reranking Performance

**Cross-Encoder Strengths:**
- Remain competitive against LLM-based rerankers
- Far more efficient (100-300ms overhead)
- More robust zero-shot ranking than single vector models
- Better for straightforward relevance scoring

**LLM Reranker Strengths:**
- GPT-4 provides remarkable zero-shot performance
- Better for complex tasks (e.g., candidate search based on job descriptions)
- Open LLMs under-perform compared to GPT-4 but still exhibit good ranking abilities

**Verdict:** Cross-encoders offer best balance for on-prem deployment

## Recommended Implementation: Combined Strategy

### Dynamic Threshold-Based Filtering

Instead of hardcoded `top_n=3`, use similarity threshold to:
- Include all relevant results (e.g., 6 chunks if all relevant)
- Exclude irrelevant context (e.g., only 2 chunks if others aren't relevant)
- Prevent LLM from getting confused by irrelevant context
- Enable better "I don't know" responses when low scores detected

### Implementation Code

```python
# Combined Strategy in rag_pipeline.py
from llama_index.core.postprocessors import (
    SentenceTransformerRerank,
    SimilarityPostprocessor
)

node_postprocessors = [
    # Stage 1: Rerank all candidates
    SentenceTransformerRerank(
        model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        top_n=10  # Consider all retrieved, don't filter yet
    ),
    # Stage 2: Filter by relevance threshold
    SimilarityPostprocessor(
        similarity_cutoff=0.65  # Only keep nodes above this score
    )
]

query_engine = index.as_query_engine(
    similarity_top_k=10,  # High recall - retrieve more candidates
    node_postprocessors=node_postprocessors,
    text_qa_template=qa_prompt
)
```

### Environment Variables

```yaml
RERANKER_MODEL: "cross-encoder/ms-marco-MiniLM-L-6-v2"
RERANKER_SIMILARITY_THRESHOLD: "0.65"
RETRIEVAL_TOP_K: "10"
ENABLE_RERANKER: "true"
```

### Architecture Changes

1. **Increase initial retrieval:** `similarity_top_k=10` (high recall)
2. **Add reranker postprocessor:** Re-scores all 10 candidates
3. **Apply threshold filter:** Narrows to N results where N = count(score > 0.65)
4. **Result:** Between 0-10 nodes based on actual relevance

### Dependencies to Add

```toml
# In pyproject.toml
dependencies = [
    # ... existing deps ...
    "llama-index-postprocessor-sentencetransformer-rerank>=0.4.0",
]
```

### Migration Path

1. Add reranker as opt-in via env var `ENABLE_RERANKER=false`
2. Test in development
3. Enable by default once validated
4. Support multiple reranker backends via strategy pattern (like prompt strategies)

## Docling and Reranking

**Docling does NOT provide reranking functionality.**

### Role Distinction

**Docling's Role:**
- Document parsing only
- Converts PDFs, DOCX, PPTX, etc. into structured text
- Layout understanding (tables, headings, paragraphs)
- Chunking via `DoclingNodeParser`

**Reranker's Role:**
- Post-retrieval processing
- Works AFTER vector search retrieves candidates
- Re-scores chunks based on query relevance
- Filters to keep only most relevant chunks

### Pipeline Stages

```
1. Docling (parsing)
   └─> PDF/DOCX → structured nodes

2. Embedding (indexing)
   └─> nodes → vectors → ChromaDB

3. Retrieval (search)
   └─> query → top-10 similar nodes

4. Reranker (NEW)
   └─> re-score top-10 → filter by threshold

5. LLM (generation)
   └─> filtered nodes → answer
```

### Research Finding

Study found best-performing configuration:
- **Docling parsing** + semantic chunking
- **Nomic embeddings**
- **BGE reranking**
- **Qwen3:4b prompting**

Confirms Docling + reranking work together but handle different stages.

## Framework Comparison

### LlamaIndex

**Reranker Support:**
- ✅ Built-in `SentenceTransformerRerank`
- ✅ Built-in `SimilarityPostprocessor` (threshold filtering)
- ✅ Native `DoclingReader` and `DoclingNodeParser`
- ✅ Simple integration via `node_postprocessors` parameter

**Recommendation:** Best fit for current stack

### Haystack 2.x

**Reranker Support:**
- ✅ `SentenceTransformersSimilarityRanker` (recommended)
- ✅ `TransformersSimilarityRanker` (legacy, being deprecated)
- ✅ `CohereRanker` (API-based)
- ✅ `NvidiaRanker` (NeMo)
- ❌ No native Ollama reranker component

**Ollama Integration:**
- ✅ Text generation (`OllamaGenerator`)
- ✅ Embeddings (via custom components)
- ❌ No native Ollama reranker component

**Why No Ollama Reranker:**
- Ollama doesn't expose reranking API endpoint
- Only `/generate` and `/embeddings` available
- Models like `qwen3-reranker` need custom implementation

**Recommendation:** More enterprise features (evaluation, pipelines-as-DAGs) but not worth switching from LlamaIndex for this use case

## On-Premise Private RAG Recommendations

### Complete End-to-End Solutions

#### Tier 1: Production-Ready Platforms

**RAGFlow**
- Self-hosted web UI + API
- Built-in document processing, chunking strategies
- Multi-user with access controls
- Docker deployment
- Best for: Teams wanting turnkey solution

**Danswer/Onyx**
- Enterprise Q&A platform
- Slack/Teams integration
- Multi-connector (Google Drive, Confluence, GitHub)
- User permissions, audit logs
- Best for: Enterprise knowledge management

**PrivateGPT**
- 100% air-gapped operation
- Offline-first design
- Simple setup, minimal dependencies
- Best for: Maximum privacy, single-user

### Framework-Based Stacks (Tier 2)

**Recommended Build-Your-Own Stack:**

```yaml
Document Processing: Docling
Orchestration:       LLMWare (privacy-focused) or LlamaIndex
Vector DB:           Qdrant or Milvus
Embeddings:          Ollama (nomic-embed-text)
LLM:                 Ollama (llama3.2, qwen3, gemma3)
Reranker:            SentenceTransformers cross-encoder
API Layer:           FastAPI
```

### Vector Database Comparison (On-Prem)

| Database | Deployment | Privacy Features | Performance | Best For |
|----------|-----------|------------------|-------------|----------|
| **Qdrant** | Docker, K8s | Encryption, RBAC, payload filtering | Fast, low overhead | Small-medium scale |
| **Milvus** | Docker, K8s, Helm | Encryption, RBAC, anonymization | Highest performance | Large scale, complex queries |
| **Weaviate** | Docker, K8s | Encryption, hybrid search, anonymization | Good hybrid search | Multi-modal data |
| **ChromaDB** | Docker, embedded | Basic encryption | Lightweight | Development, prototypes |

**Recommendation for Privacy:**
- **Qdrant** - Easiest on-prem setup
- **Milvus** - Best performance and features

**Privacy Features (All Three):**
- Built-in encryption at rest and in transit
- RBAC (Role-Based Access Control)
- Anonymization techniques
- Payload filtering to exclude sensitive fields
- Tenant isolation via collections/namespaces
- VPC peering or private link support

### LLM Options (On-Prem, <16GB RAM)

**Privacy-First Models (Oct 2025):**

1. **Qwen3:8b** (available)
   - Excellent quality/size ratio
   - Good instruction following

2. **Gemma3:4b** (available)
   - Google's efficient model
   - Fast on M2

3. **Llama3.2:3b**
   - `ollama pull llama3.2:3b`
   - Latest Meta release
   - Better than 3.2:1b

4. **Phi-4:14b** (recommended download)
   - `ollama pull phi-4:14b`
   - Microsoft's January 2025 release
   - Best <16GB model currently available
   - State-of-the-art reasoning

### Complete Privacy-Preserving Architecture

```
┌─────────────────────────────────────────────┐
│         Air-Gapped On-Prem Network          │
├─────────────────────────────────────────────┤
│                                             │
│  [FastAPI Web App] ← Users (internal only) │
│         ↓                                   │
│  [RAG Server]                               │
│    ├─ Docling (document parsing)           │
│    ├─ Ollama (embeddings + LLM)            │
│    ├─ SentenceTransformers (reranker)      │
│    └─ LlamaIndex/LLMWare (orchestration)   │
│         ↓                                   │
│  [Qdrant/Milvus] (vector DB)               │
│    ├─ Encrypted at rest                    │
│    ├─ RBAC enabled                          │
│    └─ Anonymization filters                │
│                                             │
│  All data stays within your network         │
│  No external API calls                      │
└─────────────────────────────────────────────┘
```

## Privacy Best Practices (2025)

### 1. Data Governance & Access Control
- Implement robust data governance practices
- Privacy-preserving techniques throughout RAG workflow
- Access controls from ingestion to storage
- Encrypt data at rest and in transit
- Implement context-aware data filtering

### 2. Data Minimization
- Don't store more data than needed
- Core requirement of data protection laws
- Implement retention policies
- Auto-delete old embeddings

### 3. Differential Privacy & Anonymization
- Differential privacy: controlled noise in datasets
- Ensures individual data points remain indistinguishable
- Anonymize customer/internal data before storing
- Prevent privacy violations

### 4. Complete On-Premise Deployment
- No data sent to outside vendors
- Everything on-premises:
  - Vector database
  - Embedding model
  - LLM
  - Document processing

### 5. Vector Database Security
- Embeddings can contain PII
- Vulnerable to data leaks via inversion methods
- Regular security monitoring
- Use tokenization for sensitive data
- Implement RBAC with team-specific permissions

### 6. Network Isolation
- Private VLANs
- No internet access for processing nodes
- VPC peering or private link

### 7. Audit Logging
- Track all queries
- Log document access
- Monitor for security breaches
- Enable quick detection and response

## Current Stack Assessment

### Keep
- ✅ Docling (best document parser)
- ✅ Ollama (local LLMs)
- ✅ FastAPI (good API layer)
- ✅ LlamaIndex (solid orchestration)

### Consider Changing
- ⚠️ **ChromaDB → Qdrant/Milvus**
  - Reason: Better RBAC, encryption, enterprise features
  - Benefit: Improved privacy controls

- ⚠️ **Add data anonymization layer**
  - Strip PII before embedding
  - Tokenization for sensitive fields

- ⚠️ **Add audit logging**
  - Track queries and document access
  - Security monitoring

## Key Research Sources

### Reranking Models
- Qwen3-Reranker: MTEB #1 multilingual (score 70.58, June 2025)
- Best configuration: Docling + semantic chunking + Nomic embeddings + BGE reranking
- Cross-encoders remain competitive vs LLM rerankers while being far more efficient

### Privacy Trends
- Increasing demand for frameworks prioritizing security and private deployment
- Stricter data privacy regulations in 2025
- Open-source frameworks provide complete control over data processing
- Self-hosted vector stores offer maximum security control

### Framework Maturity
- LlamaIndex: Best for RAG with sophisticated indexing
- Haystack: Mature, production-ready NLP systems
- LLMWare: Privacy-focused, enterprise-grade
- RAGFlow: Complete platform with UI
