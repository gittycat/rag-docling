"""Benchmark orchestrator for RAG evaluation.

This module coordinates the full benchmark workflow:
1. Load dataset
2. Upload documents to RAG server
3. Run queries against the system
4. Compute metrics (DeepEval + retrieval)
5. Store results for historical tracking
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from evaluation.datasets import BenchmarkDataset, Document, TestCase, get_dataset
from evaluation.results_store import BenchmarkResultsStore, BenchmarkRun, MetricResult


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark run."""

    dataset_name: str
    sample_size: int | None = None
    rag_server_url: str = "http://localhost:8003"  # Benchmark server port
    batch_size: int = 10
    query_timeout: float = 60.0
    compute_retrieval_metrics: bool = True
    compute_deepeval_metrics: bool = True
    run_notes: str = ""


@dataclass
class QueryResult:
    """Result from a single RAG query."""

    question: str
    expected_answer: str
    actual_answer: str
    retrieved_contexts: list[str]
    retrieved_doc_ids: list[str]
    gold_passage_ids: list[str]
    latency_ms: float
    metadata: dict = field(default_factory=dict)


class BenchmarkRunner:
    """Orchestrates benchmark runs against RAG system."""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.dataset: BenchmarkDataset | None = None
        self.results_store = BenchmarkResultsStore()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.config.query_timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    async def run(self) -> BenchmarkRun:
        """Execute full benchmark run.

        Returns:
            BenchmarkRun with all metrics and results
        """
        run_id = f"bench-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        start_time = time.time()

        print(f"Starting benchmark run: {run_id}")
        print(f"Dataset: {self.config.dataset_name}")
        print(f"Server: {self.config.rag_server_url}")
        print()

        # 1. Load dataset
        print("Loading dataset...")
        self.dataset = get_dataset(
            self.config.dataset_name,
            sample_size=self.config.sample_size,
        )
        self.dataset.load()
        info = self.dataset.info
        print(f"  Documents: {info.num_documents}")
        print(f"  Test cases: {info.num_test_cases}")
        print()

        # 2. Check server health
        if not await self._check_health():
            raise RuntimeError(f"RAG server not healthy at {self.config.rag_server_url}")

        # 3. Clear existing documents (fresh start)
        print("Clearing existing documents...")
        await self._clear_documents()

        # 4. Upload documents
        print("Uploading documents...")
        upload_start = time.time()
        await self._upload_documents(self.dataset.get_documents())
        upload_time = time.time() - upload_start
        print(f"  Upload completed in {upload_time:.1f}s")
        print()

        # 5. Run queries
        print("Running queries...")
        query_start = time.time()
        query_results = await self._run_queries(self.dataset.get_test_cases())
        query_time = time.time() - query_start
        print(f"  Queries completed in {query_time:.1f}s")
        print()

        # 6. Compute metrics
        print("Computing metrics...")
        metrics = await self._compute_metrics(query_results)

        total_time = time.time() - start_time

        # 7. Create and store run
        benchmark_run = BenchmarkRun(
            run_id=run_id,
            dataset_name=self.config.dataset_name,
            dataset_info={
                "num_documents": info.num_documents,
                "num_test_cases": info.num_test_cases,
                "has_gold_passages": info.has_gold_passages,
            },
            sample_size=self.config.sample_size or info.num_test_cases,
            metrics=metrics,
            total_time_seconds=total_time,
            upload_time_seconds=upload_time,
            query_time_seconds=query_time,
            avg_latency_ms=sum(r.latency_ms for r in query_results) / len(query_results),
            notes=self.config.run_notes,
            config_snapshot={
                "rag_server_url": self.config.rag_server_url,
                "batch_size": self.config.batch_size,
                "query_timeout": self.config.query_timeout,
            },
        )

        # Store results
        self.results_store.save_run(benchmark_run)
        print(f"\nResults saved: {run_id}")

        return benchmark_run

    async def _check_health(self) -> bool:
        """Check if RAG server is healthy."""
        try:
            response = await self._client.get(f"{self.config.rag_server_url}/health")
            return response.status_code == 200
        except Exception:
            return False

    async def _clear_documents(self) -> None:
        """Clear all documents from RAG server."""
        try:
            # Get list of documents
            response = await self._client.get(f"{self.config.rag_server_url}/documents")
            if response.status_code == 200:
                docs = response.json()
                for doc in docs:
                    doc_id = doc.get("document_id") or doc.get("doc_id")
                    if doc_id:
                        await self._client.delete(
                            f"{self.config.rag_server_url}/documents/{doc_id}"
                        )
        except Exception as e:
            print(f"  Warning: Could not clear documents: {e}")

    async def _upload_documents(self, documents: list[Document]) -> None:
        """Upload documents to RAG server."""
        for i, doc in enumerate(documents):
            try:
                # Create a text file from the document content
                files = {
                    "files": (f"{doc.doc_id}.txt", doc.content.encode(), "text/plain")
                }

                response = await self._client.post(
                    f"{self.config.rag_server_url}/upload",
                    files=files,
                )

                if response.status_code not in (200, 202):
                    print(f"  Warning: Failed to upload {doc.doc_id}: {response.text}")

                # Progress indicator
                if (i + 1) % 50 == 0:
                    print(f"  Uploaded {i + 1}/{len(documents)} documents")

            except Exception as e:
                print(f"  Warning: Error uploading {doc.doc_id}: {e}")

        # Wait for async processing to complete
        print("  Waiting for document processing...")
        await asyncio.sleep(5)  # Give time for async processing

    async def _run_queries(self, test_cases: list[TestCase]) -> list[QueryResult]:
        """Run queries against RAG server."""
        results = []

        for i, test_case in enumerate(test_cases):
            start = time.time()

            try:
                response = await self._client.post(
                    f"{self.config.rag_server_url}/query",
                    json={"query": test_case.question},
                )

                latency_ms = (time.time() - start) * 1000

                if response.status_code == 200:
                    data = response.json()
                    results.append(
                        QueryResult(
                            question=test_case.question,
                            expected_answer=test_case.expected_answer,
                            actual_answer=data.get("answer", ""),
                            retrieved_contexts=data.get("sources", []),
                            retrieved_doc_ids=self._extract_doc_ids(data.get("sources", [])),
                            gold_passage_ids=test_case.gold_passage_ids,
                            latency_ms=latency_ms,
                            metadata=test_case.metadata,
                        )
                    )
                else:
                    results.append(
                        QueryResult(
                            question=test_case.question,
                            expected_answer=test_case.expected_answer,
                            actual_answer="",
                            retrieved_contexts=[],
                            retrieved_doc_ids=[],
                            gold_passage_ids=test_case.gold_passage_ids,
                            latency_ms=latency_ms,
                            metadata={"error": response.text, **test_case.metadata},
                        )
                    )

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                results.append(
                    QueryResult(
                        question=test_case.question,
                        expected_answer=test_case.expected_answer,
                        actual_answer="",
                        retrieved_contexts=[],
                        retrieved_doc_ids=[],
                        gold_passage_ids=test_case.gold_passage_ids,
                        latency_ms=latency_ms,
                        metadata={"error": str(e), **test_case.metadata},
                    )
                )

            # Progress indicator
            if (i + 1) % 20 == 0:
                print(f"  Processed {i + 1}/{len(test_cases)} queries")

        return results

    def _extract_doc_ids(self, sources: list) -> list[str]:
        """Extract document IDs from source list."""
        doc_ids = []
        for source in sources:
            if isinstance(source, dict):
                doc_id = source.get("document_id") or source.get("doc_id")
                if doc_id:
                    doc_ids.append(doc_id)
            elif isinstance(source, str):
                # Try to parse if it's a formatted string
                doc_ids.append(source[:50])  # Truncate for ID
        return doc_ids

    async def _compute_metrics(self, query_results: list[QueryResult]) -> list[MetricResult]:
        """Compute evaluation metrics from query results."""
        metrics = []

        # Retrieval metrics
        if self.config.compute_retrieval_metrics:
            metrics.extend(self._compute_retrieval_metrics(query_results))

        # Answer quality metrics (simplified - full DeepEval would require more setup)
        if self.config.compute_deepeval_metrics:
            metrics.extend(await self._compute_answer_metrics(query_results))

        return metrics

    def _compute_retrieval_metrics(self, results: list[QueryResult]) -> list[MetricResult]:
        """Compute retrieval-specific metrics."""
        metrics = []

        # Recall@K - Is any gold passage in retrieved?
        recall_scores = []
        for r in results:
            if r.gold_passage_ids:
                retrieved_set = set(r.retrieved_doc_ids)
                gold_set = set(r.gold_passage_ids)
                # Check if any gold passage was retrieved
                hit = 1.0 if retrieved_set & gold_set else 0.0
                recall_scores.append(hit)

        if recall_scores:
            metrics.append(
                MetricResult(
                    name="recall@k",
                    score=sum(recall_scores) / len(recall_scores),
                    sample_count=len(recall_scores),
                    per_sample_scores=recall_scores,
                )
            )

        # MRR - Mean Reciprocal Rank
        mrr_scores = []
        for r in results:
            if r.gold_passage_ids:
                gold_set = set(r.gold_passage_ids)
                for rank, doc_id in enumerate(r.retrieved_doc_ids, 1):
                    if doc_id in gold_set:
                        mrr_scores.append(1.0 / rank)
                        break
                else:
                    mrr_scores.append(0.0)

        if mrr_scores:
            metrics.append(
                MetricResult(
                    name="mrr",
                    score=sum(mrr_scores) / len(mrr_scores),
                    sample_count=len(mrr_scores),
                    per_sample_scores=mrr_scores,
                )
            )

        # Latency metrics
        latencies = [r.latency_ms for r in results]
        if latencies:
            sorted_latencies = sorted(latencies)
            p50_idx = len(sorted_latencies) // 2
            p95_idx = int(len(sorted_latencies) * 0.95)

            metrics.append(
                MetricResult(
                    name="latency_p50_ms",
                    score=sorted_latencies[p50_idx],
                    sample_count=len(latencies),
                )
            )
            metrics.append(
                MetricResult(
                    name="latency_p95_ms",
                    score=sorted_latencies[min(p95_idx, len(sorted_latencies) - 1)],
                    sample_count=len(latencies),
                )
            )

        return metrics

    async def _compute_answer_metrics(self, results: list[QueryResult]) -> list[MetricResult]:
        """Compute answer quality metrics.

        This is a simplified version. For full DeepEval metrics,
        integrate with the existing evaluation module.
        """
        metrics = []

        # Answer rate - How many queries got non-empty answers
        non_empty = sum(1 for r in results if r.actual_answer.strip())
        metrics.append(
            MetricResult(
                name="answer_rate",
                score=non_empty / len(results) if results else 0,
                sample_count=len(results),
            )
        )

        # Exact match (case-insensitive)
        exact_matches = sum(
            1 for r in results
            if r.actual_answer.strip().lower() == r.expected_answer.strip().lower()
        )
        metrics.append(
            MetricResult(
                name="exact_match",
                score=exact_matches / len(results) if results else 0,
                sample_count=len(results),
            )
        )

        # Token overlap (simple F1-like measure)
        f1_scores = []
        for r in results:
            if r.expected_answer and r.actual_answer:
                expected_tokens = set(r.expected_answer.lower().split())
                actual_tokens = set(r.actual_answer.lower().split())
                if expected_tokens and actual_tokens:
                    precision = len(expected_tokens & actual_tokens) / len(actual_tokens)
                    recall = len(expected_tokens & actual_tokens) / len(expected_tokens)
                    if precision + recall > 0:
                        f1 = 2 * precision * recall / (precision + recall)
                        f1_scores.append(f1)

        if f1_scores:
            metrics.append(
                MetricResult(
                    name="token_f1",
                    score=sum(f1_scores) / len(f1_scores),
                    sample_count=len(f1_scores),
                    per_sample_scores=f1_scores,
                )
            )

        return metrics


async def run_benchmark(
    dataset_name: str,
    sample_size: int | None = None,
    server_url: str = "http://localhost:8003",
    notes: str = "",
) -> BenchmarkRun:
    """Convenience function to run a benchmark.

    Args:
        dataset_name: Name of dataset (squad, ragbench, hotpotqa)
        sample_size: Number of test cases to use (None = all)
        server_url: RAG server URL
        notes: Optional notes for this run

    Returns:
        BenchmarkRun with results
    """
    config = BenchmarkConfig(
        dataset_name=dataset_name,
        sample_size=sample_size,
        rag_server_url=server_url,
        run_notes=notes,
    )

    async with BenchmarkRunner(config) as runner:
        return await runner.run()


def run_benchmark_sync(
    dataset_name: str,
    sample_size: int | None = None,
    server_url: str = "http://localhost:8003",
    notes: str = "",
) -> BenchmarkRun:
    """Synchronous wrapper for run_benchmark."""
    return asyncio.run(run_benchmark(dataset_name, sample_size, server_url, notes))
