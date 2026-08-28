"""The prompt fingerprint is what lets a consumer notice a prompt edit.

The eval runner keys its query cache on the server's reported configuration.
Prompts were absent from that key, so editing `prompts.context` — the one edit
whose purpose is to change the answers — left the next run scoring cached
answers produced by the old prompt.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.llm.prompts import get_prompt_fingerprint


def _config(system="You are an assistant.",
            context="Use ONLY {context_str}.{citation_instructions}",
            citation_scope="retrieved"):
    config = MagicMock()
    config.prompts.system = system
    config.prompts.context = context
    config.prompts.condense = None
    config.prompts.contextual_prefix = "Document: {document_name}"
    config.prompts.citation_instructions.numeric = "\n- Cite as [1]."
    config.eval.citation_scope = citation_scope
    config.eval.citation_format = "numeric"
    return config


def _fingerprint(config) -> str:
    targets = [
        "infrastructure.llm.prompts.get_models_config",
        "infrastructure.config.models_config.get_models_config",
    ]
    with patch(targets[0], return_value=config), patch(targets[1], return_value=config):
        return get_prompt_fingerprint()


def test_the_fingerprint_is_stable_for_unchanged_prompts():
    assert _fingerprint(_config()) == _fingerprint(_config())


def test_editing_the_context_prompt_changes_the_fingerprint():
    before = _fingerprint(_config())
    after = _fingerprint(_config(context="Answer freely from {context_str}.{citation_instructions}"))
    assert before != after


def test_editing_the_system_prompt_changes_the_fingerprint():
    assert _fingerprint(_config()) != _fingerprint(_config(system="Be terse."))


def test_citation_scope_changes_the_fingerprint():
    """It changes what the model is sent, so it must not share a key."""
    retrieved = _fingerprint(_config(citation_scope="retrieved"))
    explicit = _fingerprint(_config(citation_scope="explicit"))
    assert retrieved != explicit


def test_the_fingerprint_is_short_and_hex():
    fp = _fingerprint(_config())
    assert len(fp) == 16
    int(fp, 16)
