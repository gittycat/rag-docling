# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local RAG system with two FastAPI services using Docling + LlamaIndex for document processing, ChromaDB for vector storage, and Ollama for LLM inference.

## Architecture

**Two-Service Design:**
- `fastapi_web_app` (port 8000): User-facing web interface
- `rag-server` (port 8001): Backend RAG processing service

**Network Isolation:**
- `public` network: Web app accessible from host
- `private` network: Internal services (ChromaDB, RAG server communication)
- Ollama runs on host machine at `http://host.docker.internal:11434`

**Document Processing Flow:**
1. Documents uploaded → `rag-server` `/upload` endpoint
2. DoclingReader parses (PDF/DOCX/PPTX/XLSX/HTML) → DoclingNodeParser creates nodes
3. LlamaIndex OllamaEmbedding generates vectors (qwen3-embedding:8b, 768-dim)
4. Stored in ChromaDB via VectorStoreIndex
5. Query → retrieval (top-k=10) → reranking → threshold filtering → LLM (gemma3:4b) generates answer

**Key Implementation Pattern:**
- Documents stored as nodes with `document_id` metadata
- Each node has ID: `{doc_id}-chunk-{i}`
- Deletion removes all nodes with matching `document_id`
- Two-stage retrieval: High-recall embedding search (top-10) → precision reranking (threshold-based)
- Dynamic context: Returns 0-10 nodes based on relevance scores, not fixed top-k
- Uses query_engine with custom PromptTemplate (4 strategies: fast, balanced, precise, comprehensive)

## Common Commands

### Development

```bash
# Start services (requires Ollama running on host)
docker compose up -d

# Build after dependency changes
docker compose build

# View logs
docker compose logs -f rag-server
docker compose logs -f fastapi_web_app

# Stop services
docker compose down -v
```

### Testing

```bash
# RAG Server tests (33 core tests + 27 evaluation tests)
cd services/rag_server
uv sync
.venv/bin/pytest -v

# Run single test
.venv/bin/pytest tests/test_document_processing.py::test_chunk_document -v

# Evaluation tests only (27 tests)
.venv/bin/pytest tests/evaluation/ -v

# Web App tests (21 tests)
cd services/fastapi_web_app
uv sync
uv run pytest -v
```

### Evaluation

```bash
# Setup evaluation dependencies
cd services/rag_server
uv sync --group eval

# Run sample evaluation
.venv/bin/python evaluation/eval_runner.py

# Run evaluation tests
.venv/bin/pytest tests/evaluation/ -v
```

### Local Development

```bash
# Install dependencies for a service
cd services/rag_server
uv sync

# Add new dependency
uv add package-name

# Update dependencies
uv sync --upgrade
```

## Critical Implementation Details

### Docling + LlamaIndex Integration

**Document Processing** (`services/rag_server/core_logic/document_processor.py`):
- `DoclingReader` from `llama-index-readers-docling` loads documents
- **CRITICAL**: Must use `DoclingReader(export_type=DoclingReader.ExportType.JSON)` - DoclingNodeParser requires JSON format, not default MARKDOWN
- `DoclingNodeParser` from `llama-index-node-parser-docling` creates nodes
- ChromaDB metadata must be flat types (str, int, float, bool, None) - complex types filtered via `clean_metadata_for_chroma()`
- Returns LlamaIndex Node objects

**Embeddings** (`services/rag_server/core_logic/embeddings.py`):
- `OllamaEmbedding` from `llama-index-embeddings-ollama`
- Model: `nomic-embed-text` (parameter: `model_name`)
- URL from `OLLAMA_URL` env var

**Vector Store** (`services/rag_server/core_logic/chroma_manager.py`):
- `ChromaVectorStore` wraps ChromaDB collection
- `VectorStoreIndex.from_vector_store()` creates index
- `index.insert_nodes()` adds documents
- `index.as_retriever()` for retrieval operations
- Direct ChromaDB access via `._vector_store._collection` for deletion/listing

**LLM** (`services/rag_server/core_logic/llm_handler.py`):
- `Ollama` from `llama-index-llms-ollama`
- Returns prompt templates (not direct LLM calls)
- 4 strategies: fast, balanced (default), precise, comprehensive

**RAG Pipeline** (`services/rag_server/core_logic/rag_pipeline.py`):
- `PromptTemplate` wraps strategy-specific template string
- `index.as_query_engine()` with `text_qa_template=qa_prompt`
- Two-stage node postprocessing:
  1. `SentenceTransformerRerank`: Cross-encoder reranks top-10 results
  2. `SimilarityPostprocessor`: Filters nodes below threshold (default: 0.65)
- `query_engine.query()` handles retrieval + reranking + generation
- Returns sources from `response.source_nodes` (dynamic 0-10 nodes)

**Reranking Strategy**:
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80MB, HuggingFace)
- Auto-downloads from HuggingFace on first query (NOT from Ollama)
- Cached in `~/.cache/huggingface/` for subsequent queries
- Combined approach: Rerank ALL retrieved nodes, then apply similarity threshold
- Adaptive context window: Only includes nodes above relevance threshold
- Configurable via env vars: `ENABLE_RERANKER`, `RERANKER_MODEL`, `RERANKER_SIMILARITY_THRESHOLD`, `RETRIEVAL_TOP_K`
- Can be disabled by setting `ENABLE_RERANKER=false`

**Settings** (`services/rag_server/core_logic/settings.py`):
- Global `Settings.llm` and `Settings.embed_model`
- Initialized on app startup via `@app.on_event("startup")`

### Docker Build Issues

**PyTorch CPU Index Problem:**
The Dockerfile uses `--index-strategy unsafe-best-match` because:
- PyTorch CPU index has old package versions (e.g., certifi==2022.12.7)
- Docling requires newer versions from PyPI
- uv's default "first match wins" prevents finding newer versions
- Solution: Allow checking all indexes for best version

```dockerfile
RUN uv sync --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match
```

### Environment Setup

**Prerequisites:**
- Docker & Docker Compose v2+
- Ollama running on host with models:
  - `ollama pull gemma3:4b` (LLM)
  - `ollama pull qwen3-embedding:8b` (embeddings)
- Reranker model auto-downloads from HuggingFace (no manual installation needed)

**Environment Variables:**
- Web App: `RAG_SERVER_URL=http://rag-server:8001`
- RAG Server (required): `CHROMADB_URL`, `OLLAMA_URL`, `EMBEDDING_MODEL`, `LLM_MODEL`, `PROMPT_STRATEGY`
- RAG Server (reranker): `ENABLE_RERANKER=true`, `RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2`, `RERANKER_SIMILARITY_THRESHOLD=0.65`, `RETRIEVAL_TOP_K=10`

### Testing

**Mocking:**
- `DoclingReader` and `DoclingNodeParser` mocked to return Node objects
- LlamaIndex components mocked via `@patch`
- VectorStoreIndex mocked with `._vector_store._collection` for ChromaDB access

**Test Files:**
- `test_embeddings.py`: OllamaEmbedding with `model_name` parameter
- `test_document_processing.py`: DoclingReader → DoclingNodeParser
- `test_chroma_collection.py`: VectorStoreIndex operations

## API Endpoints

**RAG Server** (port 8001):
- `POST /query`: query_engine.query() with custom PromptTemplate
- `GET /documents`: List all indexed documents (grouped by document_id)
- `POST /upload`: Upload documents (supports multiple files)
- `DELETE /documents/{document_id}`: Delete document and all nodes

**Supported Formats:**
`.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, `.xlsx`, `.html`, `.htm`, `.asciidoc`, `.adoc`

## Key Files

**Core Pipeline:**
- `services/rag_server/core_logic/rag_pipeline.py`: query_engine with reranking + PromptTemplate
- `services/rag_server/core_logic/document_processor.py`: DoclingReader + DoclingNodeParser
- `services/rag_server/core_logic/chroma_manager.py`: VectorStoreIndex
- `services/rag_server/core_logic/embeddings.py`: OllamaEmbedding
- `services/rag_server/core_logic/llm_handler.py`: Ollama LLM + PromptTemplate strategies
- `services/rag_server/core_logic/settings.py`: Global Settings initialization
- `services/rag_server/core_logic/env_config.py`: Required and optional env var helpers
- `services/rag_server/main.py`: FastAPI endpoints

**Evaluation System:**
- `services/rag_server/evaluation/ragas_config.py`: Ollama configuration for RAGAS
- `services/rag_server/evaluation/retrieval_eval.py`: Context Precision/Recall, Hit Rate, MRR
- `services/rag_server/evaluation/reranking_eval.py`: Precision@K, NDCG comparison
- `services/rag_server/evaluation/generation_eval.py`: Faithfulness, Answer Relevancy, Correctness
- `services/rag_server/evaluation/end_to_end_eval.py`: Combined pipeline evaluation
- `services/rag_server/evaluation/report_generator.py`: Text + JSON reports
- `services/rag_server/evaluation/eval_runner.py`: Sample evaluation script
- `services/rag_server/eval_data/golden_qa.json`: Test Q&A dataset (10 pairs)
- `services/rag_server/eval_data/documents/`: Test documents (Paul Graham essays)

## Web App Styling & Templates

### Template Architecture

**Jinja2 Template Inheritance:**
The web app uses Jinja2's template inheritance pattern with a base template that all pages extend. This follows the official Jinja2 recommended approach for maintaining consistent layouts.

**Base Template** (`services/fastapi_web_app/templates/base.html`):
- Common HTML structure, meta tags, and Tailwind CSS configuration
- Dark mode initialization script (runs before page render to prevent flash)
- Theme toggle button with sun/moon icons
- Navigation bar structure
- Reusable template blocks for customization

**Template Blocks:**
```jinja2
{% block title %}        # Page title
{% block extra_head %}   # Additional <head> content (styles, meta tags)
{% block body_class %}   # Custom body classes
{% block navigation %}   # Override entire nav (rare)
{% block nav_links %}    # Just the nav links (common)
{% block content %}      # Main page content (required)
{% block extra_scripts %}# Page-specific JavaScript
```

**Template Files:**
- `base.html`: Base layout with dark mode support
- `home.html`: Search interface (centered form when empty, results view when populated)
- `admin.html`: Document management (upload, list, delete)
- `about.html`: Project information page
- `results.html`: Search results display
- `upload_progress.html`: Real-time upload progress with SSE

**Usage Pattern:**
```jinja2
{% extends "base.html" %}

{% block title %}Page Title{% endblock %}

{% block content %}
<!-- Page-specific HTML -->
{% endblock %}

{% block extra_scripts %}
<script>
// Page-specific JavaScript
</script>
{% endblock %}
```

### Dark/Light Mode Implementation

**Strategy:**
- Class-based dark mode using Tailwind CSS (`darkMode: 'class'`)
- Theme stored in `localStorage` for persistence across sessions
- System preference detection on first visit via `prefers-color-scheme`
- Theme initialization script in `<head>` prevents flash of wrong theme

**Theme Toggle:**
```javascript
// Auto-detects system preference on first visit
const theme = localStorage.getItem('theme') ||
              (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

// Toggle via button click
document.documentElement.classList.toggle('dark');
localStorage.setItem('theme', isDark ? 'light' : 'dark');
```

**Theme State:**
- Light mode: No `dark` class on `<html>`
- Dark mode: `dark` class on `<html>`
- Persists across page navigation via localStorage

### Styling System

**Framework:** Tailwind CSS 3.x via CDN
- Utility-first CSS framework
- No build step required (CDN approach)
- Custom configuration for dark mode

**Configuration:**
```javascript
tailwind.config = {
    darkMode: 'class'  // Class-based dark mode
}
```

**Design System:**

**Color Palette:**
| Element | Light Mode | Dark Mode |
|---------|-----------|-----------|
| **Backgrounds** |
| Primary | `bg-white` | `dark:bg-gray-900` |
| Secondary | `bg-gray-50` | `dark:bg-gray-800` |
| Tertiary | `bg-gray-100` | `dark:bg-gray-700` |
| **Text** |
| Primary | `text-gray-900` | `dark:text-gray-100` |
| Secondary | `text-gray-600` | `dark:text-gray-400` |
| Tertiary | `text-gray-500` | `dark:text-gray-500` |
| **Borders** |
| Default | `border-gray-200` | `dark:border-gray-700` |
| Light | `border-gray-300` | `dark:border-gray-600` |
| **Buttons** |
| Primary | `bg-blue-600 hover:bg-blue-700` | `dark:bg-blue-500 dark:hover:bg-blue-600` |
| Success | `bg-green-600 hover:bg-green-700` | `dark:bg-green-500 dark:hover:bg-green-600` |
| Danger | `bg-red-600 hover:bg-red-900` | `dark:bg-red-400 dark:hover:bg-red-300` |
| **Accents** |
| Highlight | `bg-blue-50` | `dark:bg-blue-900/30` |
| Code | `bg-gray-100` (rgba 0.1) | `dark:bg-gray-400/20` |

**Typography:**
- Base font size: `text-base` (1rem / 16px)
- Headings: `text-3xl` (h1), `text-xl` (h2), `text-sm` (h3)
- Line height: `leading-relaxed` for body text

**Transitions:**
```css
transition-colors duration-200  /* Smooth theme switching */
```

**Special Styling:**

**Answer Content** (Markdown rendered from LLM):
```css
.answer-content code {
    background-color: rgba(107, 114, 128, 0.1);
    /* dark mode: rgba(156, 163, 175, 0.2) */
}

.answer-content pre {
    background-color: rgba(107, 114, 128, 0.05);
    /* dark mode: rgba(31, 41, 55, 0.5) */
}
```

### Layout Patterns

**Centered Search (home.html - no results):**
```css
flex flex-col items-center justify-center  /* Vertical centering */
max-w-3xl mx-auto                          /* Horizontal centering */
```

**Results View (home.html - with results):**
```css
mt-20 pb-24         /* Top margin, bottom padding for fixed input */
fixed bottom-0      /* Fixed bottom search bar */
```

**Admin Table:**
```css
hover:bg-gray-50 dark:hover:bg-gray-700/50  /* Row hover */
divide-y divide-gray-200 dark:divide-gray-700  /* Row dividers */
```

**LLM Context Dropdown:**
```html
<details class="group">
  <summary>...</summary>
  <!-- Tailwind group-open: for arrow rotation -->
</details>
```

### Validation

**Template Syntax Validation:**
```bash
cd services/fastapi_web_app
uv run python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('templates'))
env.get_template('base.html')  # Validates syntax
"
```

**Expected Output:**
```
✓ base.html: Valid
✓ home.html: Valid
✓ admin.html: Valid
✓ about.html: Valid
✓ results.html: Valid
✓ upload_progress.html: Valid
```

### Best Practices

**1. Extending Templates:**
- Always use `{% extends "base.html" %}` as first line
- Override only necessary blocks
- Use `{{ super() }}` to include parent block content when extending

**2. Dark Mode Utilities:**
- Always pair light and dark variants: `bg-white dark:bg-gray-900`
- Test both themes during development
- Use semantic color names (primary, secondary) in comments

**3. Responsive Design:**
- Use Tailwind responsive prefixes: `sm:px-6 lg:px-8`
- Mobile-first approach (base styles = mobile)
- Test with `w-full` and `max-w-*` containers

**4. Accessibility:**
- Include `aria-label` on icon buttons
- Use semantic HTML (`<nav>`, `<main>`, `<section>`)
- Maintain sufficient color contrast in both themes

**5. Performance:**
- Theme initialization before DOM render prevents flash
- Transitions limited to `transition-colors` (cheap)
- CDN Tailwind CSS for quick prototyping (consider build step for production)

### Common Styling Tasks

**Adding a New Page:**
```jinja2
{% extends "base.html" %}

{% block title %}New Page{% endblock %}

{% block nav_links %}
<a href="/">Home</a>
<span class="text-gray-400 dark:text-gray-500">New Page</span>
{% endblock %}

{% block content %}
<main class="max-w-5xl mx-auto mt-24 px-4">
    <!-- Page content -->
</main>
{% endblock %}
```

**Custom Theme Toggle Position:**
```jinja2
{% block navigation %}
<!-- Override entire nav -->
<nav class="custom-layout">
    <button id="themeToggle">...</button>
</nav>
{% endblock %}
```

**Page-Specific Styles:**
```jinja2
{% block extra_head %}
<style>
.custom-element {
    /* Page-specific CSS */
}
</style>
{% endblock %}
```

## Common Issues

**Ollama not accessible:** Check `host.docker.internal` resolves correctly. Verify with:
```bash
docker compose exec rag-server curl http://host.docker.internal:11434/api/tags
```

**ChromaDB connection fails:** ChromaDB on private network only. RAG server must be on same network.

**Docker build fails with certifi error:** Ensure `--index-strategy unsafe-best-match` is in Dockerfile RUN command.

**Tests fail with ModuleNotFoundError:** Use `.venv/bin/pytest` directly instead of `uv run pytest` to avoid path issues.

**Reranker performance:** First query downloads cross-encoder model from HuggingFace (~80MB). Subsequent queries use cached model from `~/.cache/huggingface/`. Adds ~100-300ms latency per query. Disable with `ENABLE_RERANKER=false` if not needed.

**Tuning reranker threshold:** Lower `RERANKER_SIMILARITY_THRESHOLD` (e.g., 0.5) for broader information, raise (e.g., 0.75) for more precise responses. Monitor "I don't know" frequency - too high means threshold is too strict.

## Troubleshooting History

**Historical Issues & Fixes:**
See `docs/troubleshooting/` for detailed diagnostic reports:
- `2025-10-09-retrieval-failure.md`: Initial investigation of document upload failure (DoclingReader/DoclingNodeParser format mismatch)
- `2025-10-09-retrieval-fix.md`: Complete root cause analysis and fix implementation (JSON export format, ChromaDB metadata compatibility, retrieval coverage tuning)

**Key Lessons Learned:**
1. DoclingReader defaults to MARKDOWN export but DoclingNodeParser requires JSON - always specify `export_type=DoclingReader.ExportType.JSON`
2. ChromaDB only accepts flat metadata types (str/int/float/bool/None) - filter complex types before insertion
3. Docling's granular chunking (9-27K char range) fragments answers across chunks - reranking + higher top-k (10) improves coverage
4. Answer quality tuning via reranker threshold: 0.65 balanced, <0.6 broader, >0.7 stricter

## RAG Evaluation System

**Architecture:**
Comprehensive evaluation using RAGAS framework configured with local Ollama models. Evaluates three pipeline stages: retrieval quality, reranking effectiveness, and generation quality. All metrics use LLM-as-judge approach with `gemma3:4b` as the evaluator.

**Evaluation Philosophy:**
- Component-wise evaluation (retrieval, reranking, generation) + end-to-end
- Reference-free metrics where possible (Context Precision, Faithfulness, Answer Relevancy)
- Reference-based metrics when ground truth available (Context Recall, Answer Correctness)
- Quantitative thresholds for pass/fail criteria
- Track metric trends over time for regression detection

### Evaluation Datasets

**Location:** `services/rag_server/eval_data/`

**Test Documents** (`eval_data/documents/`):
- Paul Graham essays: `greatwork.html` (78KB), `talk.html` (11KB), `conformism.html` (20KB)
- Total: 3 documents, diverse topics (work, writing, society)
- HTML format parsed by Docling for realistic pipeline testing

**Golden Q&A Dataset** (`eval_data/golden_qa.json`):
- 10 question-answer pairs covering all 3 documents
- Mix of query types: factual (direct lookup) and reasoning (inference)
- Each entry includes:
  - `question`: User query
  - `answer`: Ground truth answer
  - `document`: Source document filename
  - `context_hint`: Where in document to find answer
  - `query_type`: "factual" or "reasoning"

**Dataset Format:**
```json
[
  {
    "question": "What are the three qualities for great work?",
    "answer": "Natural aptitude, deep interest, and scope to do great work.",
    "document": "greatwork.html",
    "context_hint": "The essay discusses the first step",
    "query_type": "factual"
  }
]
```

### Evaluation Metrics

**Retrieval Metrics** (Target: >0.85 precision, >0.90 recall):
- **Context Precision**: Signal-to-noise ratio of retrieved contexts (0-1 scale)
  - Measures how many retrieved chunks are actually relevant
  - Uses LLM to judge relevance of each context to the query
  - High precision = less noise in retrieved results
- **Context Recall**: Completeness of retrieved information (0-1 scale)
  - Measures if all needed information was retrieved
  - Requires ground truth answer for comparison
  - High recall = pipeline doesn't miss relevant information
- **Hit Rate@K**: Percentage of queries with ≥1 relevant result in top-K
  - Traditional IR metric, simpler than LLM-based metrics
  - Default K=10 matches retrieval top-k
- **MRR**: Mean Reciprocal Rank of first relevant result
  - Measures how high relevant results appear in ranking
  - 1/position of first relevant hit, averaged across queries

**Reranking Metrics** (Target: >15% P@1 improvement, >10% NDCG improvement):
- **Precision@1 / Precision@3**: Relevant results in top-1/top-3 positions
  - Compare before vs after reranking
  - Improvement % quantifies reranker effectiveness
- **NDCG@10**: Normalized Discounted Cumulative Gain
  - Measures ranking quality (higher rank = better)
  - Accounts for position of relevant results
  - NDCG increase shows reranker improves ordering

**Generation Metrics** (Target: >0.90 faithfulness, >0.85 relevancy):
- **Faithfulness**: Factual accuracy against retrieved contexts (0-1 scale)
  - LLM checks if answer claims are supported by contexts
  - Detects hallucinations (unsupported statements)
  - High faithfulness = no hallucinations
- **Answer Relevancy**: How well answer addresses the query (0-1 scale)
  - LLM compares question intent to answer content
  - Checks completeness and directness
  - Low relevancy = incomplete or off-topic answers
- **Answer Correctness**: Semantic similarity to ground truth (0-1 scale)
  - Requires reference answer
  - Combines semantic similarity and factual overlap
  - Optional metric (only when ground truth available)

**Overall Score**: Average of all available metrics (target >0.85)

### Evaluation Module Structure

**Core Components:**

`services/rag_server/evaluation/ragas_config.py`:
- `RagasOllamaConfig`: Configures RAGAS to use Ollama instead of OpenAI
- Wraps `ChatOllama` (gemma3:4b) and `OllamaEmbeddings` (qwen3-embedding:8b)
- Default timeout: 300s (increase for large datasets)
- Pattern: LangChain models → LangchainLLMWrapper → RAGAS evaluators

`services/rag_server/evaluation/data_models.py`:
- `EvaluationSample`: Input format (user_input, retrieved_contexts, response, reference)
- `RetrievalEvaluationResult`: Context Precision/Recall scores + per-sample results
- `GenerationEvaluationResult`: Faithfulness/Relevancy/Correctness scores
- `EndToEndEvaluationResult`: Combined metrics with overall score

`services/rag_server/evaluation/retrieval_eval.py`:
- `RetrievalEvaluator`: Runs Context Precision/Recall via RAGAS
- `calculate_hit_rate()`: Traditional IR metric (top-K hit rate)
- `calculate_mrr()`: Mean Reciprocal Rank calculation
- Uses `datasets.Dataset` for RAGAS compatibility

`services/rag_server/evaluation/reranking_eval.py`:
- `RerankingEvaluator`: Compares before/after reranking
- `calculate_precision_at_k()`: Precision@1, Precision@3
- `calculate_ndcg()`: NDCG@10 ranking quality
- `compare_reranking()`: Returns improvement percentages

`services/rag_server/evaluation/generation_eval.py`:
- `GenerationEvaluator`: Runs Faithfulness/Relevancy/Correctness via RAGAS
- Async evaluation support (`evaluate_async()`)
- Optional Answer Correctness (only if all samples have references)

`services/rag_server/evaluation/end_to_end_eval.py`:
- `EndToEndEvaluator`: Combines retrieval + generation evaluation
- Runs both evaluators in parallel (async)
- Calculates overall score as metric average

`services/rag_server/evaluation/dataset_loader.py`:
- `load_golden_qa_dataset()`: Loads eval_data/golden_qa.json
- `GoldenQA` Pydantic model for type safety
- `load_default_dataset()`: Convenience function

`services/rag_server/evaluation/report_generator.py`:
- `EvaluationReportGenerator`: Text + JSON report generation
- Status indicators: ✓ Good/Excellent, ⚠ Warning, ✗ Poor
- Threshold-based quality assessment
- Timestamped output files

**Test Files** (27 tests total):
- `tests/evaluation/test_data_models.py`: Pydantic model validation
- `tests/evaluation/test_dataset_loader.py`: Dataset loading
- `tests/evaluation/test_retrieval_eval.py`: Hit Rate, MRR calculation
- `tests/evaluation/test_reranking_eval.py`: Precision, NDCG comparison

### Evaluation Workflow

**1. Setup Dependencies:**
```bash
cd services/rag_server
uv sync --group eval  # Installs ragas>=0.3.5, langchain-ollama>=0.3.10
```

**2. Verify Ollama Models:**
```bash
ollama list | grep -E "gemma3:4b|qwen3-embedding:8b"
# If missing: ollama pull gemma3:4b && ollama pull qwen3-embedding:8b
```

**3. Run Sample Evaluation:**
```bash
.venv/bin/python evaluation/eval_runner.py
# Creates mock samples from golden Q&A dataset
# Outputs text report + JSON results to eval_data/
```

**4. Run Tests:**
```bash
.venv/bin/pytest tests/evaluation/ -v  # 27 tests
```

**5. Integrate with RAG Pipeline:**
```python
from evaluation.dataset_loader import load_default_dataset
from evaluation.data_models import EvaluationSample
from evaluation.end_to_end_eval import EndToEndEvaluator
from core_logic.rag_pipeline import query_with_rag

# Load test questions
golden_qa = load_default_dataset()

# Run RAG for each question
samples = []
for qa in golden_qa:
    response = query_with_rag(qa.question, strategy="balanced")

    sample = EvaluationSample(
        user_input=qa.question,
        retrieved_contexts=[node.text for node in response.source_nodes],
        response=response.response,
        reference=qa.answer
    )
    samples.append(sample)

# Evaluate
evaluator = EndToEndEvaluator()
result = evaluator.evaluate(samples)
print(f"Overall Score: {result.overall_score:.3f}")
```

### Evaluation Implementation Patterns

**Pattern 1: RAGAS Dataset Preparation**
```python
# RAGAS expects datasets.Dataset with specific column names
from datasets import Dataset

data_dict = {
    "user_input": [sample.user_input for sample in samples],
    "retrieved_contexts": [sample.retrieved_contexts for sample in samples],
    "response": [sample.response for sample in samples],
    "reference": [sample.reference or "" for sample in samples],
}
dataset = Dataset.from_dict(data_dict)
```

**Pattern 2: Async Evaluation**
```python
# Evaluation is I/O bound (LLM calls), use async for performance
async def evaluate_async(samples):
    retrieval_task = retrieval_evaluator.evaluate_async(samples)
    generation_task = generation_evaluator.evaluate_async(samples)

    retrieval_result, generation_result = await asyncio.gather(
        retrieval_task, generation_task
    )
    return combine_results(retrieval_result, generation_result)
```

**Pattern 3: Reranking Comparison**
```python
# Run pipeline twice: with and without reranking
# Create matching EvaluationSample lists for comparison

samples_no_rerank = []  # enable_reranker=False
samples_with_rerank = []  # enable_reranker=True

# Must have same queries in same order
rerank_eval = RerankingEvaluator()
comparison = rerank_eval.compare_reranking(
    samples_no_rerank,
    samples_with_rerank
)
```

**Pattern 4: Batch Evaluation for Timeouts**
```python
# Ollama can timeout on large datasets, batch to avoid
batch_size = 5
all_results = []

for i in range(0, len(samples), batch_size):
    batch = samples[i:i+batch_size]
    result = evaluator.evaluate(batch)
    all_results.append(result)

# Aggregate results
combined = aggregate_batch_results(all_results)
```

### Configuration and Tuning

**Timeout Adjustment:**
```python
from evaluation.ragas_config import RagasOllamaConfig

config = RagasOllamaConfig(
    ollama_url="http://localhost:11434",
    llm_model="gemma3:4b",
    embedding_model="qwen3-embedding:8b",
    request_timeout=600.0,  # Increase for slow models/large contexts
)
```

**Custom Evaluator Models:**
```python
# Use different models for evaluation
config = RagasOllamaConfig(
    llm_model="gemma3:2b",  # Faster but less accurate
    # OR
    llm_model="llama3:8b",  # Slower but more accurate
)
```

**Metric Selection:**
```python
# Choose specific metrics to run
from ragas.metrics import context_precision, faithfulness

# Only run retrieval metrics
retrieval_evaluator.metrics = [context_precision]

# Skip Answer Correctness (no ground truth)
generation_result = evaluator.evaluate(samples, include_correctness=False)
```

### Evaluation Results Format

**Text Report Output:**
```
================================================================================
RAG Evaluation Report
Generated: 2025-10-08 19:30:15
================================================================================

RETRIEVAL METRICS
--------------------------------------------------------------------------------
  Context Precision:     0.887 ✓ Good
  Context Recall:        0.923 ✓ Excellent

GENERATION METRICS
--------------------------------------------------------------------------------
  Faithfulness:          0.915 ✓ Excellent
  Answer Relevancy:      0.864 ✓ Good
  Answer Correctness:    0.891 ✓ Good

OVERALL
--------------------------------------------------------------------------------
  Overall Score:         0.896 ✓ Excellent
  Sample Count:          10
================================================================================
```

**JSON Results Structure:**
```json
{
  "retrieval": {
    "context_precision": 0.887,
    "context_recall": 0.923,
    "sample_count": 10,
    "per_sample_results": [...]
  },
  "generation": {
    "faithfulness": 0.915,
    "answer_relevancy": 0.864,
    "answer_correctness": 0.891,
    "sample_count": 10,
    "per_sample_results": [...]
  },
  "overall_score": 0.896,
  "sample_count": 10
}
```

### Baseline Performance Targets

| Metric | Poor | Acceptable | Good | Excellent |
|--------|------|------------|------|-----------|
| Context Precision | <0.75 | 0.75-0.85 | 0.85-0.95 | >0.95 |
| Context Recall | <0.80 | 0.80-0.90 | 0.90-0.98 | >0.98 |
| Faithfulness | <0.80 | 0.80-0.90 | 0.90-0.98 | >0.98 |
| Answer Relevancy | <0.75 | 0.75-0.85 | 0.85-0.95 | >0.95 |
| Overall Score | <0.75 | 0.75-0.85 | 0.85-0.95 | >0.95 |

**Reranking Improvement Targets:**
- Precision@1: >15% improvement (Excellent), 10-15% (Good), 5-10% (Moderate), <5% (Minimal)
- NDCG: >10% improvement (Excellent), 5-10% (Good), <5% (Minimal)

### Evaluation Best Practices

**1. Dataset Quality:**
- Minimum 10 Q&A pairs for initial testing, 50+ for production baselines
- Cover diverse query types (factual, reasoning, multi-hop, aggregation)
- Include both easy and hard questions
- Ensure ground truth answers are accurate and complete
- Update dataset with production queries that failed

**2. Regression Testing:**
- Run evaluation before/after pipeline changes
- Track metrics over time in CI/CD
- Set failure thresholds (e.g., Overall Score <0.80 fails build)
- Compare metrics across different configurations

**3. Reranker Evaluation:**
- Always test with and without reranker to measure impact
- Track latency increase (reranker adds ~100-300ms)
- Compare Precision@1 improvement vs. cost
- Monitor similarity threshold effectiveness

**4. Troubleshooting Low Scores:**
- Context Precision <0.85: Retrieval pulling irrelevant chunks → adjust chunking strategy
- Context Recall <0.90: Missing relevant info → increase top-k, check embeddings quality
- Faithfulness <0.90: Hallucinations → adjust prompt, lower temperature, check context quality
- Answer Relevancy <0.85: Incomplete answers → improve prompt, check LLM model capability

**5. Production Monitoring:**
- Sample 5-10% of production queries for evaluation
- Run nightly batch evaluations
- Alert on metric degradation (>5% drop from baseline)
- Track "I don't know" frequency (should increase with higher thresholds)

### Common Evaluation Issues

**RAGAS timeout errors:**
```bash
# Symptom: Evaluation hangs or times out
# Solution 1: Increase timeout
config = RagasOllamaConfig(request_timeout=600.0)

# Solution 2: Use smaller batches
batch_size = 3  # Reduce from 10

# Solution 3: Use faster model
config = RagasOllamaConfig(llm_model="gemma3:2b")
```

**Ollama connection refused during evaluation:**
```bash
# Verify Ollama is running
ollama list

# Check URL matches config
export OLLAMA_URL="http://localhost:11434"
# OR if in Docker: http://host.docker.internal:11434
```

**ModuleNotFoundError for evaluation modules:**
```bash
# Use .venv/bin/python directly, NOT uv run
.venv/bin/python evaluation/eval_runner.py

# Ensure eval dependencies installed
uv sync --group eval
```

**LLM-as-judge score variance (10-20% between runs):**
- Expected behavior (LLM non-determinism even at temperature=0)
- Mitigation: Run multiple times and average scores
- Use ensemble judging (multiple LLM models vote)
- Focus on relative comparisons (A/B testing) not absolute scores

**Context window exceeded errors:**
```bash
# Symptom: Evaluation fails on long contexts
# Solution: Use model with larger context window
config = RagasOllamaConfig(llm_model="gemma3:4b")  # 8K context
# OR reduce context size in pipeline (lower top-k, smaller chunks)
```

**Missing ground truth answers:**
```bash
# Symptom: Context Recall returns None
# Cause: reference field is None in EvaluationSample
# Solution: Either provide references or skip recall metric
evaluator.metrics = [context_precision]  # Skip context_recall
```

### Extending Evaluation System

**Adding Custom Metrics:**
```python
# Create custom metric following RAGAS pattern
from ragas.metrics import Metric

class CustomMetric(Metric):
    def __init__(self, llm):
        self.llm = llm

    async def single_turn_ascore(self, sample):
        # Implement scoring logic
        return score

# Add to evaluator
retrieval_evaluator.metrics.append(CustomMetric(config.llm))
```

**Generating Synthetic Q&A:**
```python
# Use LLM to generate questions from documents
from core_logic.llm_handler import get_llm

llm = get_llm()
prompt = f"""Generate 5 questions that can be answered using this text:

{document_text}

Questions:"""

response = llm.complete(prompt)
# Parse questions, manually verify quality, add to golden_qa.json
```

**Exporting Evaluation Results to Dashboard:**
```python
# Save results in time-series format
import json
from datetime import datetime

result_entry = {
    "timestamp": datetime.now().isoformat(),
    "metrics": result.model_dump(),
    "config": {"reranker_enabled": True, "strategy": "balanced"},
}

# Append to history file
with open("eval_data/history.jsonl", "a") as f:
    f.write(json.dumps(result_entry) + "\n")

# Visualize trends (external tool: Grafana, custom plotting)
```
