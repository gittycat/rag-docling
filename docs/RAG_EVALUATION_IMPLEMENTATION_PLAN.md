# RAG Evaluation Implementation Plan

> **Framework Choice**: DeepEval v3.7.4 (Dec 2025)
> **LLM Judge**: Anthropic Claude (via API)
> **Integration**: CI/CD + Manual CLI
> **Dataset Target**: 100+ Q&A pairs

---

## Executive Summary

Migrate from RAGAS to **DeepEval** - the 2025 community-recommended framework for production RAG evaluation. DeepEval offers Pytest-style testing, self-explaining metrics (easier debugging), native LlamaIndex integration, and superior CI/CD support.

### Why DeepEval Over RAGAS?

| Aspect | RAGAS | DeepEval |
|--------|-------|----------|
| CI/CD Integration | Manual, data-science style | Pytest-native, assert-based |
| Debugging | Metric scores only | Self-explaining (shows *why* score is low) |
| LlamaIndex Support | Manual wrapping | Native `DeepEvalAnswerRelevancyEvaluator` |
| Metrics | 5 RAG-focused | 50+ (RAG, agents, safety, multimodal) |
| Local LLM Support | Ollama wrappers needed | Direct model configuration |

**Sources**: [DeepEval vs RAGAS](https://deepeval.com/blog/deepeval-vs-ragas), [Top 5 AI Evaluation Frameworks 2025](https://www.gocodeo.com/post/top-5-ai-evaluation-frameworks-in-2025-from-ragas-to-deepeval-and-beyond), [LlamaIndex DeepEval Integration](https://docs.llamaindex.ai/en/stable/community/integrations/deepeval/)

---

## Phase 1: Setup & Configuration

### Step 1.1: Install DeepEval

Add to `services/rag_server/pyproject.toml`:

```toml
[project.optional-dependencies]
eval = [
    "deepeval>=3.7.0",
    "anthropic>=0.40.0",  # For Claude as judge
]
```

Run: `cd services/rag_server && uv sync --group eval`

### Step 1.2: Configure Anthropic as LLM Judge

Create `services/rag_server/evaluation/deepeval_config.py`:

```python
import os
from deepeval.models import DeepEvalBaseLLM
from anthropic import Anthropic

class AnthropicEvaluator(DeepEvalBaseLLM):
    """Claude as LLM-as-judge for DeepEval metrics."""

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def load_model(self):
        return self.model

    def generate(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text

    async def a_generate(self, prompt: str) -> str:
        # Async version for parallel evaluation
        return self.generate(prompt)

    def get_model_name(self) -> str:
        return self.model
```

### Step 1.3: Environment Variables

Add to `.env.example` and document:

```bash
# Evaluation (DeepEval with Anthropic)
ANTHROPIC_API_KEY=sk-ant-...
EVAL_MODEL=claude-sonnet-4-20250514  # Cost-effective for evals
```

---

## Phase 2: Core Metrics Implementation

### Step 2.1: RAG Evaluation Metrics

Create `services/rag_server/evaluation/metrics.py`:

```python
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    HallucinationMetric,
)
from evaluation.deepeval_config import AnthropicEvaluator

def get_rag_metrics(model: AnthropicEvaluator = None):
    """Return configured RAG evaluation metrics."""
    model = model or AnthropicEvaluator()

    return [
        # Retrieval Quality
        ContextualPrecisionMetric(
            threshold=0.7,
            model=model,
            include_reason=True,  # Self-explaining!
        ),
        ContextualRecallMetric(
            threshold=0.7,
            model=model,
            include_reason=True,
        ),

        # Generation Quality
        FaithfulnessMetric(
            threshold=0.7,
            model=model,
            include_reason=True,
        ),
        AnswerRelevancyMetric(
            threshold=0.7,
            model=model,
            include_reason=True,
        ),

        # Hallucination Detection
        HallucinationMetric(
            threshold=0.5,  # Lower = stricter (0.5 = max 50% hallucinated)
            model=model,
            include_reason=True,
        ),
    ]
```

### Step 2.2: Test Case Factory

Create `services/rag_server/evaluation/test_cases.py`:

```python
from deepeval.test_case import LLMTestCase
from typing import List

def create_test_case(
    question: str,
    actual_output: str,
    expected_output: str,
    retrieval_context: List[str],
) -> LLMTestCase:
    """Create a DeepEval test case from RAG query results."""
    return LLMTestCase(
        input=question,
        actual_output=actual_output,
        expected_output=expected_output,
        retrieval_context=retrieval_context,
    )
```

---

## Phase 3: Golden Dataset Expansion (100+ Q&A)

### Step 3.1: Dataset Structure

Expand `services/rag_server/eval_data/golden_qa.json` to include:

```json
{
  "version": "2.0",
  "created": "2025-12-07",
  "documents": [
    {"id": "greatwork", "path": "greatwork.html", "topic": "productivity"},
    {"id": "talk", "path": "talk.html", "topic": "writing"},
    {"id": "conformism", "path": "conformism.html", "topic": "society"}
  ],
  "test_cases": [
    {
      "id": "tc001",
      "question": "What are the three qualities needed to do great work?",
      "expected_answer": "Natural aptitude, deep interest, and scope for great work.",
      "document_id": "greatwork",
      "query_type": "factual",
      "difficulty": "easy",
      "tags": ["core-concept", "definition"]
    }
  ]
}
```

### Step 3.2: Synthetic Q&A Generation Script

Create `services/rag_server/evaluation/generate_qa.py`:

```python
"""Generate synthetic Q&A pairs from documents using Claude."""

import json
from pathlib import Path
from anthropic import Anthropic

GENERATION_PROMPT = """
Given this document, generate 10 diverse Q&A pairs for RAG evaluation.

Requirements:
- Mix of factual (direct lookup) and reasoning (inference) questions
- Include easy, medium, and hard difficulty levels
- Questions should require specific context from the document
- Answers should be concise but complete

Document:
{document_text}

Output JSON array:
[{{"question": "...", "answer": "...", "query_type": "factual|reasoning", "difficulty": "easy|medium|hard"}}]
"""

def generate_qa_for_document(doc_path: Path, client: Anthropic) -> list:
    text = doc_path.read_text()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": GENERATION_PROMPT.format(document_text=text[:15000])}]
    )
    return json.loads(response.content[0].text)
```

### Step 3.3: Dataset Targets

| Category | Current | Target | Source |
|----------|---------|--------|--------|
| Factual (easy) | 6 | 40 | Synthetic + manual |
| Factual (medium) | 0 | 25 | Synthetic + manual |
| Reasoning (easy) | 2 | 20 | Synthetic + manual |
| Reasoning (hard) | 2 | 15 | Manual curation |
| Edge cases | 0 | 10 | Manual curation |
| **Total** | **10** | **110** | |

---

## Phase 4: Pipeline Integration

### Step 4.1: Live RAG Evaluation

Create `services/rag_server/evaluation/live_eval.py`:

```python
"""Evaluate the actual RAG pipeline, not mock data."""

import httpx
from deepeval.test_case import LLMTestCase
from deepeval import evaluate
from evaluation.metrics import get_rag_metrics
from evaluation.dataset_loader import load_golden_dataset

RAG_SERVER_URL = "http://localhost:8001"

async def query_rag(question: str, session_id: str = "eval") -> dict:
    """Query the actual RAG server."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{RAG_SERVER_URL}/query",
            json={"query": question, "session_id": session_id}
        )
        return response.json()

async def create_live_test_cases() -> list[LLMTestCase]:
    """Generate test cases from live RAG queries."""
    dataset = load_golden_dataset()
    test_cases = []

    for item in dataset:
        result = await query_rag(item["question"])
        test_cases.append(LLMTestCase(
            input=item["question"],
            actual_output=result["response"],
            expected_output=item["expected_answer"],
            retrieval_context=result.get("source_nodes", []),
        ))

    return test_cases

def run_live_evaluation():
    """Run evaluation against live RAG server."""
    import asyncio
    test_cases = asyncio.run(create_live_test_cases())
    metrics = get_rag_metrics()

    results = evaluate(test_cases, metrics)
    return results
```

### Step 4.2: CLI Runner

Create `services/rag_server/evaluation/cli.py`:

```python
"""CLI for running evaluations."""

import argparse
from evaluation.live_eval import run_live_evaluation
from evaluation.report_generator import save_report

def main():
    parser = argparse.ArgumentParser(description="RAG Evaluation CLI")
    parser.add_argument("--output", "-o", default="eval_results", help="Output directory")
    parser.add_argument("--samples", "-n", type=int, help="Limit number of samples")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    args = parser.parse_args()

    print("🔍 Running RAG evaluation...")
    results = run_live_evaluation()

    report_path = save_report(results, args.output)
    print(f"📊 Report saved to: {report_path}")

if __name__ == "__main__":
    main()
```

Usage: `.venv/bin/python -m evaluation.cli --verbose`

---

## Phase 5: CI/CD Integration

### Step 5.1: Pytest Integration

Create `services/rag_server/tests/test_rag_eval.py`:

```python
"""RAG evaluation tests for CI/CD."""

import pytest
from deepeval import assert_test
from deepeval.test_case import LLMTestCase
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric

from evaluation.deepeval_config import AnthropicEvaluator
from evaluation.dataset_loader import load_golden_dataset

# Skip in regular test runs, only run in eval pipeline
pytestmark = pytest.mark.skipif(
    not pytest.config.getoption("--run-eval", default=False),
    reason="Evaluation tests require --run-eval flag"
)

@pytest.fixture(scope="session")
def evaluator():
    return AnthropicEvaluator()

@pytest.fixture(scope="session")
def metrics(evaluator):
    return [
        FaithfulnessMetric(threshold=0.7, model=evaluator),
        AnswerRelevancyMetric(threshold=0.7, model=evaluator),
    ]

@pytest.mark.eval
def test_rag_faithfulness(metrics):
    """Test that RAG responses are faithful to retrieved context."""
    # Load a sample test case from golden dataset
    dataset = load_golden_dataset()[:5]  # Subset for CI speed

    for item in dataset:
        # Query actual RAG (requires server running)
        test_case = LLMTestCase(
            input=item["question"],
            actual_output="...",  # From RAG query
            retrieval_context=["..."],  # From RAG
        )
        assert_test(test_case, [metrics[0]])

@pytest.mark.eval
def test_rag_relevancy(metrics):
    """Test that RAG responses are relevant to questions."""
    # Similar structure
    pass
```

### Step 5.2: GitHub Actions Workflow

Create `.github/workflows/rag-eval.yml`:

```yaml
name: RAG Evaluation

on:
  push:
    branches: [main]
    paths:
      - 'services/rag_server/core_logic/**'
      - 'services/rag_server/evaluation/**'
  pull_request:
    branches: [main]
  workflow_dispatch:  # Manual trigger

jobs:
  evaluate:
    runs-on: ubuntu-latest

    services:
      chromadb:
        image: chromadb/chroma:latest
        ports:
          - 8000:8000
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: |
          cd services/rag_server
          uv sync --group eval

      - name: Start RAG server
        run: |
          cd services/rag_server
          .venv/bin/python -m uvicorn main:app --port 8001 &
          sleep 10  # Wait for startup
        env:
          CHROMADB_URL: http://localhost:8000
          REDIS_URL: redis://localhost:6379
          OLLAMA_URL: http://localhost:11434
          EMBEDDING_MODEL: nomic-embed-text
          LLM_MODEL: gemma3:4b

      - name: Run evaluation
        run: |
          cd services/rag_server
          .venv/bin/python -m evaluation.cli --output eval_results
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: eval-results
          path: services/rag_server/eval_results/

      - name: Check thresholds
        run: |
          # Fail if metrics below threshold
          python -c "
          import json
          results = json.load(open('services/rag_server/eval_results/latest.json'))
          assert results['overall_score'] >= 0.7, f'Score {results[\"overall_score\"]} below threshold 0.7'
          print('✅ Evaluation passed!')
          "
```

### Step 5.3: Add Pytest Config

Add to `services/rag_server/pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "eval: RAG evaluation tests (require --run-eval and ANTHROPIC_API_KEY)",
]
addopts = "--strict-markers"
```

---

## Phase 6: Reporting & Baselines

### Step 6.1: Report Generator

Create `services/rag_server/evaluation/report_generator.py`:

```python
"""Generate evaluation reports with trend tracking."""

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass

@dataclass
class EvaluationReport:
    timestamp: str
    metrics: dict
    overall_score: float
    test_cases: list

    def to_markdown(self) -> str:
        return f"""# RAG Evaluation Report

**Date**: {self.timestamp}
**Overall Score**: {self.overall_score:.2%}

## Metrics Summary

| Metric | Score | Threshold | Status |
|--------|-------|-----------|--------|
{self._format_metrics_table()}

## Failing Test Cases

{self._format_failures()}
"""

def save_report(results, output_dir: str):
    """Save report with baseline comparison."""
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)

    # Save timestamped report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_path / f"eval_{timestamp}.json"

    with open(report_path, "w") as f:
        json.dump(results.to_dict(), f, indent=2)

    # Update latest symlink
    latest_path = output_path / "latest.json"
    if latest_path.exists():
        latest_path.unlink()
    latest_path.symlink_to(report_path.name)

    return report_path
```

### Step 6.2: Baseline Tracking

Store baselines in `services/rag_server/eval_data/baselines/`:

```
baselines/
├── baseline_v1.json      # Initial baseline after 100+ Q&A
├── baseline_v2.json      # After hybrid search improvements
└── current.json          # Latest accepted baseline
```

---

## File Changes Summary

### New Files

| File | Purpose |
|------|---------|
| `evaluation/deepeval_config.py` | Anthropic LLM judge configuration |
| `evaluation/metrics.py` | DeepEval metric definitions |
| `evaluation/test_cases.py` | Test case factory |
| `evaluation/live_eval.py` | Live RAG pipeline evaluation |
| `evaluation/cli.py` | CLI runner |
| `evaluation/generate_qa.py` | Synthetic Q&A generation |
| `tests/test_rag_eval.py` | Pytest integration tests |
| `.github/workflows/rag-eval.yml` | CI/CD workflow |

### Modified Files

| File | Changes |
|------|---------|
| `pyproject.toml` | Add `deepeval`, `anthropic` to eval deps |
| `eval_data/golden_qa.json` | Expand to 100+ Q&A pairs |
| `CLAUDE.md` | Update evaluation docs |

### Files to Remove (Optional)

The existing RAGAS-based files can be kept for reference or removed:

| File | Recommendation |
|------|----------------|
| `evaluation/ragas_config.py` | Remove (replaced by deepeval_config.py) |
| `evaluation/retrieval_eval.py` | Remove (DeepEval handles this) |
| `evaluation/generation_eval.py` | Remove (DeepEval handles this) |
| `evaluation/reranking_eval.py` | Keep (custom reranking comparison) |

---

## Implementation Order

1. **Install DeepEval + Configure Anthropic** (Phase 1)
2. **Create core metrics module** (Phase 2)
3. **Expand golden dataset to 50 Q&A** (Phase 3 - initial)
4. **Implement live pipeline evaluation** (Phase 4)
5. **Add CLI runner** (Phase 4)
6. **Expand dataset to 100+ Q&A** (Phase 3 - complete)
7. **Add CI/CD workflow** (Phase 5)
8. **Implement baseline tracking** (Phase 6)
9. **Update documentation** (Final)

---

## Success Criteria

- [ ] DeepEval installed and configured with Anthropic
- [ ] 100+ golden Q&A pairs across all documents
- [ ] CLI runs evaluation against live RAG server
- [ ] CI/CD pipeline triggers on relevant changes
- [ ] Baseline established with current accuracy
- [ ] Metrics include faithfulness, relevancy, precision, recall
- [ ] Reports show *why* scores are low (self-explaining)

---

## Cost Estimation

| Usage | Claude Sonnet Cost |
|-------|-------------------|
| Per test case (5 metrics) | ~$0.01-0.02 |
| Full eval (100 cases) | ~$1-2 per run |
| CI/CD (10 cases/PR) | ~$0.10-0.20 per PR |
| Monthly (20 PRs + 4 full) | ~$10-15/month |

---

## References

- [DeepEval Documentation](https://docs.confident-ai.com/)
- [DeepEval GitHub](https://github.com/confident-ai/deepeval)
- [LlamaIndex DeepEval Integration](https://docs.llamaindex.ai/en/stable/community/integrations/deepeval/)
- [DeepEval vs RAGAS Comparison](https://deepeval.com/blog/deepeval-vs-ragas)
- [RAG Evaluation Best Practices 2025](https://www.cohorte.co/blog/evaluating-rag-systems-in-2025-ragas-deep-dive-giskard-showdown-and-the-future-of-context)
