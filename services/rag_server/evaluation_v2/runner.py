"""Evaluation v2 runner: dataset ingestion, query execution, and metrics."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from deepeval import evaluate
from deepeval.test_case import LLMTestCase
from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, HallucinationMetric

from evaluation_v2.data_models import EvalTestCase
from evaluation_v2.datasets import get_dataset
from evaluation_v2.deepeval_config import get_default_evaluator
from evaluation_v2.metrics import (
    precision_at_k,
    recall_at_k,
    mean_reciprocal_rank,
    ndcg_at_k,
    citation_precision,
    citation_recall,
    aggregate_metric,
    is_abstained,
    is_long_form,
    long_form_evidence_coverage,
)
from services.cost_tracker import CostTracker
from services.latency_tracker import LatencyTracker
from schemas.metrics import EvaluationRun, MetricResult, TestCaseResult, ConfigSnapshot
from services.metrics import save_evaluation_run
from evaluation_v2.review_export import export_review_json, export_review_csv


@dataclass
class EvalRunnerConfig:
    dataset_name: str
    sample_size: int | None = None
    server_url: str = "http://localhost:8001"
    include_reason: bool = True
    retrieval_k: int = 10
    citation_scope: str | None = None
    export_review_path: str | None = None
    export_review_format: str = "json"
    abstention_phrases: list[str] | None = None
    run_notes: str = ""


def _get_config_snapshot() -> Optional[ConfigSnapshot]:
    try:
        from infrastructure.config.models_config import get_models_config
        from pipelines.inference import get_inference_config
        from pipelines.ingestion import get_ingestion_config

        models_config = get_models_config()
        inference_config = get_inference_config()
        ingestion_config = get_ingestion_config()

        return ConfigSnapshot(
            llm_provider=models_config.llm.provider,
            llm_model=models_config.llm.model,
            llm_base_url=models_config.llm.base_url,
            embedding_provider=models_config.embedding.provider,
            embedding_model=models_config.embedding.model,
            retrieval_top_k=inference_config["retrieval_top_k"],
            hybrid_search_enabled=inference_config["hybrid_search_enabled"],
            rrf_k=inference_config["rrf_k"],
            contextual_retrieval_enabled=ingestion_config["contextual_retrieval_enabled"],
            reranker_enabled=inference_config["reranker_enabled"],
            reranker_model=inference_config["reranker_model"],
            reranker_top_n=inference_config.get("reranker_top_n", 5),
            citation_scope=models_config.eval.citation_scope,
            citation_format=models_config.eval.citation_format,
            abstention_phrases=models_config.eval.abstention_phrases,
        )
    except Exception:
        return None


async def _query_rag(client: httpx.AsyncClient, server_url: str, question: str) -> dict:
    response = await client.post(
        f"{server_url}/query",
        json={"query": question, "include_chunks": True},
    )
    response.raise_for_status()
    return response.json()


def _build_retrieved_chunks(sources: list[dict]) -> list[dict]:
    chunks = []
    for source in sources:
        chunks.append(
            {
                "document_id": source.get("document_id"),
                "chunk_id": source.get("chunk_id"),
                "chunk_index": source.get("chunk_index"),
                "text": source.get("full_text") or source.get("excerpt") or "",
                "score": source.get("score"),
            }
        )
    return chunks


def _select_cited_chunks(retrieved_chunks: list[dict], citations: list[dict] | None) -> list[dict]:
    if not citations:
        return []

    cited_doc_ids = set()
    cited_chunk_ids = set()
    for cite in citations:
        if isinstance(cite, dict):
            if cite.get("chunk_id"):
                cited_chunk_ids.add(cite.get("chunk_id"))
            if cite.get("document_id"):
                cited_doc_ids.add(cite.get("document_id"))
        elif isinstance(cite, str):
            cited_chunk_ids.add(cite)

    cited_chunks = []
    for chunk in retrieved_chunks:
        chunk_id = chunk.get("chunk_id")
        doc_id = chunk.get("document_id")
        if chunk_id and chunk_id in cited_chunk_ids:
            cited_chunks.append(chunk)
        elif doc_id and doc_id in cited_doc_ids:
            cited_chunks.append(chunk)

    return cited_chunks


def _to_deepeval_test_case(
    test_case: EvalTestCase,
    actual_answer: str,
    retrieved_chunks: list[dict],
) -> LLMTestCase:
    retrieval_context = [chunk.get("text", "") for chunk in retrieved_chunks if chunk.get("text")]
    return LLMTestCase(
        input=test_case.question,
        actual_output=actual_answer,
        expected_output=test_case.expected_answer,
        retrieval_context=retrieval_context,
        context=retrieval_context,
        name=test_case.metadata.get("id"),
        tags=test_case.metadata.get("tags"),
    )


async def run_evaluation(config: EvalRunnerConfig) -> EvaluationRun:
    dataset = get_dataset(config.dataset_name, sample_size=config.sample_size)
    dataset.load()

    docs = dataset.get_documents()
    tests = dataset.get_test_cases()

    run_id = str(uuid.uuid4())[:8]
    start_time = time.time()

    latency_tracker = LatencyTracker()
    cost_tracker = CostTracker()

    config_snapshot = _get_config_snapshot()
    citation_scope = config.citation_scope
    if citation_scope is None and config_snapshot:
        citation_scope = getattr(config_snapshot, "citation_scope", None)
    if citation_scope is None:
        citation_scope = "retrieved"
    abstention_phrases = config.abstention_phrases
    if abstention_phrases is None and config_snapshot:
        abstention_phrases = getattr(config_snapshot, "abstention_phrases", None)
    if abstention_phrases is None:
        abstention_phrases = []

    review_rows: list[dict] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Clear documents
        response = await client.get(f"{config.server_url}/documents")
        if response.status_code == 200:
            for doc in response.json().get("documents", []):
                doc_id = doc.get("document_id") or doc.get("doc_id")
                if doc_id:
                    await client.delete(f"{config.server_url}/documents/{doc_id}")

        # Upload documents
        for doc in docs:
            files = {"files": (f"{doc.doc_id}.txt", doc.content.encode(), "text/plain")}
            await client.post(f"{config.server_url}/upload", files=files)

        # Give async processing time to complete
        await asyncio.sleep(5)

        # Query and collect results
        retrieved_results = []
        deepeval_cases: list[LLMTestCase] = []

        for test in tests:
            query_start = time.perf_counter()
            result = await _query_rag(client, config.server_url, test.question)
            elapsed_ms = (time.perf_counter() - query_start) * 1000
            latency_tracker.record(elapsed_ms)

            input_tokens = result.get("input_tokens", 0) or len(test.question.split()) * 2
            output_tokens = result.get("output_tokens", 0) or len(result.get("answer", "").split()) * 2
            cost_tracker.track_query(input_tokens, output_tokens)

            retrieved_chunks = _build_retrieved_chunks(result.get("sources", []))
            cited_chunks = retrieved_chunks
            if citation_scope == "explicit":
                cited_chunks = _select_cited_chunks(
                    retrieved_chunks, result.get("citations")
                )
            retrieved_results.append(
                {
                    "test_case": test,
                    "actual_answer": result.get("answer", ""),
                    "retrieved_chunks": retrieved_chunks,
                    "cited_chunks": cited_chunks,
                }
            )

            review_rows.append(
                {
                    "question": test.question,
                    "expected_answer": test.expected_answer,
                    "actual_answer": result.get("answer", ""),
                    "gold_document_ids": test.gold_document_ids,
                    "gold_evidence_texts": test.gold_evidence_texts,
                    "retrieved_document_ids": [c.get("document_id") for c in retrieved_chunks],
                    "retrieved_chunk_ids": [c.get("chunk_id") for c in retrieved_chunks],
                    "cited_document_ids": [c.get("document_id") for c in cited_chunks],
                    "cited_chunk_ids": [c.get("chunk_id") for c in cited_chunks],
                }
            )

            deepeval_cases.append(
                _to_deepeval_test_case(test, result.get("answer", ""), retrieved_chunks)
            )

    # DeepEval metrics
    model = get_default_evaluator()
    metrics = [
        FaithfulnessMetric(model=model, include_reason=config.include_reason),
        AnswerRelevancyMetric(model=model, include_reason=config.include_reason),
        HallucinationMetric(model=model, include_reason=config.include_reason),
    ]

    deepeval_results = evaluate(deepeval_cases, metrics)

    # Retrieval + citation metrics
    precision_scores = []
    recall_scores = []
    mrr_scores = []
    ndcg_scores = []
    citation_precision_scores = []
    citation_recall_scores = []
    long_form_scores = []
    long_form_total = 0
    unanswerable_total = 0
    unanswerable_correct = 0
    answerable_total = 0
    answerable_abstained = 0

    test_case_results: list[TestCaseResult] = []

    for entry in retrieved_results:
        test = entry["test_case"]
        retrieved_chunks = entry["retrieved_chunks"]
        cited_chunks = entry["cited_chunks"]
        gold_evidence = test.gold_evidence_texts
        gold_docs = test.gold_document_ids

        precision_scores.append(
            precision_at_k(retrieved_chunks, gold_evidence, gold_docs, config.retrieval_k)
        )
        recall_scores.append(
            recall_at_k(retrieved_chunks, gold_evidence, gold_docs, config.retrieval_k)
        )
        mrr_scores.append(mean_reciprocal_rank(retrieved_chunks, gold_evidence, gold_docs))
        ndcg_scores.append(ndcg_at_k(retrieved_chunks, gold_evidence, gold_docs, config.retrieval_k))
        citation_precision_scores.append(citation_precision(cited_chunks, gold_evidence, gold_docs))
        citation_recall_scores.append(citation_recall(cited_chunks, gold_evidence, gold_docs))

        expected_answer = test.expected_answer.strip()
        actual_answer = entry["actual_answer"]
        if is_long_form(test.metadata, expected_answer, test.question):
            long_form_total += 1
            long_form_scores.append(
                long_form_evidence_coverage(actual_answer, gold_evidence)
            )
        if expected_answer:
            answerable_total += 1
            if is_abstained(actual_answer, abstention_phrases):
                answerable_abstained += 1
        else:
            unanswerable_total += 1
            if is_abstained(actual_answer, abstention_phrases):
                unanswerable_correct += 1

    # Build per-test results from DeepEval output
    for test_result in getattr(deepeval_results, "test_results", []):
        test_case = getattr(test_result, "input", None)
        question = getattr(test_case, "input", "") if test_case else ""
        expected_answer = getattr(test_case, "expected_output", None) if test_case else None
        actual_answer = getattr(test_case, "actual_output", "") if test_case else ""
        retrieval_context = getattr(test_case, "retrieval_context", []) if test_case else []

        metrics_results: list[MetricResult] = []
        for metric in getattr(test_result, "metrics_data", []):
            name = getattr(metric, "name", "unknown").lower().replace(" ", "_")
            score = getattr(metric, "score", 0.0) or 0.0
            threshold = getattr(metric, "threshold", 0.0) or 0.0
            passed = bool(getattr(metric, "success", False))
            reason = getattr(metric, "reason", None)
            metrics_results.append(
                MetricResult(
                    metric_name=name,
                    score=score,
                    passed=passed,
                    threshold=threshold,
                    reason=reason,
                )
            )

        test_case_results.append(
            TestCaseResult(
                test_id=getattr(test_case, "name", None) or "unknown",
                question=question,
                expected_answer=expected_answer,
                actual_answer=actual_answer,
                metrics=metrics_results,
                passed=bool(getattr(test_result, "success", False)),
                retrieval_context_count=len(retrieval_context),
            )
        )

    # DeepEval per-metric aggregates
    metric_averages: dict[str, float] = {}
    metric_pass_rates: dict[str, float] = {}
    metric_scores: dict[str, list[float]] = {}
    metric_passes: dict[str, list[bool]] = {}

    for test_result in getattr(deepeval_results, "test_results", []):
        for metric in getattr(test_result, "metrics_data", []):
            name = getattr(metric, "name", "").lower().replace(" ", "_")
            score = getattr(metric, "score", 0.0) or 0.0
            passed = bool(getattr(metric, "success", False))
            metric_scores.setdefault(name, []).append(score)
            metric_passes.setdefault(name, []).append(passed)

    for name, scores in metric_scores.items():
        metric_averages[name] = aggregate_metric(scores)
        passes = metric_passes.get(name, [])
        metric_pass_rates[name] = aggregate_metric([1.0 if p else 0.0 for p in passes]) * 100

    # Add retrieval + citation metrics
    unanswerable_accuracy = (
        unanswerable_correct / unanswerable_total if unanswerable_total else 0.0
    )
    answerable_abstain_rate = (
        answerable_abstained / answerable_total if answerable_total else 0.0
    )

    metric_averages.update(
        {
            "precision_at_k": aggregate_metric(precision_scores),
            "recall_at_k": aggregate_metric(recall_scores),
            "mrr": aggregate_metric(mrr_scores),
            "ndcg": aggregate_metric(ndcg_scores),
            "citation_precision": aggregate_metric(citation_precision_scores),
            "citation_recall": aggregate_metric(citation_recall_scores),
            "unanswerable_accuracy": unanswerable_accuracy,
            "answerable_abstain_rate": answerable_abstain_rate,
            "long_form_completeness": aggregate_metric(long_form_scores),
        }
    )

    long_form_avg = aggregate_metric(long_form_scores)

    metric_pass_rates.update(
        {
            "precision_at_k": aggregate_metric([1.0 if s >= 0.5 else 0.0 for s in precision_scores]) * 100,
            "recall_at_k": aggregate_metric([1.0 if s >= 0.5 else 0.0 for s in recall_scores]) * 100,
            "mrr": aggregate_metric([1.0 if s >= 0.3 else 0.0 for s in mrr_scores]) * 100,
            "ndcg": aggregate_metric([1.0 if s >= 0.5 else 0.0 for s in ndcg_scores]) * 100,
            "citation_precision": aggregate_metric([1.0 if s >= 0.6 else 0.0 for s in citation_precision_scores]) * 100,
            "citation_recall": aggregate_metric([1.0 if s >= 0.6 else 0.0 for s in citation_recall_scores]) * 100,
            "unanswerable_accuracy": 100.0 if unanswerable_accuracy >= 0.7 else 0.0,
            "answerable_abstain_rate": 100.0 if answerable_abstain_rate <= 0.2 else 0.0,
            "long_form_completeness": 100.0 if long_form_avg >= 0.5 else 0.0,
        }
    )

    total_tests = len(deepeval_cases)
    passed_tests = sum(1 for tr in getattr(deepeval_results, "test_results", []) if getattr(tr, "success", False))
    pass_rate = (passed_tests / total_tests * 100) if total_tests else 0.0

    eval_run = EvaluationRun(
        run_id=run_id,
        timestamp=datetime.utcnow(),
        framework="DeepEval",
        eval_model=model.model,
        total_tests=total_tests,
        passed_tests=passed_tests,
        pass_rate=pass_rate,
        metric_averages=metric_averages,
        metric_pass_rates=metric_pass_rates,
        retrieval_config=None,
        config_snapshot=config_snapshot,
        latency=latency_tracker.get_metrics(),
        cost=cost_tracker.get_metrics(config_snapshot.llm_model if config_snapshot else "unknown"),
        test_cases=test_case_results,
        notes=config.run_notes,
    )

    save_evaluation_run(eval_run)
    if config.export_review_path:
        output_path = Path(config.export_review_path)
        if config.export_review_format == "csv":
            export_review_csv(review_rows, output_path)
        else:
            export_review_json(review_rows, output_path)
    return eval_run


def run_evaluation_sync(config: EvalRunnerConfig) -> EvaluationRun:
    return asyncio.run(run_evaluation(config))
