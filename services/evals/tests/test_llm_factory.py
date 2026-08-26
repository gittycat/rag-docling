"""The evals LLM factory: provider coverage and what actually reaches the client.

The factory is a translation layer between LLMConfig and a llama-index client
class, and a field it forgets to map is dropped in silence. That is not
hypothetical: `temperature` was declared on LLMConfig, populated by the judge and
never mapped, so the judge's documented temperature-0 determinism reached no
client at all. These tests pin the mapping itself rather than the behaviour of
any one client.
"""

import pytest

from infrastructure.llm.config import LLMConfig, LLMProvider
from infrastructure.llm.factory import _PROVIDER_CONFIG, create_llm_client


def _mapped_kwargs(config: LLMConfig) -> dict:
    """Replay the factory's mapping without importing a client class."""
    _, _, mapping = _PROVIDER_CONFIG[config.provider]
    kwargs = {}
    for field, param in mapping.items():
        value = getattr(config, field, None)
        if value is not None:
            kwargs[param or field] = value
    return kwargs


class TestProviderCoverage:
    def test_every_provider_has_a_mapping(self):
        # An enum value with no factory entry is a config option that raises at
        # the first call instead of at load.
        assert set(_PROVIDER_CONFIG) == set(LLMProvider)

    def test_vllm_is_a_supported_provider(self):
        assert LLMProvider("vllm") is LLMProvider.VLLM

    def test_vllm_uses_the_openai_compatible_client(self):
        module_path, class_name, _ = _PROVIDER_CONFIG[LLMProvider.VLLM]
        assert (module_path, class_name) == ("llama_index.llms.openai_like", "OpenAILike")

    def test_unsupported_provider_raises(self):
        class _Fake:
            provider = "not-a-provider"
            model = "m"

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            create_llm_client(_Fake())


class TestParamMapping:
    @pytest.mark.parametrize("provider", list(LLMProvider))
    def test_temperature_is_forwarded_for_every_provider(self, provider):
        # The gap Unit A documented and could not close: the mapping had no
        # temperature entry, so a configured temperature never left the process.
        _, _, mapping = _PROVIDER_CONFIG[provider]
        assert "temperature" in mapping

    @pytest.mark.parametrize("provider", list(LLMProvider))
    def test_base_url_is_forwarded_for_every_provider(self, provider):
        # Including Anthropic: its client accepts base_url, and a configured value
        # being discarded is the failure mode that made active.eval dead config.
        _, _, mapping = _PROVIDER_CONFIG[provider]
        assert "base_url" in mapping

    @pytest.mark.parametrize(
        "provider,expected_key",
        [
            (LLMProvider.OPENAI, "api_base"),
            (LLMProvider.VLLM, "api_base"),
            (LLMProvider.ANTHROPIC, "base_url"),
        ],
    )
    def test_base_url_maps_to_the_client_s_own_parameter_name(self, provider, expected_key):
        config = LLMConfig(
            provider=provider,
            model="m",
            base_url="http://vllm:8000/v1",
            temperature=0.0,
        )
        assert _mapped_kwargs(config)[expected_key] == "http://vllm:8000/v1"

    def test_temperature_zero_is_not_treated_as_absent(self):
        # The mapping skips None, and 0.0 is falsy — an `if value` check here
        # would drop exactly the value the judge depends on.
        config = LLMConfig(provider=LLMProvider.VLLM, model="m", temperature=0.0)
        assert _mapped_kwargs(config)["temperature"] == 0.0

    def test_unset_temperature_is_omitted_so_the_client_default_wins(self):
        config = LLMConfig(provider=LLMProvider.OPENAI, model="m")
        assert "temperature" not in _mapped_kwargs(config)


class TestVLLMClientConstruction:
    def _client(self, **overrides):
        config = LLMConfig(
            provider=LLMProvider.VLLM,
            model="Qwen/Qwen3-32B-AWQ",
            base_url="http://vllm:8000/v1",
            temperature=0.0,
            timeout=30.0,
            **overrides,
        )
        return create_llm_client(config)

    def test_keyless_endpoint_gets_a_placeholder_key(self):
        # vLLM runs keyless behind the network boundary; the OpenAI client under
        # OpenAILike still refuses an empty api_key.
        client = self._client()
        assert client.api_key == "none"

    def test_configured_key_is_not_overwritten(self):
        client = self._client(api_key="real-key")
        assert client.api_key == "real-key"

    def test_served_models_are_chat_models(self):
        # Left to OpenAILike's own guess this is False for an HF repo id, and the
        # request would go to the legacy /v1/completions route vLLM need not serve.
        assert self._client().is_chat_model is True

    def test_endpoint_and_temperature_reach_the_client(self):
        client = self._client()
        assert client.api_base == "http://vllm:8000/v1"
        assert client.temperature == 0.0
        assert client.model == "Qwen/Qwen3-32B-AWQ"
