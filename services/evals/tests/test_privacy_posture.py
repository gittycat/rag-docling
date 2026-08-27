"""Nothing in the eval path is masked — judge prompts embed retrieved chunks and
answers verbatim. So a corpus declared confidential must not be judged outside the
permitted execution boundaries unless *this run's* content is declared public.

The gate used to be a binary provider set (LOCAL_JUDGE_PROVIDERS) keyed off
pii.enabled. Both halves of that were wrong: "local" is not a property of a
provider string (an OpenAI-compatible transport can point at our own vLLM or at
api.openai.com), and confidential content need not contain PII.

It was then a single global boolean, `eval_dataset_is_public`, which was wrong in
a third way: it could not see which dataset a run was using, so setting it once
let a `golden` run — authored from the operator's own documents — ship the corpus
verbatim to a third-party judge. Publicity is now computed per run from the
datasets and the tier.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.config import DatasetName, EvalTier, eval_content_is_public
from infrastructure.config.models_config import (
    DEFAULT_ALLOWED_JUDGE_BOUNDARIES,
    DEFAULT_PUBLIC_DATASETS,
    DataPolicyConfig,
    EmbeddingConfig,
    EvalConfig,
    ExecutionBoundary,
    LLMConfig,
    ModelsConfig,
    PiiConfig,
    enforce_judge_boundary,
)


def build_policy(
    *,
    corpus_confidential: bool = True,
    allowed: set[ExecutionBoundary] | None = None,
    public_datasets: set[str] | None = None,
    eval_index_is_isolated: bool = False,
) -> DataPolicyConfig:
    return DataPolicyConfig(
        corpus_confidential=corpus_confidential,
        eval_index_is_isolated=eval_index_is_isolated,
        **({"allowed_judge_boundaries": allowed} if allowed is not None else {}),
        **({"public_datasets": public_datasets} if public_datasets is not None else {}),
    )


def build_config(
    judge_boundary: ExecutionBoundary | None,
    *,
    corpus_confidential: bool = True,
    judge_provider: str = "openai",
    pii_enabled: bool = False,
    allowed: set[ExecutionBoundary] | None = None,
    public_datasets: set[str] | None = None,
    eval_index_is_isolated: bool = False,
) -> ModelsConfig:
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
        data_policy=build_policy(
            corpus_confidential=corpus_confidential,
            allowed=allowed,
            public_datasets=public_datasets,
            eval_index_is_isolated=eval_index_is_isolated,
        ),
    )


def gate(
    boundary: ExecutionBoundary | None,
    *,
    datasets: list[DatasetName] | None,
    tier: EvalTier | None,
    policy: DataPolicyConfig | None = None,
) -> None:
    """Run the gate exactly as resolve_judge_config does."""
    policy = policy or build_policy()
    enforce_judge_boundary(
        boundary,
        policy,
        "test/judge",
        eval_content_is_public=eval_content_is_public(datasets, tier, policy),
    )


PUBLIC_GEN = {"datasets": [DatasetName.RAGBENCH], "tier": EvalTier.GENERATION}


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
        gate(ExecutionBoundary.THIRD_PARTY, datasets=[DatasetName.GOLDEN],
             tier=EvalTier.GENERATION)


def test_customer_managed_judge_allowed_on_confidential_corpus():
    gate(ExecutionBoundary.CUSTOMER_MANAGED, datasets=[DatasetName.GOLDEN],
         tier=EvalTier.GENERATION)


def test_aws_managed_judge_allowed_on_confidential_corpus():
    gate(ExecutionBoundary.AWS_MANAGED, datasets=[DatasetName.GOLDEN],
         tier=EvalTier.GENERATION)


def test_missing_boundary_fails_closed():
    """Unknown boundary is not "probably fine" — it is refused."""
    with pytest.raises(ValueError, match="declares no execution_boundary"):
        gate(None, datasets=[DatasetName.GOLDEN], tier=EvalTier.GENERATION)


def test_boundary_is_not_inferred_from_provider():
    """An openai-compatible transport pointed at our own vLLM is in-boundary, and
    the same provider string pointed at the vendor is not. Only the declared
    boundary decides."""
    gate(ExecutionBoundary.CUSTOMER_MANAGED, datasets=[DatasetName.GOLDEN],
         tier=EvalTier.GENERATION)

    with pytest.raises(ValueError, match="third_party"):
        gate(ExecutionBoundary.THIRD_PARTY, datasets=[DatasetName.GOLDEN],
             tier=EvalTier.GENERATION)


def test_allow_list_is_configurable_and_can_be_narrowed():
    policy = build_policy(allowed={ExecutionBoundary.CUSTOMER_MANAGED})
    with pytest.raises(ValueError, match="aws_managed"):
        gate(ExecutionBoundary.AWS_MANAGED, datasets=[DatasetName.GOLDEN],
             tier=EvalTier.GENERATION, policy=policy)


def test_every_gate_error_names_the_three_resolutions():
    """An operator who hits this must not have to read the source to get out."""
    for boundary in (None, ExecutionBoundary.THIRD_PARTY):
        with pytest.raises(ValueError) as exc:
            gate(boundary, datasets=[DatasetName.GOLDEN], tier=EvalTier.GENERATION)
        message = str(exc.value)
        assert "active.eval" in message
        assert "eval_index_is_isolated" in message
        assert "corpus_confidential" in message


# ── Publicity is a property of the run, not the deployment ────────────────────


def test_public_dataset_in_generation_tier_is_public():
    gate(ExecutionBoundary.THIRD_PARTY, **PUBLIC_GEN)


def test_golden_is_never_public_by_default():
    """`golden` is authored from the operator's own documents. It is deliberately
    absent from the shipped public list — this is the defect that motivated the
    per-run gate."""
    assert "golden" not in DEFAULT_PUBLIC_DATASETS
    with pytest.raises(ValueError, match="third_party"):
        gate(ExecutionBoundary.THIRD_PARTY, datasets=[DatasetName.GOLDEN],
             tier=EvalTier.GENERATION)


def test_end_to_end_is_gated_even_for_a_public_dataset():
    """The tier that queries the live index can return operator chunks whatever
    dataset asked the question."""
    with pytest.raises(ValueError, match="third_party"):
        gate(ExecutionBoundary.THIRD_PARTY, datasets=[DatasetName.RAGBENCH],
             tier=EvalTier.END_TO_END)


def test_end_to_end_is_allowed_when_the_index_is_declared_isolated():
    gate(
        ExecutionBoundary.THIRD_PARTY,
        datasets=[DatasetName.RAGBENCH],
        tier=EvalTier.END_TO_END,
        policy=build_policy(eval_index_is_isolated=True),
    )


def test_a_mixed_run_is_as_confidential_as_its_worst_dataset():
    with pytest.raises(ValueError, match="third_party"):
        gate(
            ExecutionBoundary.THIRD_PARTY,
            datasets=[DatasetName.RAGBENCH, DatasetName.GOLDEN],
            tier=EvalTier.GENERATION,
        )


def test_unknown_datasets_or_tier_fail_closed():
    policy = build_policy()
    assert eval_content_is_public(None, EvalTier.GENERATION, policy) is False
    assert eval_content_is_public([], EvalTier.GENERATION, policy) is False
    assert eval_content_is_public([DatasetName.RAGBENCH], None, policy) is False


def test_public_datasets_is_operator_configurable():
    """An operator who knows their golden set is synthetic can say so."""
    gate(
        ExecutionBoundary.THIRD_PARTY,
        datasets=[DatasetName.GOLDEN],
        tier=EvalTier.GENERATION,
        policy=build_policy(public_datasets={"golden"}),
    )


# ── The remaining escape hatch ────────────────────────────────────────────────


def test_third_party_judge_allowed_when_corpus_declared_not_confidential():
    gate(
        ExecutionBoundary.THIRD_PARTY,
        datasets=[DatasetName.GOLDEN],
        tier=EvalTier.END_TO_END,
        policy=build_policy(corpus_confidential=False),
    )


# ── The removed key must not be ignored ───────────────────────────────────────


def test_legacy_eval_dataset_is_public_refuses_to_load():
    """Silently ignoring a key an operator relies on for safety is worse than
    refusing to boot."""
    with pytest.raises(ValueError) as exc:
        DataPolicyConfig(corpus_confidential=True, eval_dataset_is_public=True)
    message = str(exc.value)
    assert "public_datasets" in message
    assert "eval_index_is_isolated" in message


# ── Load-time check is structural only ────────────────────────────────────────


def test_config_load_refuses_a_judge_with_no_declared_boundary():
    """The half of the gate that *is* knowable without a dataset."""
    with pytest.raises(ValueError, match="declares no execution_boundary"):
        build_config(None).validate_privacy_posture()


def test_config_load_does_not_apply_the_allow_list():
    """A third-party judge is legitimate for a public-dataset run, and load time
    cannot know which run is coming. Deferring this is what lets `just eval
    --tier generation --datasets squad_v2` work while `--datasets golden` fails."""
    build_config(ExecutionBoundary.THIRD_PARTY).validate_privacy_posture()


def test_config_load_skips_the_check_on_a_non_confidential_corpus():
    build_config(None, corpus_confidential=False).validate_privacy_posture()


# ── Decoupling from pii.enabled ───────────────────────────────────────────────


def test_egress_gate_does_not_depend_on_pii_enabled():
    """Confidential corpus content need not contain PII. Turning PII masking off
    must not open the judge egress gate, and turning it on must not close it."""
    with pytest.raises(ValueError, match="third_party"):
        gate(ExecutionBoundary.THIRD_PARTY, datasets=[DatasetName.GOLDEN],
             tier=EvalTier.GENERATION)

    gate(ExecutionBoundary.CUSTOMER_MANAGED, datasets=[DatasetName.GOLDEN],
         tier=EvalTier.GENERATION)


def test_pii_no_longer_carries_a_judge_opt_out():
    assert not hasattr(PiiConfig(), "allow_cloud_judge")


def test_data_policy_defaults_are_closed():
    policy = DataPolicyConfig()
    assert policy.corpus_confidential is True
    assert policy.eval_index_is_isolated is False
    assert policy.public_datasets == set(DEFAULT_PUBLIC_DATASETS)
    assert "golden" not in policy.public_datasets
    assert ExecutionBoundary.THIRD_PARTY not in policy.allowed_judge_boundaries
