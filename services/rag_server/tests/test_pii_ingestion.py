"""Regression tests: contextual retrieval must never send raw PII to the LLM.

Guards the mask -> LLM -> unmask flow added to pipelines/ingestion.py. If a
future change drops the masking of the prompt, the unmasking of the generated
prefix, or the shared per-document token mapping, these tests fail.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from llama_index.core.schema import TextNode

from infrastructure.config.models_config import PiiConfig
from pipelines.ingestion import (
    add_contextual_prefix_to_chunk,
    add_contextual_prefix_to_chunk_async,
    add_contextual_retrieval,
)

CHUNK_TEXT = "My name is John Smith and my email is john@example.com. Quarterly numbers follow."


def _patch_pii(enabled: bool):
    from infrastructure.pii.service import reset_pii_service

    config = PiiConfig(enabled=enabled)
    reset_pii_service()
    return patch("infrastructure.pii.config.get_pii_config", return_value=config), patch(
        "infrastructure.pii.service.get_pii_config", return_value=config
    )


@pytest.fixture
def pii_enabled():
    p1, p2 = _patch_pii(enabled=True)
    with p1, p2:
        yield
    from infrastructure.pii.service import reset_pii_service

    reset_pii_service()


def _mock_llm(response_text: str = "Chunk discusses [[[PERSON_0]]]'s report."):
    llm = MagicMock()
    response = MagicMock()
    response.text = response_text
    llm.complete.return_value = response
    llm.acomplete = AsyncMock(return_value=response)
    return llm


def test_sync_prompt_contains_no_raw_pii(pii_enabled):
    node = TextNode(text=CHUNK_TEXT)
    llm = _mock_llm()

    with patch("pipelines.ingestion.get_llm_client", return_value=llm):
        add_contextual_prefix_to_chunk(node, "report.pdf", ".pdf")

    prompt = llm.complete.call_args[0][0]
    assert "John Smith" not in prompt
    assert "john@example.com" not in prompt
    assert "[[[PERSON_0]]]" in prompt
    assert "[[[EMAIL_ADDRESS_0]]]" in prompt


def test_sync_prefix_is_unmasked_before_storage(pii_enabled):
    node = TextNode(text=CHUNK_TEXT)
    llm = _mock_llm("Chunk discusses [[[PERSON_0]]]'s report.")

    with patch("pipelines.ingestion.get_llm_client", return_value=llm):
        result = add_contextual_prefix_to_chunk(node, "report.pdf", ".pdf")

    # Prefix stored locally must contain the real value, not the token
    assert result.text.startswith("Chunk discusses John Smith's report.")
    assert "[[[PERSON_0]]]" not in result.text
    # Original chunk text is untouched
    assert CHUNK_TEXT in result.text


def test_async_prompt_contains_no_raw_pii(pii_enabled):
    node = TextNode(text=CHUNK_TEXT)
    llm = _mock_llm()

    with patch("pipelines.ingestion.get_llm_client", return_value=llm):
        result = asyncio.run(add_contextual_prefix_to_chunk_async(node, "report.pdf", ".pdf"))

    prompt = llm.acomplete.call_args[0][0]
    assert "John Smith" not in prompt
    assert "john@example.com" not in prompt
    assert "[[[PERSON_0]]]" in prompt
    assert result.text.startswith("Chunk discusses John Smith's report.")


def test_altered_token_in_prefix_is_fuzzy_recovered(pii_enabled):
    node = TextNode(text=CHUNK_TEXT)
    # LLM dropped the brackets — fuzzy recovery must still restore the original value
    llm = _mock_llm("Chunk discusses PERSON_0's report.")

    with patch("pipelines.ingestion.get_llm_client", return_value=llm):
        result = add_contextual_prefix_to_chunk(node, "report.pdf", ".pdf")

    assert result.text.startswith("Chunk discusses John Smith's report.")


def test_disabled_pii_sends_original_text():
    node = TextNode(text=CHUNK_TEXT)
    llm = _mock_llm("A plain context sentence.")
    p1, p2 = _patch_pii(enabled=False)

    with p1, p2, patch("pipelines.ingestion.get_llm_client", return_value=llm):
        add_contextual_prefix_to_chunk(node, "report.pdf", ".pdf")

    prompt = llm.complete.call_args[0][0]
    assert "John Smith" in prompt
    assert "[[[" not in prompt


def test_llm_failure_returns_original_node(pii_enabled):
    node = TextNode(text=CHUNK_TEXT)
    llm = MagicMock()
    llm.acomplete = AsyncMock(side_effect=Exception("LLM unavailable"))

    with patch("pipelines.ingestion.get_llm_client", return_value=llm):
        result = asyncio.run(add_contextual_prefix_to_chunk_async(node, "report.pdf", ".pdf"))

    assert result.text == CHUNK_TEXT


def test_document_mapping_shared_across_chunks(pii_enabled):
    """Same entity in different chunks of one document gets the same token."""
    nodes = [
        TextNode(text="My name is John Smith and I wrote section one."),
        TextNode(text="My name is John Smith and I wrote section two."),
    ]
    prompts = []

    llm = MagicMock()

    async def fake_acomplete(prompt):
        prompts.append(prompt)
        response = MagicMock()
        response.text = "context"
        return response

    llm.acomplete = fake_acomplete

    with patch("pipelines.ingestion.get_ingestion_config", return_value={"contextual_retrieval_enabled": True}), \
         patch("pipelines.ingestion.get_llm_client", return_value=llm), \
         patch("pipelines.ingestion.get_models_config") as mock_models:
        mock_models.return_value.retrieval.contextual_concurrency = 2
        add_contextual_retrieval(nodes, "/tmp/doc.txt")

    assert len(prompts) == 2
    for prompt in prompts:
        assert "John Smith" not in prompt
        assert "[[[PERSON_0]]]" in prompt
    # No PERSON_1 anywhere: the mapping was shared, not re-minted per chunk
    assert all("PERSON_1" not in p for p in prompts)
