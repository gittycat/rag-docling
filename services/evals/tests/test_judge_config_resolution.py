"""The judge a run calls must be the judge `active.eval` names.

Regression suite for a defect that made every eval run call Anthropic's
claude-sonnet-4-20250514 (retired 2026-06-15) no matter what config.yml said:
JudgeConfig defaulted to provider="anthropic"/model="claude-sonnet-4-20250514",
both entry points constructed JudgeConfig(enabled=...) without provider or model,
and LLMJudge's `config or self._load_default_config()` fallback therefore never
ran. Privacy validation reported on active.eval while the runtime called someone
else entirely.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from evals.config import JudgeConfig, resolve_judge_config
from evals.judges.llm_judge import LLMJudge
from infrastructure.config.models_config import (
    DataPolicyConfig,
    EmbeddingConfig,
    EvalConfig,
    ExecutionBoundary,
    LLMConfig,
    ModelsConfig,
)

REPO_CONFIG = Path(__file__).parent.parent.parent.parent / "config.yml"


@pytest.fixture
def repo_models_config():
    """The real config.yml, loaded fresh — active.eval is gpt5-2."""
    from infrastructure.config import models_config as mc

    return mc.ModelsConfig.load(REPO_CONFIG)


def _patched(models_config):
    """Patch every get_models_config lookup the judge path reaches."""
    return patch(
        "infrastructure.config.models_config.get_models_config",
        return_value=models_config,
    )


# ── (a) both entry points resolve gpt-5.2, not Anthropic ──────────────────────


def test_cli_constructed_job_resolves_active_eval(repo_models_config):
    import evals.cli as cli

    args = type(
        "Args",
        (),
        {
            "no_judge": False,
            "samples": 1,
            "seed": 42,
            "rag_url": "http://localhost:8001",
            "output": "data/eval_runs",
        },
    )()

    with _patched(repo_models_config):
        judge = cli.resolve_judge_config(enabled=not args.no_judge)

    assert judge.provider == "openai"
    assert judge.model == "gpt-5.2"
    assert judge.enabled is True
    assert "claude" not in judge.model


def test_api_constructed_job_resolves_active_eval(repo_models_config):
    import evals.config as evals_config
    from api import job_manager

    # job_manager builds its EvalConfig with resolve_judge_config(enabled=...);
    # exercise that exact symbol rather than a copy of it.
    assert job_manager.resolve_judge_config is evals_config.resolve_judge_config

    with _patched(repo_models_config):
        config = job_manager.EvalConfig(
            datasets=[job_manager.DatasetName("ragbench")],
            samples_per_dataset=1,
            tier=job_manager.EvalTier("generation"),
            judge=job_manager.resolve_judge_config(enabled=True),
        )

    assert config.judge.provider == "openai"
    assert config.judge.model == "gpt-5.2"


def test_cli_and_api_resolve_identically(repo_models_config):
    from api import job_manager
    import evals.cli as cli

    with _patched(repo_models_config):
        cli_judge = cli.resolve_judge_config(enabled=True)
        api_judge = job_manager.resolve_judge_config(enabled=True)

    assert cli_judge == api_judge


def test_judge_config_has_no_provider_or_model_default():
    """The root cause. If these ever regain defaults, the whole class of bug is back."""
    with pytest.raises(TypeError):
        JudgeConfig()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        JudgeConfig(enabled=True)  # type: ignore[call-arg]


def test_eval_config_default_judge_comes_from_active_eval(repo_models_config):
    from evals.config import EvalConfig as RunEvalConfig

    with _patched(repo_models_config):
        config = RunEvalConfig(samples_per_dataset=1)

    assert (config.judge.provider, config.judge.model) == ("openai", "gpt-5.2")


# ── (b) privacy validation inspects the object the runtime uses ───────────────


def _models_config(boundary, *, eval_dataset_is_public=False, base_url=None, timeout=120):
    return ModelsConfig(
        llm=LLMConfig(provider="openai", model="gpt-5-mini"),
        embedding=EmbeddingConfig(provider="tei", model="Qwen/Qwen3-Embedding-0.6B"),
        eval=EvalConfig(
            provider="openai",
            model="gpt-5.2",
            api_key="test-key",
            base_url=base_url,
            timeout=timeout,
            execution_boundary=boundary,
        ),
        data_policy=DataPolicyConfig(
            corpus_confidential=True, eval_dataset_is_public=eval_dataset_is_public
        ),
    )


def test_resolution_enforces_the_policy_on_the_resolved_judge():
    """Resolution, not just config load, refuses an out-of-boundary judge — so the
    object the runtime calls is the object that was checked."""
    with _patched(_models_config(ExecutionBoundary.THIRD_PARTY)):
        with pytest.raises(ValueError, match="third_party"):
            resolve_judge_config()


def test_resolved_judge_carries_the_boundary_it_was_validated_against():
    with _patched(_models_config(ExecutionBoundary.CUSTOMER_MANAGED)):
        judge = resolve_judge_config()

    assert judge.execution_boundary == "customer_managed"


def test_repo_config_load_and_resolution_agree(repo_models_config):
    """Both paths read the same eval block; neither may say "fine" while the other
    says "refused"."""
    repo_models_config.validate_privacy_posture()
    with _patched(repo_models_config):
        judge = resolve_judge_config()
    assert judge.execution_boundary == repo_models_config.eval.execution_boundary.value


# ── (c) a model definition with no boundary fails closed ──────────────────────


def test_resolution_fails_closed_on_missing_boundary():
    with _patched(_models_config(None)):
        with pytest.raises(ValueError, match="declares no execution_boundary"):
            resolve_judge_config()


def test_missing_boundary_permitted_only_by_explicit_override():
    with _patched(_models_config(None, eval_dataset_is_public=True)):
        judge = resolve_judge_config()
    assert judge.execution_boundary is None


# ── (d) LLMJudge has no fallback ──────────────────────────────────────────────


def test_llm_judge_requires_a_config():
    with pytest.raises(TypeError):
        LLMJudge()  # type: ignore[call-arg]


def test_llm_judge_rejects_an_explicit_none():
    with pytest.raises(ValueError, match="resolved JudgeConfig"):
        LLMJudge(None)  # type: ignore[arg-type]


def test_llm_judge_has_no_default_loader():
    assert not hasattr(LLMJudge, "_load_default_config")


# ── (e) temperature and base_url reach the client config ──────────────────────


def test_create_llm_passes_temperature_base_url_and_timeout():
    models_config = _models_config(
        ExecutionBoundary.CUSTOMER_MANAGED,
        base_url="http://vllm:8000/v1",
        timeout=90,
    )
    with _patched(models_config):
        judge_config = resolve_judge_config()

    assert judge_config.base_url == "http://vllm:8000/v1"
    assert judge_config.temperature == 0.0
    assert judge_config.timeout == 90.0

    captured = {}

    def _capture(llm_config):
        captured["config"] = llm_config
        return object()

    judge = LLMJudge(judge_config)
    with _patched(models_config), patch(
        "infrastructure.llm.factory.create_llm_client", side_effect=_capture
    ):
        judge._create_llm()

    llm_config = captured["config"]
    assert llm_config.model == "gpt-5.2"
    assert llm_config.base_url == "http://vllm:8000/v1"
    assert llm_config.temperature == 0.0
    assert llm_config.timeout == 90.0
    assert llm_config.api_key == "test-key"


def test_base_url_and_temperature_reach_the_client_kwargs():
    """Both halves of the resolved judge identity survive the factory's mapping.

    base_url was already wired (-> api_base); temperature was declared on
    LLMConfig and dropped, so the judge's temperature-0 determinism reached no
    client. Unit D added the mapping entry. tests/test_llm_factory.py covers the
    mapping for every provider; this keeps the judge-resolution path honest.
    """
    from infrastructure.llm.config import LLMConfig as ClientConfig, LLMProvider
    from infrastructure.llm.factory import _PROVIDER_CONFIG

    _, _, mapping = _PROVIDER_CONFIG[LLMProvider.OPENAI]
    assert mapping["base_url"] == "api_base"
    assert "temperature" in mapping

    config = ClientConfig(
        provider=LLMProvider.OPENAI,
        model="gpt-5.2",
        base_url="http://vllm:8000/v1",
        temperature=0.0,
    )
    kwargs = {}
    for field, param in mapping.items():
        value = getattr(config, field, None)
        if value is not None:
            kwargs[param or field] = value

    assert kwargs["api_base"] == "http://vllm:8000/v1"
    assert kwargs["temperature"] == 0.0
