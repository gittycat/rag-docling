"""The chat memory caches hold cleartext user messages, so they must stay bounded.

Guards the TTL + LRU eviction in pipelines/inference.py. Temporary sessions matter
most: they have no PostgreSQL copy and no delete hook, so before this the only way
their history left RAM was a process restart.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from infrastructure.config.models_config import ChatMemoryCacheConfig, ChatMemoryConfig
from pipelines import inference


@pytest.fixture(autouse=True)
def clean_caches():
    inference._memory_cache.clear()
    inference._temporary_sessions.clear()
    yield
    inference._memory_cache.clear()
    inference._temporary_sessions.clear()


def _config(max_sessions=500, ttl_seconds=3600):
    return ChatMemoryCacheConfig(max_sessions=max_sessions, ttl_seconds=ttl_seconds)


def _put(cache, cfg, session_id):
    memory = MagicMock(name=f"memory-{session_id}")
    inference._cache_put(cache, cfg, session_id, memory)
    return memory


class TestCacheEviction:
    def test_hit_returns_same_buffer(self):
        cfg = _config()
        memory = _put(inference._temporary_sessions, cfg, "s1")

        assert inference._cache_get(inference._temporary_sessions, cfg, "s1") is memory

    def test_miss_returns_none(self):
        assert inference._cache_get(inference._temporary_sessions, _config(), "nope") is None

    def test_idle_session_expires(self):
        cfg = _config(ttl_seconds=60)
        with patch("pipelines.inference.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            _put(inference._temporary_sessions, cfg, "s1")

            mock_time.monotonic.return_value = 1000.0 + 61
            assert inference._cache_get(inference._temporary_sessions, cfg, "s1") is None
            assert len(inference._temporary_sessions) == 0

    def test_active_session_survives_ttl(self):
        cfg = _config(ttl_seconds=60)
        with patch("pipelines.inference.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            memory = _put(inference._temporary_sessions, cfg, "s1")

            # Touched every 30s — never idle long enough to expire.
            for offset in (30, 60, 90):
                mock_time.monotonic.return_value = 1000.0 + offset
                assert inference._cache_get(inference._temporary_sessions, cfg, "s1") is memory

    def test_expiry_sweeps_other_idle_sessions(self):
        cfg = _config(ttl_seconds=60)
        with patch("pipelines.inference.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            _put(inference._temporary_sessions, cfg, "idle")

            # A different session's lookup still reclaims the idle entry.
            mock_time.monotonic.return_value = 1000.0 + 61
            inference._cache_get(inference._temporary_sessions, cfg, "other")
            assert "idle" not in inference._temporary_sessions

    def test_capacity_cap_evicts_least_recently_used(self):
        cfg = _config(max_sessions=3)
        for session_id in ("a", "b", "c"):
            _put(inference._temporary_sessions, cfg, session_id)

        inference._cache_get(inference._temporary_sessions, cfg, "a")  # "b" is now LRU
        _put(inference._temporary_sessions, cfg, "d")

        assert set(inference._temporary_sessions) == {"a", "c", "d"}

    def test_cap_is_never_exceeded(self):
        # Eviction runs after insert; evicting first would leave the cache one over.
        cfg = _config(max_sessions=2)
        for i in range(10):
            _put(inference._temporary_sessions, cfg, f"s{i}")
            assert len(inference._temporary_sessions) <= 2

    def test_caches_are_independent(self):
        cfg = _config(max_sessions=1)
        _put(inference._memory_cache, cfg, "persistent")
        _put(inference._temporary_sessions, cfg, "temporary")

        assert "persistent" in inference._memory_cache
        assert "temporary" in inference._temporary_sessions


class TestTemporarySessionLifecycle:
    """End-to-end through the public entry points, with the two configs distinct."""

    def _models_config(self, temporary_max=2):
        config = MagicMock()
        config.chat_memory = ChatMemoryConfig(
            persistent=ChatMemoryCacheConfig(),
            temporary=ChatMemoryCacheConfig(max_sessions=temporary_max, ttl_seconds=1800),
        )
        return config

    def test_temporary_session_reused_then_evicted(self):
        with patch("pipelines.inference.get_models_config", return_value=self._models_config()), \
             patch("pipelines.inference._get_token_limit_for_chat_history", return_value=100):
            first = inference.get_or_create_chat_memory("t1", is_temporary=True)
            assert inference.get_or_create_chat_memory("t1", is_temporary=True) is first

            inference.get_or_create_chat_memory("t2", is_temporary=True)
            inference.get_or_create_chat_memory("t3", is_temporary=True)

            # "t1" was the least recently used once the cap of 2 was passed.
            assert set(inference._temporary_sessions) == {"t2", "t3"}

    def test_clear_session_memory_drops_temporary_history(self):
        with patch("pipelines.inference.get_models_config", return_value=self._models_config()), \
             patch("pipelines.inference._get_token_limit_for_chat_history", return_value=100):
            inference.get_or_create_chat_memory("t1", is_temporary=True)

        chat_store = MagicMock()
        chat_store.get_messages.return_value = []
        with patch("pipelines.inference._get_chat_store", return_value=chat_store), \
             patch("pipelines.inference.clear_session_token_mapping"):
            inference.clear_session_memory("t1")

        assert "t1" not in inference._temporary_sessions
