"""Regression tests: node metadata must never carry raw PII to the LLM.

The synthesizer renders retrieved nodes with MetadataMode.LLM, so anything left
unmasked in node.metadata (file_name, path) lands in the prompt even though the
chunk text itself was masked. These tests guard both directions: masking on the
way out, unmasking on the way back so the UI still shows the real filename.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from llama_index.core.schema import MetadataMode, NodeWithScore, TextNode

from infrastructure.config.models_config import PiiConfig
from infrastructure.pii.postprocessor import PIIMaskingPostprocessor
from infrastructure.pii.service import TokenMapping

CHUNK_TEXT = "The severance terms were agreed with John Smith."
FILE_NAME = "Jane Doe severance 2025.pdf"


@pytest.fixture
def pii_enabled():
    from infrastructure.pii.service import reset_pii_service

    config = PiiConfig(enabled=True)
    reset_pii_service()
    with patch("infrastructure.pii.config.get_pii_config", return_value=config), patch(
        "infrastructure.pii.service.get_pii_config", return_value=config
    ):
        yield
    reset_pii_service()


def _node(chunk_index: int = 0) -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(
            text=CHUNK_TEXT,
            metadata={
                "file_name": FILE_NAME,
                "path": "/app/documents/hr/Jane Doe",
                "document_id": "doc-abc-123",
                "chunk_index": chunk_index,
                "file_hash": "9f2b" * 16,
            },
        ),
        score=0.9,
    )


def test_metadata_masked_before_reaching_llm(pii_enabled):
    postprocessor = PIIMaskingPostprocessor(token_mapping=TokenMapping(), context_id="session-1")

    masked = postprocessor.postprocess_nodes([_node()], query_bundle=None)

    # MetadataMode.LLM is what the synthesizer actually sends
    llm_visible = masked[0].node.get_content(metadata_mode=MetadataMode.LLM)
    assert "Jane" not in llm_visible
    assert "Doe" not in llm_visible
    assert "John Smith" not in llm_visible
    assert "[[[PERSON_" in llm_visible


def test_structural_metadata_preserved(pii_enabled):
    postprocessor = PIIMaskingPostprocessor(token_mapping=TokenMapping(), context_id="session-1")

    metadata = postprocessor.postprocess_nodes([_node()], query_bundle=None)[0].node.metadata

    # extract_sources dedupes on document_id — it must survive verbatim
    assert metadata["document_id"] == "doc-abc-123"
    assert metadata["chunk_index"] == 0
    assert metadata["file_hash"] == "9f2b" * 16


def test_source_nodes_round_trip_to_original_metadata(pii_enabled):
    from pipelines.inference import _unmask_source_nodes

    token_mapping = TokenMapping()
    postprocessor = PIIMaskingPostprocessor(token_mapping=token_mapping, context_id="session-1")

    masked = postprocessor.postprocess_nodes([_node()], query_bundle=None)
    restored = _unmask_source_nodes(masked, token_mapping)

    assert restored[0].node.metadata["file_name"] == FILE_NAME
    assert restored[0].node.metadata["path"] == "/app/documents/hr/Jane Doe"
    assert restored[0].node.get_content() == CHUNK_TEXT


@pytest.mark.xfail(
    reason="Known detector gap, not a plumbing gap: spaCy NER does not recognize names "
    "joined by separators, so 'Jane_Doe_severance.pdf' survives masking. Tracked as the "
    "detector-backend upgrade (GLiNER recognizer / separator normalization).",
    strict=True,
)
def test_separator_joined_name_in_filename_is_masked(pii_enabled):
    postprocessor = PIIMaskingPostprocessor(token_mapping=TokenMapping(), context_id="session-1")
    node = NodeWithScore(
        node=TextNode(text=CHUNK_TEXT, metadata={"file_name": "Jane_Doe_severance_2025.pdf"}),
        score=0.9,
    )

    masked = postprocessor.postprocess_nodes([node], query_bundle=None)

    assert "Jane" not in masked[0].node.metadata["file_name"]


def test_repeated_metadata_masked_once_per_batch(pii_enabled):
    """Every chunk of a document carries the same file_name — mask() must not
    re-run Presidio per chunk."""
    postprocessor = PIIMaskingPostprocessor(token_mapping=TokenMapping(), context_id="session-1")
    nodes = [_node(chunk_index=i) for i in range(4)]

    with patch(
        "infrastructure.pii.postprocessor.mask_text", wraps=__import__(
            "infrastructure.pii.postprocessor", fromlist=["mask_text"]
        ).mask_text
    ) as spy:
        masked = postprocessor.postprocess_nodes(nodes, query_bundle=None)

    # 4 chunk texts + file_name + path (each masked once, then cached)
    assert spy.call_count == 6

    file_names = {n.node.metadata["file_name"] for n in masked}
    assert len(file_names) == 1  # consistent token across chunks


def test_masking_disabled_leaves_metadata_untouched():
    from infrastructure.pii.service import reset_pii_service

    config = PiiConfig(enabled=False)
    reset_pii_service()
    with patch("infrastructure.pii.config.get_pii_config", return_value=config), patch(
        "infrastructure.pii.service.get_pii_config", return_value=config
    ):
        postprocessor = PIIMaskingPostprocessor(token_mapping=TokenMapping(), context_id="session-1")
        masked = postprocessor.postprocess_nodes([_node()], query_bundle=None)

    assert masked[0].node.metadata["file_name"] == FILE_NAME
    reset_pii_service()
