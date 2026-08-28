"""Cost and latency metrics derived from persisted ingestion stages."""

import asyncio

import pytest

from evals.metrics.performance import (
    CostPerQuery,
    IngestionCostPerDocument,
    IngestionLatencyPerDocument,
)
from evals.schemas import EvalQuestion, EvalResponse, IngestionStage, QueryMetrics, TokenUsage


def _question() -> EvalQuestion:
    return EvalQuestion(id="q1", question="q?", expected_answer="a")


def _response() -> EvalResponse:
    return EvalResponse(
        question_id="q1",
        answer="a",
        metrics=QueryMetrics(
            latency_ms=10,
            token_usage=TokenUsage(prompt_tokens=1_000, completion_tokens=0, total_tokens=1_000),
        ),
    )


def _stages() -> list[IngestionStage]:
    return [
        IngestionStage(document_id="doc-1", name="parse", duration_ms=10, item_count=1),
        IngestionStage(
            document_id="doc-1", name="contextual_enrich", duration_ms=20,
            input_tokens=1_000_000, output_tokens=1_000_000, item_count=1,
            enrichment_success_rate=1.0,
        ),
        IngestionStage(
            document_id="doc-1", name="embed", duration_ms=30,
            input_tokens=1_000_000, item_count=2,
        ),
        IngestionStage(document_id="doc-1", name="index", duration_ms=40, item_count=2),
    ]


def test_ingestion_metrics_attribute_cost_and_latency_by_stage():
    stages = _stages()
    cost = asyncio.run(
        IngestionCostPerDocument(stages, "gpt-4o", "text-embedding-3-small").compute_batch([], [])
    )
    latency = asyncio.run(IngestionLatencyPerDocument(stages).compute_batch([], []))

    assert cost.value == pytest.approx(12.52)
    assert cost.details["by_stage_usd"] == pytest.approx(
        {"contextual_enrich": 12.5, "embed": 0.02}
    )
    assert latency.value == pytest.approx(100)
    assert latency.details["by_stage_ms"] == pytest.approx(
        {"parse": 10, "contextual_enrich": 20, "embed": 30, "index": 40}
    )
    assert latency.details["enrichment_success_rate"] == 1.0


def test_unpriced_embedding_keeps_ingestion_and_query_cost_undefined():
    ingestion = asyncio.run(
        IngestionCostPerDocument(_stages(), "gpt-4o", "self-hosted-unknown").compute_batch([], [])
    )
    query = asyncio.run(
        CostPerQuery(model="gpt-4o", ingestion_cost_usd=ingestion.value).compute_batch(
            [_question()], [_response()]
        )
    )

    assert ingestion.value is None
    assert "doc-1:embed" in ingestion.details["unpriced_stages"]
    assert query.value is None
    assert "ingestion" in query.details["unpriced_components"]
