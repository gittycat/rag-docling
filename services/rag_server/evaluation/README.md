# DeepEval RAG Evaluation - Quick Start

This guide shows you how to use DeepEval for RAG evaluation.

## Prerequisites

1. **RAG Server Running**:
   ```bash
   docker compose up -d
   ```

2. **Anthropic API Key**:
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   ```

3. **Install Dependencies**:
   ```bash
   cd services/rag_server
   uv sync --group eval
   ```

## Quick Start (30 seconds)

```bash
# 1. Check dataset
.venv/bin/python -m evaluation.cli stats

# 2. Run quick evaluation (5 test cases)
.venv/bin/python -m evaluation.cli eval --samples 5

# 3. View results (DeepEval displays detailed output)
```

## Common Tasks

### View Dataset Statistics

```bash
.venv/bin/python -m evaluation.cli stats
```

Output:
```
📊 Golden Dataset Statistics
============================================================
Total Q&A pairs: 10

By Query Type:
  factual        :   8 (80.0%)
  reasoning      :   2 (20.0%)

By Document:
  conformism.html          :   5
  greatwork.html           :   1
  talk.html                :   4
```

### Run Evaluation

```bash
# Quick test (5 samples)
.venv/bin/python -m evaluation.cli eval --samples 5

# Full evaluation
.venv/bin/python -m evaluation.cli eval

# With custom server URL
.venv/bin/python -m evaluation.cli eval --server-url http://localhost:8001
```

### Generate Q&A Pairs

```bash
# From a single document
.venv/bin/python -m evaluation.cli generate document.txt -n 10 -o generated.json

# From a directory
.venv/bin/python -m evaluation.cli generate documents/ -n 5 --pattern "*.html"

# Merge with existing dataset
.venv/bin/python -m evaluation.cli generate documents/ --merge
```

### Run Pytest Tests

```bash
# Run evaluation tests
pytest tests/test_rag_eval.py --run-eval

# Quick test (5 samples)
pytest tests/test_rag_eval.py --run-eval --eval-samples=5

# Run specific metric
pytest tests/test_rag_eval.py::test_rag_faithfulness --run-eval
```

## Python API

### Basic Evaluation

```python
from evaluation.live_eval import run_live_evaluation_sync
from evaluation.dataset_loader import load_golden_dataset

# Load dataset
dataset = load_golden_dataset(limit=5)

# Run evaluation
results = run_live_evaluation_sync(
    dataset=dataset,
    include_reason=True,  # Get explanations for scores
    verbose=True
)
```

### Custom Metrics

```python
from evaluation.metrics import get_rag_metrics, get_retrieval_metrics
from evaluation.deepeval_config import get_default_evaluator
from deepeval import evaluate

# Get all RAG metrics
metrics = get_rag_metrics()

# Or get only retrieval metrics (faster, cheaper)
retrieval_metrics = get_retrieval_metrics()

# Custom thresholds
custom_metrics = get_rag_metrics(
    thresholds={
        "faithfulness": 0.8,
        "answer_relevancy": 0.85,
    }
)

# Run evaluation
results = evaluate(test_cases, metrics)
```

### Create Test Cases

```python
from evaluation.test_cases import create_test_case

test_case = create_test_case(
    question="What is Python?",
    actual_output="Python is a high-level programming language.",
    expected_output="Python is a programming language.",
    retrieval_context=["Python is a programming language created by Guido van Rossum."],
    tags=["factual", "easy"]
)
```

## Metrics Explained

### Retrieval Quality

- **Contextual Precision**: Are retrieved chunks ranked correctly?
- **Contextual Recall**: Did we retrieve all necessary information?

### Generation Quality

- **Faithfulness**: Is the answer grounded in the retrieved context?
- **Answer Relevancy**: Does the answer directly address the question?

### Safety

- **Hallucination**: Does the answer contain information not in the context?

## Environment Variables

```bash
# Required for evaluation
export ANTHROPIC_API_KEY=sk-ant-...

# Optional: Override default model (defaults to claude-sonnet-4-20250514)
export EVAL_MODEL=claude-sonnet-4-20250514

# Optional: RAG server URL (defaults to http://localhost:8001)
export RAG_SERVER_URL=http://localhost:8001
```

## Troubleshooting

### "RAG server not responding"

```bash
# Check if server is running
docker compose ps

# Start server
docker compose up -d

# Check health
curl http://localhost:8001/health
```

### "ANTHROPIC_API_KEY not set"

```bash
# Set API key
export ANTHROPIC_API_KEY=sk-ant-...

# Or add to .env file (if using direnv/dotenv)
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
```

### "No test cases created"

- Ensure RAG server has documents indexed
- Check that golden dataset exists: `eval_data/golden_qa.json`
- Verify dataset loads: `.venv/bin/python -m evaluation.cli stats`

### Import errors

```bash
# Reinstall dependencies
cd services/rag_server
uv sync --group eval
```

## CLI Help

```bash
# Main help
.venv/bin/python -m evaluation.cli --help

# Command-specific help
.venv/bin/python -m evaluation.cli eval --help
.venv/bin/python -m evaluation.cli generate --help
```

## Cost Management

- **Quick tests**: Use `--samples 5` to limit API calls
- **Skip explanations**: Use `--no-reason` for faster (cheaper) evaluation
- **Batch generation**: Generate Q&A in batches to reduce API costs

## Next Steps

1. Review [Implementation Summary](../../../docs/DEEPEVAL_IMPLEMENTATION_SUMMARY.md)
2. Set up CI/CD for automated evaluation
3. Expand golden dataset to 100+ Q&A pairs

## Support

- DeepEval Docs: https://docs.confident-ai.com/
- Anthropic API: https://docs.anthropic.com/
- Issue tracker: See project README
