"""What /models/info publishes as token rates, and what it refuses to publish.

The rates this endpoint reports are what the eval runner prices a run with, so a
wrong answer here becomes a wrong cost benchmark. The inline table this replaced
returned {"input": 0.0, "output": 0.0} for every model it did not recognise —
including the currently configured one — which made self-hosted inference look
free by construction.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from infrastructure.config.models_config import ExecutionBoundary

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.pricing import RATE_OVERRIDE_ENV, resolve_rates


@pytest.fixture(autouse=True)
def _no_rate_overrides(monkeypatch):
    monkeypatch.delenv(RATE_OVERRIDE_ENV, raising=False)


class TestRateResolution:
    def test_known_model_resolves_from_the_table(self):
        rates = resolve_rates("gpt-5-mini")
        assert rates is not None
        assert (rates.input_per_1m, rates.output_per_1m) == (0.25, 2.00)
        assert rates.source == "table"

    def test_currently_configured_model_is_priced(self):
        # gpt-5-mini was absent from the old inline table and therefore cost $0.
        assert resolve_rates("gpt-5-mini") is not None

    def test_matching_is_case_insensitive(self):
        assert resolve_rates("GPT-4O") == resolve_rates("gpt-4o")

    def test_self_hosted_model_is_unpriced_not_free(self):
        assert resolve_rates("Qwen/Qwen2.5-14B-Instruct") is None
        assert resolve_rates("Qwen/Qwen3-32B-AWQ") is None

    def test_amortized_rate_can_be_injected_without_a_code_change(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV,
            json.dumps({"Qwen/Qwen2.5-14B-Instruct": {"input": 0.31, "output": 0.31}}),
        )
        rates = resolve_rates("Qwen/Qwen2.5-14B-Instruct")
        assert rates is not None
        assert rates.input_per_1m == 0.31
        assert rates.source == "environment"

    def test_hf_repo_id_matches_a_bare_name_override(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV,
            json.dumps({"Qwen2.5-14B-Instruct": {"input": 0.5, "output": 0.5}}),
        )
        assert resolve_rates("Qwen/Qwen2.5-14B-Instruct") is not None

    def test_namespace_wildcard_does_not_match_by_substring(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV, json.dumps({"acme/*": {"input": 1.0, "output": 2.0}})
        )
        assert resolve_rates("acme/anything") is not None
        assert resolve_rates("acme-hosted-model") is None

    def test_malformed_override_is_dropped_rather_than_zeroed(self, monkeypatch):
        monkeypatch.setenv(RATE_OVERRIDE_ENV, json.dumps({"mystery": {"input": 1.0}}))
        assert resolve_rates("mystery") is None

    def test_empty_model_name_is_unpriced(self):
        assert resolve_rates("") is None
        assert resolve_rates(None) is None


def _patched_models_info(
    model: str,
    provider: str,
    boundary: ExecutionBoundary | None = ExecutionBoundary.THIRD_PARTY,
):
    """Call GET /models/info with the active model forced to `model`."""
    from main import app

    models_config = MagicMock()
    models_config.llm.model = model
    models_config.llm.provider = provider
    # Must be set explicitly: a bare MagicMock attribute fails the enum validation
    # on ModelsInfoResponse, which is the point — an undeclared boundary is never
    # silently accepted.
    models_config.llm.execution_boundary = boundary
    models_config.embedding.model = "Qwen/Qwen3-Embedding-0.6B"

    with patch("api.routes.health.get_models_config", return_value=models_config):
        with patch(
            "api.routes.health.get_inference_config",
            return_value={"reranker_enabled": False, "reranker_model": None},
        ):
            response = TestClient(app).get("/models/info")
    assert response.status_code == 200
    return response.json()


class TestModelsInfoEndpoint:
    def test_priced_model_reports_its_rates(self):
        body = _patched_models_info("gpt-5-mini", "openai")

        assert body["cost_per_1m_input_tokens"] == 0.25
        assert body["cost_per_1m_output_tokens"] == 2.00
        assert body["cost_rate_source"] == "table"

    def test_unpriced_model_reports_null_not_zero(self):
        body = _patched_models_info("Qwen/Qwen2.5-14B-Instruct", "vllm")

        assert body["cost_per_1m_input_tokens"] is None
        assert body["cost_per_1m_output_tokens"] is None
        assert body["cost_rate_source"] == "unpriced"

    def test_injected_rate_is_published(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV,
            json.dumps({"Qwen/Qwen2.5-14B-Instruct": {"input": 0.31, "output": 0.62}}),
        )
        body = _patched_models_info("Qwen/Qwen2.5-14B-Instruct", "vllm")

        assert body["cost_per_1m_input_tokens"] == 0.31
        assert body["cost_per_1m_output_tokens"] == 0.62
        assert body["cost_rate_source"] == "environment"

    def test_explicit_zero_is_distinguishable_from_unpriced(self, monkeypatch):
        monkeypatch.setenv(
            RATE_OVERRIDE_ENV,
            json.dumps({"Qwen/Qwen2.5-14B-Instruct": {"input": 0.0, "output": 0.0}}),
        )
        body = _patched_models_info("Qwen/Qwen2.5-14B-Instruct", "vllm")

        assert body["cost_per_1m_input_tokens"] == 0.0
        assert body["cost_rate_source"] == "environment"


class TestModelsInfoExecutionBoundary:
    """`/models/info` reports the declared boundary, not one inferred from the
    provider name. The old `llm_hosting` field computed `"local" if provider ==
    "vllm" else "cloud"`, which had no way to say `aws_managed` and called a
    vendor endpoint behind an OpenAI-compatible transport "local"."""

    def test_declared_boundary_is_reported(self):
        body = _patched_models_info(
            "Qwen/Qwen2.5-14B-Instruct", "vllm", ExecutionBoundary.CUSTOMER_MANAGED
        )

        assert body["llm_execution_boundary"] == "customer_managed"

    def test_aws_managed_is_representable(self):
        body = _patched_models_info(
            "mistral-large-3", "bedrock", ExecutionBoundary.AWS_MANAGED
        )

        assert body["llm_execution_boundary"] == "aws_managed"

    def test_undeclared_boundary_is_null_not_local(self):
        body = _patched_models_info("gpt-5-mini", "openai", None)

        assert body["llm_execution_boundary"] is None

    def test_boundary_is_not_inferred_from_the_provider_string(self):
        # A vllm-transport model declared third_party must report third_party.
        # The replaced code would have called this "local" on the provider name.
        body = _patched_models_info(
            "some-vendor-model", "vllm", ExecutionBoundary.THIRD_PARTY
        )

        assert body["llm_execution_boundary"] == "third_party"
