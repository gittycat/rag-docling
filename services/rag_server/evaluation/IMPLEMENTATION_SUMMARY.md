# RAG Evaluation Implementation Summary

## Overview

Comprehensive RAG evaluation system using RAGAS framework configured with local Ollama models. Provides metrics for retrieval quality, reranking effectiveness, and generation quality.

## What Was Implemented

### 1. Core Infrastructure

**Dependencies Added** (services/rag_server/pyproject.toml):
- `ragas>=0.3.5` - Evaluation framework
- `langchain-ollama>=0.3.10` - LangChain integration for Ollama

**Configuration** (evaluation/ragas_config.py):
- `RagasOllamaConfig` - Configures RAGAS to use Ollama instead of OpenAI
- Wraps LangChain's `ChatOllama` and `OllamaEmbeddings` for RAGAS
- Default models: `gemma3:4b` (LLM judge), `qwen3-embedding:8b` (embeddings)
- Configurable timeout (300s default) to handle Ollama latency

### 2. Evaluation Datasets

**Paul Graham Essays** (eval_data/documents/):
- `greatwork.html` - Essay on how to do great work
- `talk.html` - Essay on writing like you talk
- `conformism.html` - Essay on the four quadrants of conformism

**Golden Q&A Dataset** (eval_data/golden_qa.json):
- 10 question-answer pairs across the three essays
- Mix of factual and reasoning questions
- Includes context hints and query type metadata

### 3. Data Models (evaluation/data_models.py)

- `EvaluationSample` - Input format for evaluation (question, contexts, response, reference)
- `RetrievalEvaluationResult` - Context Precision, Context Recall scores
- `GenerationEvaluationResult` - Faithfulness, Answer Relevancy, Answer Correctness
- `EndToEndEvaluationResult` - Combined metrics with overall score

### 4. Retrieval Evaluation (evaluation/retrieval_eval.py)

**RAGAS Metrics**:
- **Context Precision** (target >0.85) - Signal-to-noise ratio of retrieved contexts
- **Context Recall** (target >0.90) - Completeness of information retrieval

**Traditional IR Metrics**:
- **Hit Rate@K** - Percentage of queries with ≥1 relevant result in top-K
- **MRR** - Mean Reciprocal Rank of first relevant result

### 5. Reranking Evaluation (evaluation/reranking_eval.py)

**Comparison Metrics**:
- **Precision@1 and Precision@3** - Before vs after reranking
- **NDCG@10** - Normalized Discounted Cumulative Gain
- **Improvement %** - Quantifies reranking effectiveness

**Target Improvements**:
- Precision@1: >15% improvement
- NDCG: >10% improvement

### 6. Generation Evaluation (evaluation/generation_eval.py)

**RAGAS Metrics**:
- **Faithfulness** (target >0.90) - Factual accuracy, no hallucinations
- **Answer Relevancy** (target >0.85) - How well answer addresses query
- **Answer Correctness** (optional, requires reference) - Semantic similarity to ground truth

### 7. End-to-End Pipeline (evaluation/end_to_end_eval.py)

- `EndToEndEvaluator` - Combines all metrics
- Calculates overall score as average of all available metrics
- Async evaluation support for performance

### 8. Report Generation (evaluation/report_generator.py)

**Features**:
- Text reports with status indicators (✓ Good, ⚠ Warning, ✗ Poor)
- JSON export for programmatic analysis
- Reranking comparison reports
- Threshold-based quality assessment

### 9. Testing (tests/evaluation/)

**27 pytest tests** covering:
- Data models validation
- Dataset loading
- Retrieval metrics (Hit Rate, MRR)
- Reranking comparisons (Precision, NDCG)
- Edge cases (empty samples, missing references)

All tests passing ✓

### 10. Documentation

- `evaluation/README.md` - Comprehensive usage guide
- Ollama integration warnings and workarounds
- Baseline targets and troubleshooting
- Integration examples with RAG pipeline

## Quick Start

### Install Dependencies

```bash
cd services/rag_server
uv sync --group eval
```

### Verify Models

```bash
ollama list | grep -E "gemma3:4b|qwen3-embedding:8b"
```

If missing:
```bash
ollama pull gemma3:4b
ollama pull qwen3-embedding:8b
```

### Run Sample Evaluation

```bash
.venv/bin/python evaluation/eval_runner.py
```

This will:
1. Load golden Q&A dataset
2. Create mock evaluation samples
3. Run RAGAS metrics via Ollama
4. Generate text and JSON reports
5. Save to `eval_data/`

## Integration with RAG Pipeline

### Step 1: Index Test Documents

```python
# Upload evaluation documents to ChromaDB
from pathlib import Path

docs_path = Path("eval_data/documents")
for doc_file in docs_path.glob("*.html"):
    # Upload via /upload endpoint or direct indexing
    pass
```

### Step 2: Run Queries and Collect Results

```python
from evaluation.dataset_loader import load_default_dataset
from evaluation.data_models import EvaluationSample
from core_logic.rag_pipeline import query_with_rag

golden_qa = load_default_dataset()
samples = []

for qa in golden_qa:
    # Run RAG pipeline
    response = query_with_rag(
        query=qa.question,
        strategy="balanced",
        enable_reranker=True
    )

    sample = EvaluationSample(
        user_input=qa.question,
        retrieved_contexts=[node.text for node in response.source_nodes],
        response=response.response,
        reference=qa.answer
    )
    samples.append(sample)
```

### Step 3: Run Evaluation

```python
from evaluation.end_to_end_eval import EndToEndEvaluator
from evaluation.report_generator import EvaluationReportGenerator

evaluator = EndToEndEvaluator()
result = evaluator.evaluate(samples, include_correctness=True)

# Generate report
report_gen = EvaluationReportGenerator("eval_data")
print(report_gen.generate_text_report(result))

# Save results
report_gen.save_report(result)
report_gen.save_json_results(result)
```

### Step 4: Compare Reranking

```python
from evaluation.reranking_eval import RerankingEvaluator

# Run queries with reranker disabled
samples_no_rerank = [...]  # Same process as above with enable_reranker=False

# Run queries with reranker enabled
samples_with_rerank = [...]  # Same process with enable_reranker=True

# Compare
rerank_eval = RerankingEvaluator()
comparison = rerank_eval.compare_reranking(samples_no_rerank, samples_with_rerank)

print(f"Precision@1 improvement: {comparison.precision_improvement:.1f}%")
print(f"NDCG improvement: {comparison.ndcg_improvement:.1f}%")
```

## Performance Considerations

### Ollama Timeouts

RAGAS + Ollama can timeout on large datasets. Mitigations:

1. **Increase timeout**:
```python
from evaluation.ragas_config import RagasOllamaConfig
config = RagasOllamaConfig(request_timeout=600.0)
```

2. **Batch evaluation**:
```python
batch_size = 5
for i in range(0, len(samples), batch_size):
    batch = samples[i:i+batch_size]
    result = evaluator.evaluate(batch)
```

3. **Use faster models**:
```python
config = RagasOllamaConfig(
    llm_model="gemma3:2b",  # Smaller, faster
)
```

### Evaluation Time

Expected timing (3 samples, Ollama local):
- Retrieval metrics: 30-60s
- Generation metrics: 60-120s
- Total: 2-3 minutes per 3 samples

Cloud API (OpenAI) would be 5-10x faster but requires API key.

## Known Limitations

1. **RAGAS + Ollama Integration** - Some metrics may timeout or fail with certain models
2. **Context Window Limits** - Large contexts may be truncated
3. **LLM-as-Judge Variance** - Scores can vary 10-20% between runs
4. **Ground Truth Required** - Context Recall and Answer Correctness need reference answers

## Next Steps

### Expand Dataset

1. Add more documents (technical docs, APIs, domain-specific content)
2. Generate synthetic Q&A pairs using LLM
3. Capture production queries as test cases

### CI/CD Integration

```bash
# Add to CI pipeline
.venv/bin/pytest tests/evaluation/ -v
.venv/bin/python evaluation/eval_runner.py

# Fail if metrics below threshold
python -c "
import json
with open('eval_data/evaluation_results_*.json') as f:
    results = json.load(f)
    assert results['overall_score'] > 0.80
"
```

### Production Monitoring

1. Sample 5-10% of production queries
2. Run evaluation batch jobs nightly
3. Alert on metric degradation
4. Track trends over time

### Advanced Metrics

1. Multi-hop reasoning questions
2. Domain-specific accuracy metrics
3. Response time evaluation
4. Cost per query tracking

## Files Created

```
services/rag_server/
├── evaluation/
│   ├── __init__.py
│   ├── ragas_config.py           # Ollama configuration
│   ├── data_models.py             # Pydantic models
│   ├── retrieval_eval.py          # Retrieval metrics
│   ├── reranking_eval.py          # Reranking comparison
│   ├── generation_eval.py         # Generation metrics
│   ├── end_to_end_eval.py         # Combined pipeline
│   ├── dataset_loader.py          # Load golden Q&A
│   ├── report_generator.py        # Report formatting
│   ├── eval_runner.py             # Sample runner script
│   ├── README.md                  # Usage documentation
│   └── IMPLEMENTATION_SUMMARY.md  # This file
├── eval_data/
│   ├── documents/
│   │   ├── greatwork.html
│   │   ├── talk.html
│   │   └── conformism.html
│   └── golden_qa.json             # 10 Q&A pairs
└── tests/
    └── evaluation/
        ├── __init__.py
        ├── test_data_models.py
        ├── test_dataset_loader.py
        ├── test_reranking_eval.py
        └── test_retrieval_eval.py
```

## Dependencies Updated

```toml
[dependency-groups]
eval = [
    "ragas>=0.3.5",
    "langchain-ollama>=0.3.10",
]
```

## References

- RAGAS Documentation: https://docs.ragas.io/
- RAGAS GitHub: https://github.com/explodinggradients/ragas
- LlamaIndex + RAGAS: https://docs.ragas.io/en/stable/howtos/integrations/_llamaindex/
- Evaluation best practices: See CLAUDE.md research notes
