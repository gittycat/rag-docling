"""Tests that eval.abstention_phrases in config.yml actually drives abstention scoring.

The key used to parse and do nothing — the metrics used a hardcoded list. Wiring it
up is only meaningful if the config is read on hosts without secrets mounted too,
since a silent fallback to a different phrase list silently changes eval scores.
"""

import pytest

from evals.metrics.abstention import (
    DEFAULT_ABSTENTION_PHRASES,
    get_configured_abstention_phrases,
    is_abstention,
    reset_abstention_phrases_cache,
)


@pytest.fixture(autouse=True)
def clear_cache():
    reset_abstention_phrases_cache()
    yield
    reset_abstention_phrases_cache()


class TestPhrasesComeFromConfig:
    def test_phrases_are_read_from_config_not_the_fallback(self):
        # Not merely equal — the fallback must not be what we got back, or the test
        # would pass even when config loading silently failed.
        assert get_configured_abstention_phrases() is not DEFAULT_ABSTENTION_PHRASES

    def test_config_loading_does_not_require_api_keys(self, monkeypatch):
        # No secrets are mounted in CI. Reading an unrelated config key must not
        # depend on the active provider's credentials.
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        assert get_configured_abstention_phrases() is not DEFAULT_ABSTENTION_PHRASES

    def test_editing_the_config_changes_detection(self, monkeypatch):
        # Patched at the source module: abstention imports it inside the function.
        monkeypatch.setattr(
            "infrastructure.config.models_config.load_raw_config",
            lambda: {"eval": {"abstention_phrases": ["banana"]}},
        )
        reset_abstention_phrases_cache()

        assert get_configured_abstention_phrases() == ["banana"]
        assert is_abstention("banana") is True
        assert is_abstention("I don't know") is False


class TestDetectionCoversParaphrases:
    # Substring fragments, not the full sentences the prompt emits — a list of exact
    # sentences would miss every paraphrase and depress abstention scores for a
    # reason that has nothing to do with the model.
    @pytest.mark.parametrize(
        "answer",
        [
            "I don't have enough information to answer this question.",
            "I don't have enough information to answer that.",
            "I cannot answer that based on the provided context.",
            "I can't answer this.",
            "I'm unable to answer given the context.",
            "Not enough information to answer.",
            "Insufficient information to answer.",
            "I don't know.",
            "That is not mentioned in the documents.",
            "No relevant information was found.",
        ],
    )
    def test_refusals_are_detected(self, answer):
        assert is_abstention(answer) is True

    @pytest.mark.parametrize(
        "answer",
        [
            "The capital of France is Paris.",
            "The document states the deadline is 30 June.",
        ],
    )
    def test_real_answers_are_not_abstentions(self, answer):
        assert is_abstention(answer) is False

    def test_empty_answer_is_an_abstention(self):
        assert is_abstention("") is True


class TestCaching:
    def test_phrases_are_resolved_once(self):
        first = get_configured_abstention_phrases()
        second = get_configured_abstention_phrases()

        assert first is second
