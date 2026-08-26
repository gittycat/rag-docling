import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import pytest
from llama_index.core.schema import TextNode

from pipelines.ingestion import embed_chunks, INGEST_BATCH_SIZE


def _make_nodes(n):
    return [TextNode(text=f"chunk {i}", id_=f"doc-chunk-{i}") for i in range(n)]


def _http_status_error(status_code: int, retry_after: str | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://tei/embed")
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    response = httpx.Response(status_code, request=request, headers=headers)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_embed_chunks_batches_embedding_calls():
    nodes = _make_nodes(70)  # 3 batches of 32/32/6

    mock_embed_model = MagicMock()
    mock_embed_model.aget_text_embedding_batch = AsyncMock(
        side_effect=lambda texts: [[0.1] * 8 for _ in texts]
    )

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.get_models_config") as mock_get_config:
        mock_settings.embed_model = mock_embed_model
        mock_get_config.return_value.retrieval.embed_concurrency = 8
        embed_chunks(nodes)

    assert mock_embed_model.aget_text_embedding_batch.call_count == 3
    batch_sizes = sorted(
        len(call.args[0]) for call in mock_embed_model.aget_text_embedding_batch.call_args_list
    )
    assert batch_sizes == sorted([INGEST_BATCH_SIZE, INGEST_BATCH_SIZE, 70 - 2 * INGEST_BATCH_SIZE])
    # Every node carries its embedding onward; add_chunks persists them later.
    assert all(node.embedding == [0.1] * 8 for node in nodes)


def test_embed_chunks_sets_node_embeddings():
    nodes = _make_nodes(2)

    mock_embed_model = MagicMock()
    mock_embed_model.aget_text_embedding_batch = AsyncMock(return_value=[[0.1] * 8, [0.2] * 8])

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.get_models_config") as mock_get_config:
        mock_settings.embed_model = mock_embed_model
        mock_get_config.return_value.retrieval.embed_concurrency = 8
        assert embed_chunks(nodes) is None  # persists nothing, returns nothing

    assert nodes[0].embedding == [0.1] * 8
    assert nodes[1].embedding == [0.2] * 8


def test_embed_chunks_calls_progress_callback_per_batch():
    nodes = _make_nodes(40)  # 2 batches
    progress_calls = []

    mock_embed_model = MagicMock()
    mock_embed_model.aget_text_embedding_batch = AsyncMock(
        side_effect=lambda texts: [[0.1] * 8 for _ in texts]
    )

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.get_models_config") as mock_get_config:
        mock_settings.embed_model = mock_embed_model
        mock_get_config.return_value.retrieval.embed_concurrency = 8
        embed_chunks(nodes, progress_callback=lambda done, total: progress_calls.append((done, total)))

    # Both batches fit under the concurrency limit and neither AsyncMock call
    # truly suspends, so completion order matches batch creation order.
    assert sorted(progress_calls) == [(32, 40), (40, 40)]
    assert progress_calls[-1] == (40, 40)


def test_embed_chunks_retries_on_connection_error():
    """Non-httpx errors fall back to the substring classifier."""
    nodes = _make_nodes(1)

    mock_embed_model = MagicMock()
    mock_embed_model.aget_text_embedding_batch = AsyncMock(
        side_effect=[ConnectionError("connection refused"), [[0.1] * 8]]
    )

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.get_models_config") as mock_get_config, \
         patch("pipelines.ingestion.asyncio.sleep", new_callable=AsyncMock):
        mock_settings.embed_model = mock_embed_model
        mock_get_config.return_value.retrieval.embed_concurrency = 8
        embed_chunks(nodes)

    assert mock_embed_model.aget_text_embedding_batch.call_count == 2
    assert nodes[0].embedding == [0.1] * 8


@pytest.mark.parametrize("status_code", [429, 503])
def test_embed_chunks_retries_on_retryable_http_status(status_code):
    """TEI's queue-full (429) and transient server (5xx) errors must not abort
    the whole document — only a single batch is retried.
    """
    nodes = _make_nodes(1)

    mock_embed_model = MagicMock()
    mock_embed_model.aget_text_embedding_batch = AsyncMock(
        side_effect=[_http_status_error(status_code), [[0.1] * 8]]
    )

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.get_models_config") as mock_get_config, \
         patch("pipelines.ingestion.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_settings.embed_model = mock_embed_model
        mock_get_config.return_value.retrieval.embed_concurrency = 8
        embed_chunks(nodes)

    assert mock_embed_model.aget_text_embedding_batch.call_count == 2
    assert nodes[0].embedding == [0.1] * 8
    mock_sleep.assert_awaited()


def test_embed_chunks_honours_retry_after_header():
    nodes = _make_nodes(1)

    mock_embed_model = MagicMock()
    mock_embed_model.aget_text_embedding_batch = AsyncMock(
        side_effect=[_http_status_error(429, retry_after="7"), [[0.1] * 8]]
    )

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.get_models_config") as mock_get_config, \
         patch("pipelines.ingestion.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_settings.embed_model = mock_embed_model
        mock_get_config.return_value.retrieval.embed_concurrency = 8
        embed_chunks(nodes)

    mock_sleep.assert_awaited_once_with(7.0)


def test_embed_chunks_does_not_retry_on_400():
    """A 400 (e.g. a chunk over TEI's max input length) will never succeed on
    retry, so it must abort immediately rather than burn through max_retries.
    """
    nodes = _make_nodes(1)

    mock_embed_model = MagicMock()
    mock_embed_model.aget_text_embedding_batch = AsyncMock(side_effect=_http_status_error(400))

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.get_models_config") as mock_get_config, \
         patch("pipelines.ingestion.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        mock_settings.embed_model = mock_embed_model
        mock_get_config.return_value.retrieval.embed_concurrency = 8

        with pytest.raises(Exception):
            embed_chunks(nodes)

    assert mock_embed_model.aget_text_embedding_batch.call_count == 1
    mock_sleep.assert_not_awaited()
