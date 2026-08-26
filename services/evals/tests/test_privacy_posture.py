"""Nothing in the eval path is masked — judge prompts embed retrieved chunks and
answers verbatim. So a corpus declared confidential must not be judged outside the
permitted execution boundaries unless the operator explicitly says the eval dataset
is public.

The gate used to be a binary provider set (LOCAL_JUDGE_PROVIDERS) keyed off
pii.enabled. Both halves of that were wrong: "local" is not a property of a
provider string (an OpenAI-compatible transport can point at our own vLLM or at
api.openai.com), and confidential content need not contain PII.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from infrastructure.config.models_config import (
    DEFAULT_ALLOWED_JUDGE_BOUNDARIES,
    DataPolicyConfig,
    EmbeddingConfig,
    EvalConfig,
    ExecutionBoundary,
    LLMConfig,
    ModelsConfig,
    PiiConfig,
)


def build_config(
    judge_boundary: ExecutionBoundary | None,
    *,
    corpus_confidential: bool = True,
    eval_dataset_is_public: bool = False,
    judge_provider: str = "openai",
    pii_enabled: bool = False,
    allowed: set[ExecutionBoundary] | None = None,
) -> ModelsConfig:
    policy = DataPolicyConfig(
        corpus_confidential=corpus_confidential,
        eval_dataset_is_public=eval_dataset_is_public,
        **({"allowed_judge_boundaries": allowed} if allowed is not None else {}),
    )
    return ModelsConfig(
        llm=LLMConfig(provider="vllm", model="Qwen/Qwen2.5-14B-Instruct"),
        embedding=EmbeddingConfig(provider="tei", model="some-embed-model"),
        eval=EvalConfig(
            provider=judge_provider,
            model="some-judge-model",
            api_key="test-key",
            execution_boundary=judge_boundary,
        ),
        pii=PiiConfig(enabled=pii_enabled),
        data_policy=policy,
    )


# ── The boundary model ────────────────────────────────────────────────────────


def test_default_allow_list_is_the_two_in_boundary_values():
    assert DEFAULT_ALLOWED_JUDGE_BOUNDARIES == frozenset(
        {ExecutionBoundary.CUSTOMER_MANAGED, ExecutionBoundary.AWS_MANAGED}
    )
    assert DataPolicyConfig().allowed_judge_boundaries == set(
        DEFAULT_ALLOWED_JUDGE_BOUNDARIES
    )


def test_third_party_judge_rejected_on_confidential_corpus():
    """The intent the old LOCAL_JUDGE_PROVIDERS assertion encoded: a third-party
    judge against confidential content is refused without an explicit override."""
    with pytest.raises(ValueError, match="third_party"):
        build_config(ExecutionBoundary.THIRD_PARTY).validate_privacy_posture()


def test_customer_managed_judge_allowed_on_confidential_corpus():
    build_config(ExecutionBoundary.CUSTOMER_MANAGED).validate_privacy_posture()


def test_aws_managed_judge_allowed_on_confidential_corpus():
    build_config(ExecutionBoundary.AWS_MANAGED).validate_privacy_posture()


def test_missing_boundary_fails_closed():
    """Unknown boundary is not "probably fine" — it is refused."""
    with pytest.raises(ValueError, match="declares no execution_boundary"):
        build_config(None).validate_privacy_posture()


def test_boundary_is_not_inferred_from_provider():
    """An openai-compatible transport pointed at our own vLLM is in-boundary, and
    the same provider string pointed at the vendor is not. Only the declared
    boundary decides."""
    build_config(
        ExecutionBoundary.CUSTOMER_MANAGED, judge_provider="openai"
    ).validate_privacy_posture()

    with pytest.raises(ValueError, match="third_party"):
        build_config(
            ExecutionBoundary.THIRD_PARTY, judge_provider="openai"
        ).validate_privacy_posture()


def test_allow_list_is_configurable_and_can_be_narrowed():
    config = build_config(
        ExecutionBoundary.AWS_MANAGED,
        allowed={ExecutionBoundary.CUSTOMER_MANAGED},
    )
    with pytest.raises(ValueError, match="aws_managed"):
        config.validate_privacy_posture()


# ── The escape hatches ────────────────────────────────────────────────────────


def test_third_party_judge_allowed_when_corpus_declared_not_confidential():
    build_config(
        ExecutionBoundary.THIRD_PARTY, corpus_confidential=False
    ).validate_privacy_posture()


def test_third_party_judge_allowed_when_eval_dataset_is_public():
    """The per-run override: the production corpus stays confidential but this run
    scores a public HuggingFace benchmark, so judge egress leaks nothing."""
    build_config(
        ExecutionBoundary.THIRD_PARTY, eval_dataset_is_public=True
    ).validate_privacy_posture()


def test_missing_boundary_still_allowed_under_an_explicit_override():
    build_config(None, eval_dataset_is_public=True).validate_privacy_posture()


# ── Decoupling from pii.enabled ───────────────────────────────────────────────


def test_egress_gate_does_not_depend_on_pii_enabled():
    """Confidential corpus content need not contain PII. Turning PII masking off
    must not open the judge egress gate, and turning it on must not close it."""
    with pytest.raises(ValueError, match="third_party"):
        build_config(
            ExecutionBoundary.THIRD_PARTY, pii_enabled=False
        ).validate_privacy_posture()

    build_config(
        ExecutionBoundary.CUSTOMER_MANAGED, pii_enabled=True
    ).validate_privacy_posture()


def test_pii_no_longer_carries_a_judge_opt_out():
    assert not hasattr(PiiConfig(), "allow_cloud_judge")


def test_data_policy_defaults_are_closed():
    policy = DataPolicyConfig()
    assert policy.corpus_confidential is True
    assert policy.eval_dataset_is_public is False
    assert ExecutionBoundary.THIRD_PARTY not in policy.allowed_judge_boundaries
