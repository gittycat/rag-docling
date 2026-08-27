"""Tests that a saved run records the config that actually produced it.

Retrieval settings used to be hardcoded into every snapshot (top_k=10, hybrid off,
contextual off), so every stored run misreported the three most commonly tuned
settings and any comparison between runs was comparing constants.
"""

import pytest
from conftest import stub_judge

from evals.config import EvalConfig


@pytest.fixture
def runner():
    from evals.runner import EvaluationRunner

    return EvaluationRunner(EvalConfig(judge=stub_judge()))


# Shape of the /metrics/retrieval response, trimmed to the fields the snapshot reads
RETRIEVAL_RESPONSE = {
    "retrieval_top_k": 25,
    "final_top_n": 12,
    "hybrid_search": {
        "enabled": True,
        "rrf_k": 60,
        "vector": {
            "chunk_size": 321,
            "chunk_overlap": 21,
            "chunkers": [
                {"name": "sentence_splitter", "chunk_size": 321, "chunk_overlap": 21},
                {"name": "docling", "chunk_size": None, "chunk_overlap": None},
            ],
        },
    },
    "contextual_retrieval": {"enabled": True},
    "reranker": {"enabled": True, "model": "cross-encoder/ms-marco-MiniLM-L-6-v2", "top_n": 12},
}

MODELS_RESPONSE = {
    "llm_model": "gpt-5-mini",
    "llm_provider": "openai",
    "embedding_model": "nomic-embed-text:latest",
    "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
}


class TestConfigSnapshot:
    def test_retrieval_settings_come_from_the_server(self, runner):
        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, RETRIEVAL_RESPONSE)

        assert snapshot.retrieval_top_k == 25
        assert snapshot.hybrid_search_enabled is True
        assert snapshot.contextual_retrieval_enabled is True

    def test_chunking_comes_from_the_server_not_a_literal(self, runner):
        """The values were hardcoded 500/50 in the server's own report, so every
        saved run claimed a chunk size it had not measured."""
        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, RETRIEVAL_RESPONSE)

        assert snapshot.chunk_size == 321
        assert snapshot.chunk_overlap == 21
        assert snapshot.chunker == "sentence_splitter+docling"

    def test_chunking_is_unknown_when_the_server_does_not_report_it(self, runner):
        """An older server that predates the chunkers field records None, which is
        the truth, rather than 500/50, which would be a guess that happens to match."""
        response = {**RETRIEVAL_RESPONSE, "hybrid_search": {"enabled": True, "rrf_k": 60}}

        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, response)

        assert snapshot.chunk_size is None
        assert snapshot.chunk_overlap is None
        assert snapshot.chunker is None

    def test_model_settings_still_come_from_models_info(self, runner):
        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, RETRIEVAL_RESPONSE)

        assert snapshot.llm_model == "gpt-5-mini"
        assert snapshot.llm_provider == "openai"
        assert snapshot.embedding_model == "nomic-embed-text:latest"
        assert snapshot.reranker_model == "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def test_disabled_features_are_recorded_as_disabled_not_missing(self, runner):
        response = {
            **RETRIEVAL_RESPONSE,
            "hybrid_search": {"enabled": False, "rrf_k": 60},
            "contextual_retrieval": {"enabled": False},
        }

        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, response)

        assert snapshot.hybrid_search_enabled is False
        assert snapshot.contextual_retrieval_enabled is False

    def test_unavailable_retrieval_config_is_unknown_not_a_default(self, runner):
        # The old bug: absent data silently became top_k=10 / hybrid off, which is
        # indistinguishable from a real measurement once written to disk.
        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, {})

        assert snapshot.retrieval_top_k is None
        assert snapshot.hybrid_search_enabled is None
        assert snapshot.contextual_retrieval_enabled is None

    def test_retrieval_config_defaults_to_unknown_when_omitted(self, runner):
        snapshot = runner._create_config_snapshot(MODELS_RESPONSE)

        assert snapshot.retrieval_top_k is None

    def test_full_retrieval_response_is_kept_for_later_comparison(self, runner):
        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, RETRIEVAL_RESPONSE)

        assert snapshot.additional["retrieval"]["reranker"]["top_n"] == 12
        assert snapshot.additional["retrieval"]["hybrid_search"]["rrf_k"] == 60
        assert snapshot.additional["llm_model"] == "gpt-5-mini"


class TestConfigSnapshotPersistence:
    def _run_with(self, snapshot):
        from datetime import datetime
        from evals.schemas import EvalRun

        return EvalRun(
            id="run1",
            name="test-run",
            created_at=datetime.now(),
            config=snapshot,
        )

    def test_saved_run_carries_the_real_values(self, runner):
        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, RETRIEVAL_RESPONSE)

        config = runner._run_to_dict(self._run_with(snapshot))["config"]

        assert config["retrieval_top_k"] == 25
        assert config["hybrid_search_enabled"] is True
        assert config["contextual_retrieval_enabled"] is True
        assert config["additional"]["retrieval"]["final_top_n"] == 12

    def test_unknown_values_serialize_as_null(self, runner):
        import json

        snapshot = runner._create_config_snapshot(MODELS_RESPONSE, {})

        config = json.loads(json.dumps(runner._run_to_dict(self._run_with(snapshot)), default=str))["config"]

        assert config["retrieval_top_k"] is None
        assert config["hybrid_search_enabled"] is None


class TestReportRendering:
    def test_unknown_renders_as_unknown_not_disabled(self):
        from evals.export import _toggle_label

        assert _toggle_label(None) == "Unknown"
        assert _toggle_label(True) == "Enabled"
        assert _toggle_label(False) == "Disabled"
