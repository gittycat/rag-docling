"""Evaluator handling for query-pipeline stage traces."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from evals.runner import RAGClient, parse_rag_response, parse_search_response


def test_parse_rag_response_preserves_stage_items_and_ttft():
    response = parse_rag_response(
        "q1",
        {
            "answer": "answer",
            "metrics": {
                "stages": [
                    {
                        "name": "fusion",
                        "duration_ms": 2.5,
                        "item_count": 1,
                        "items": [
                            {
                                "chunk_id": "chunk-1", "doc_id": "doc-1", "score": 0.4, "rank": 1,
                                "metadata": {"file_hash": "f" * 64},
                            }
                        ],
                        "status": "ok",
                        "error": None,
                    }
                ],
                "time_to_first_token_ms": 42.0,
            },
        },
        latency_ms=100.0,
    )

    assert response.metrics.time_to_first_token_ms == 42.0
    assert response.metrics.stages[0].name == "fusion"
    assert response.metrics.stages[0].items[0].chunk_id == "chunk-1"
    assert response.metrics.stages[0].items[0].metadata["file_hash"] == "f" * 64


def test_parse_rag_response_preserves_chunk_lineage() -> None:
    response = parse_rag_response(
        "q1",
        {
            "answer": "answer",
            "sources": [{
                "document_id": "doc-1",
                "chunk_id": "chunk-1",
                "file_hash": "f" * 64,
                "source_locator": {
                    "document_hash": "f" * 64,
                    "source_format": "txt",
                    "locator": {"element_path": "document", "start_char": 0, "end_char": 10},
                },
            }],
        },
        latency_ms=100.0,
    )

    assert response.retrieved_chunks[0].metadata["file_hash"] == "f" * 64
    assert response.retrieved_chunks[0].metadata["source_locator"]["source_format"] == "txt"


def test_parse_search_response_uses_requested_stage_without_an_answer() -> None:
    response = parse_search_response(
        "q1",
        [{
            "name": "fusion", "duration_ms": 1, "item_count": 1, "status": "ok",
            "error": None,
            "items": [{
                "chunk_id": "chunk-1", "doc_id": "doc-1", "score": 0.4, "rank": 1,
                "metadata": {"file_hash": "f" * 64},
            }],
        }],
        latency_ms=10,
        selected_stage="fusion",
    )

    assert response.answer == ""
    assert response.retrieved_chunks[0].chunk_id == "chunk-1"
    assert response.retrieved_chunks[0].metadata["file_hash"] == "f" * 64


@pytest.mark.asyncio
async def test_rag_client_search_posts_retrieval_only_payload():
    client = RAGClient("http://rag.test")
    response = MagicMock()
    response.json.return_value = [{"name": "fusion"}]
    client._client.post = AsyncMock(return_value=response)

    result = await client.search("where is the evidence?", top_k=7, stages=["fusion"])

    assert result == [{"name": "fusion"}]
    client._client.post.assert_awaited_once_with(
        "http://rag.test/search",
        json={"query": "where is the evidence?", "top_k": 7, "stages": ["fusion"]},
    )
    await client.close()


@pytest.mark.asyncio
async def test_rag_client_reads_chunk_lineage_catalog():
    client = RAGClient("http://rag.test")
    response = MagicMock()
    response.json.return_value = {"chunks": [{"chunk_id": "chunk-1"}]}
    client._client.get = AsyncMock(return_value=response)

    assert await client.get_document_chunks("doc-1") == [{"chunk_id": "chunk-1"}]
    client._client.get.assert_awaited_once_with("http://rag.test/documents/doc-1/chunks")
    await client.close()
