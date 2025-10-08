# RAG Evaluation with RAGAS

This module provides comprehensive evaluation capabilities for the RAG pipeline using the RAGAS framework configured to use local Ollama models.

## Setup

Install evaluation dependencies:

```bash
cd services/rag_server
uv sync --group eval
```

## Quick Start

Run a simple evaluation with mock data:

```bash
.venv/bin/python evaluation/eval_runner.py
```

## Components

### 1. Configuration (`ragas_config.py`)

Configures RAGAS to use Ollama models instead of OpenAI:

```python
from evaluation.ragas_config import create_default_ragas_config

config = create_default_ragas_config()
# Uses gemma3:4b for LLM judge and qwen3-embedding:8b for embeddings
```

### 2. Retrieval Evaluation (`retrieval_eval.py`)

Evaluates retrieval quality with:
- **Context Precision**: Signal-to-noise ratio of retrieved context
- **Context Recall**: Completeness of retrieved information
- **Hit Rate@K**: Percentage of queries with at least one relevant result in top-K
- **MRR**: Mean Reciprocal Rank of first relevant result

```python
from evaluation.retrieval_eval import RetrievalEvaluator
from evaluation.data_models import EvaluationSample

samples = [
    EvaluationSample(
        user_input="What are the three qualities for great work?",
        retrieved_contexts=["context 1", "context 2"],
        reference="natural aptitude, deep interest, and scope"
    )
]

evaluator = RetrievalEvaluator(config)
result = evaluator.evaluate(samples)
print(f"Context Precision: {result.context_precision}")
```

### 3. Reranking Evaluation (`reranking_eval.py`)

Compares retrieval quality before and after reranking:

```python
from evaluation.reranking_eval import RerankingEvaluator

evaluator = RerankingEvaluator()
comparison = evaluator.compare_reranking(
    samples_before_rerank,
    samples_after_rerank
)
print(f"Precision@1 improvement: {comparison.precision_improvement:.1f}%")
print(f"NDCG improvement: {comparison.ndcg_improvement:.1f}%")
```

### 4. Generation Evaluation (`generation_eval.py`)

Evaluates answer quality with:
- **Faithfulness**: Factual accuracy (no hallucinations)
- **Answer Relevancy**: How well the answer addresses the question
- **Answer Correctness**: Semantic similarity to ground truth (requires reference answer)

```python
from evaluation.generation_eval import GenerationEvaluator

samples = [
    EvaluationSample(
        user_input="What is the trick for getting more people to read?",
        retrieved_contexts=["Write in spoken language..."],
        response="The trick is to write in spoken language.",
        reference="Write in spoken language."
    )
]

evaluator = GenerationEvaluator(config)
result = evaluator.evaluate(samples, include_correctness=True)
print(f"Faithfulness: {result.faithfulness}")
print(f"Answer Relevancy: {result.answer_relevancy}")
```

### 5. End-to-End Evaluation (`end_to_end_eval.py`)

Combines all metrics for comprehensive evaluation:

```python
from evaluation.end_to_end_eval import EndToEndEvaluator

evaluator = EndToEndEvaluator()
result = evaluator.evaluate(samples)

print(f"Overall Score: {result.overall_score}")
print(f"Context Precision: {result.retrieval.context_precision}")
print(f"Faithfulness: {result.generation.faithfulness}")
```

## Dataset Format

The golden Q&A dataset (`eval_data/golden_qa.json`) format:

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

## Evaluation Data Model

```python
from evaluation.data_models import EvaluationSample

sample = EvaluationSample(
    user_input="The question",          # Required
    retrieved_contexts=["ctx1", "ctx2"], # Required
    response="The answer",               # Optional, needed for generation metrics
    reference="Ground truth answer"      # Optional, needed for recall and correctness
)
```

## Integration with RAG Pipeline

To evaluate your actual RAG pipeline:

1. **Run queries through your RAG system** to get retrieved contexts and generated answers
2. **Create EvaluationSample objects** from the results
3. **Run evaluation** with the appropriate evaluator

Example integration:

```python
from core_logic.rag_pipeline import query_with_rag
from evaluation.data_models import EvaluationSample
from evaluation.end_to_end_eval import EndToEndEvaluator
from evaluation.dataset_loader import load_default_dataset

# Load test questions
golden_qa = load_default_dataset()

# Run RAG pipeline for each question
samples = []
for qa in golden_qa:
    response = query_with_rag(qa.question)

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
print(f"Overall Score: {result.overall_score}")
```

## Known Limitations

### Ollama Integration Challenges

RAGAS + Ollama integration has some known issues (as of 2025):

1. **Timeouts**: Evaluation may timeout on large datasets or slow models
2. **Context Windows**: Some models have limited context windows affecting evaluation
3. **Performance**: Local LLM evaluation is slower than cloud APIs

**Workarounds**:
- Use smaller, faster models (gemma3:4b recommended over llama3:70b)
- Increase timeout in `RagasOllamaConfig` (default: 300s)
- Evaluate in smaller batches (5-10 samples at a time)
- Consider hybrid approach: Use Ollama for embeddings, cloud API for LLM judge

### Model Requirements

Ensure Ollama models are downloaded:

```bash
ollama pull gemma3:4b              # LLM judge
ollama pull qwen3-embedding:8b     # Embeddings
```

## Baseline Targets

Expected performance targets for a well-functioning RAG system:

| Metric              | Target | Good  | Excellent |
|---------------------|--------|-------|-----------|
| Context Precision   | >0.85  | >0.90 | >0.95     |
| Context Recall      | >0.90  | >0.95 | >0.98     |
| Faithfulness        | >0.90  | >0.95 | >0.98     |
| Answer Relevancy    | >0.85  | >0.90 | >0.95     |
| Hit Rate@10         | >0.95  | >0.98 | >0.99     |

**Reranking improvement targets**:
- Precision@1 increase: >15%
- NDCG increase: >10%

## Troubleshooting

**ImportError for langchain_ollama**:
```bash
uv sync --group eval
```

**Timeout errors**:
```python
config = RagasOllamaConfig(request_timeout=600.0)  # Increase timeout
```

**"No module named 'evaluation'"**:
```bash
# Use .venv/bin/python directly instead of uv run
.venv/bin/python evaluation/eval_runner.py
```

**Ollama connection refused**:
```bash
# Check Ollama is running
ollama list

# Verify URL in config
export OLLAMA_URL="http://localhost:11434"
```

## Running Tests

```bash
.venv/bin/pytest tests/evaluation/ -v
```

## References

- [RAGAS Documentation](https://docs.ragas.io/)
- [RAGAS GitHub](https://github.com/explodinggradients/ragas)
- [LlamaIndex + RAGAS Integration](https://docs.ragas.io/en/stable/howtos/integrations/_llamaindex/)
