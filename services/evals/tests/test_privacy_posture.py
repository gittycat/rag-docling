"""Nothing in the eval path is masked — judge prompts embed retrieved chunks and
answers verbatim. So a corpus declared sensitive (pii.enabled) must not be judged
by a cloud model unless the operator explicitly opts out.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.config.models_config import (
    EmbeddingConfig,
    EvalConfig,
    LLMConfig,
    ModelsConfig,
    PiiConfig,
)


def build_config(judge_provider: str, pii_enabled: bool, allow_cloud_judge: bool = False) -> ModelsConfig:
    return ModelsConfig(
        llm=LLMConfig(provider="ollama", model="gemma3:4b"),
        embedding=EmbeddingConfig(provider="ollama", model="some-embed-model"),
        eval=EvalConfig(provider=judge_provider, model="some-judge-model", api_key="test-key"),
        pii=PiiConfig(enabled=pii_enabled, allow_cloud_judge=allow_cloud_judge),
    )


def test_local_judge_allowed_with_pii_enabled():
    build_config("ollama", pii_enabled=True).validate_privacy_posture()  # should not raise


def test_cloud_judge_allowed_when_pii_disabled():
    build_config("anthropic", pii_enabled=False).validate_privacy_posture()  # user's explicit choice


def test_cloud_judge_rejected_with_pii_enabled():
    with pytest.raises(ValueError, match="not local"):
        build_config("anthropic", pii_enabled=True).validate_privacy_posture()


def test_cloud_judge_allowed_with_explicit_optout():
    config = build_config("anthropic", pii_enabled=True, allow_cloud_judge=True)
    config.validate_privacy_posture()  # should not raise


def test_pii_defaults_are_closed():
    assert PiiConfig().enabled is False
    assert PiiConfig().allow_cloud_judge is False
