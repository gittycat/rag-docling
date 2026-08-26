"""Judge/generator provider independence warning.

Distinct from the PII judge gate in `validate_privacy_posture`, which is a
data-egress check. Nothing previously compared the two providers.
"""

from evals.judges.llm_judge import check_judge_independence


def test_same_provider_warns():
    warning = check_judge_independence("openai", "openai")
    assert warning is not None
    assert "openai" in warning


def test_provider_comparison_ignores_case():
    assert check_judge_independence("OpenAI", "openai") is not None


def test_different_providers_do_not_warn():
    assert check_judge_independence("vllm", "openai") is None


def test_missing_provider_does_not_warn():
    # An unknown provider is not evidence of a shared one
    assert check_judge_independence("", "openai") is None
    assert check_judge_independence("openai", "") is None


def test_warning_names_the_setting_to_change():
    warning = check_judge_independence("anthropic", "anthropic")
    assert "active.eval" in warning
