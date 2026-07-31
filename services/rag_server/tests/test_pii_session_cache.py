"""The session token-mapping cache holds cleartext PII, so it must stay bounded.

Guards the TTL + LRU eviction in infrastructure/pii/postprocessor.py. Without it
every name a user ever mentioned stays in RAM for the process lifetime.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from infrastructure.config.models_config import PiiConfig, PiiSessionMappingConfig
from infrastructure.pii import postprocessor


@pytest.fixture(autouse=True)
def clean_cache():
    postprocessor._session_mappings.clear()
    yield
    postprocessor._session_mappings.clear()


def _with_config(max_sessions=500, ttl_seconds=3600):
    config = PiiConfig(
        enabled=True,
        session_mapping=PiiSessionMappingConfig(max_sessions=max_sessions, ttl_seconds=ttl_seconds),
    )
    return patch("infrastructure.pii.postprocessor.get_pii_config", return_value=config)


def test_same_session_returns_same_mapping():
    with _with_config():
        first = postprocessor.get_session_token_mapping("s1")
        assert postprocessor.get_session_token_mapping("s1") is first


def test_idle_session_evicted_after_ttl():
    with _with_config(ttl_seconds=60), patch("infrastructure.pii.postprocessor.time") as mock_time:
        mock_time.monotonic.return_value = 1000.0
        original = postprocessor.get_session_token_mapping("s1")

        mock_time.monotonic.return_value = 1000.0 + 61
        assert postprocessor.get_session_token_mapping("s1") is not original
        assert len(postprocessor._session_mappings) == 1


def test_active_session_survives_ttl():
    with _with_config(ttl_seconds=60), patch("infrastructure.pii.postprocessor.time") as mock_time:
        mock_time.monotonic.return_value = 1000.0
        original = postprocessor.get_session_token_mapping("s1")

        # Touched every 30s — never idle long enough to expire.
        for offset in (30, 60, 90):
            mock_time.monotonic.return_value = 1000.0 + offset
            assert postprocessor.get_session_token_mapping("s1") is original


def test_capacity_cap_evicts_least_recently_used():
    with _with_config(max_sessions=3):
        for session_id in ("a", "b", "c"):
            postprocessor.get_session_token_mapping(session_id)

        postprocessor.get_session_token_mapping("a")  # "b" is now the LRU entry
        postprocessor.get_session_token_mapping("d")

        assert set(postprocessor._session_mappings) == {"a", "c", "d"}


def test_clear_removes_mapping():
    with _with_config():
        postprocessor.get_session_token_mapping("s1")
        postprocessor.clear_session_token_mapping("s1")

        assert "s1" not in postprocessor._session_mappings
        postprocessor.clear_session_token_mapping("s1")  # idempotent
