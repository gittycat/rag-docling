import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from llama_index.core.schema import TextNode

from pipelines.ingestion import embed_chunks, INGEST_BATCH_SIZE


def _make_nodes(n):
    return [TextNode(text=f"chunk {i}", id_=f"doc-chunk-{i}") for i in range(n)]


def test_embed_chunks_batches_embedding_calls():
    nodes = _make_nodes(70)  # 3 batches of 32/32/6

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding_batch.side_effect = lambda texts: [[0.1] * 8 for _ in texts]

    with patch("pipelines.ingestion.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        embed_chunks(nodes)

    assert mock_embed_model.get_text_embedding_batch.call_count == 3
    batch_sizes = [len(call.args[0]) for call in mock_embed_model.get_text_embedding_batch.call_args_list]
    assert batch_sizes == [INGEST_BATCH_SIZE, INGEST_BATCH_SIZE, 70 - 2 * INGEST_BATCH_SIZE]
    # Every node carries its embedding onward; add_chunks persists them later.
    assert all(node.embedding == [0.1] * 8 for node in nodes)


def test_embed_chunks_sets_node_embeddings():
    nodes = _make_nodes(2)

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding_batch.return_value = [[0.1] * 8, [0.2] * 8]

    with patch("pipelines.ingestion.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        assert embed_chunks(nodes) is None  # persists nothing, returns nothing

    assert nodes[0].embedding == [0.1] * 8
    assert nodes[1].embedding == [0.2] * 8


def test_embed_chunks_calls_progress_callback_per_batch():
    nodes = _make_nodes(40)  # 2 batches
    progress_calls = []

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding_batch.side_effect = lambda texts: [[0.1] * 8 for _ in texts]

    with patch("pipelines.ingestion.Settings") as mock_settings:
        mock_settings.embed_model = mock_embed_model
        embed_chunks(nodes, progress_callback=lambda done, total: progress_calls.append((done, total)))

    assert progress_calls == [(32, 40), (40, 40)]


def test_embed_chunks_retries_on_connection_error():
    nodes = _make_nodes(1)

    mock_embed_model = MagicMock()
    mock_embed_model.get_text_embedding_batch.side_effect = [
        ConnectionError("connection refused"),
        [[0.1] * 8],
    ]

    with patch("pipelines.ingestion.Settings") as mock_settings, \
         patch("pipelines.ingestion.time.sleep"):
        mock_settings.embed_model = mock_embed_model
        embed_chunks(nodes)

    assert mock_embed_model.get_text_embedding_batch.call_count == 2
    assert nodes[0].embedding == [0.1] * 8
