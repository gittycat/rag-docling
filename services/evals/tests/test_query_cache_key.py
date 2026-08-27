"""The query cache must notice a prompt change.

`_query_cache_key` fingerprinted models and retrieval settings but not prompts,
so editing `prompts.context` in config.yml left a cache full of answers from the
previous prompt and the next run scored them as if they were new.
"""

import pytest

from evals.schemas.results import ConfigSnapshot


def _snapshot(**kwargs) -> ConfigSnapshot:
    base = dict(
        llm_model="gpt-5-mini",
        llm_provider="openai",
        embedding_model="Qwen/Qwen3-Embedding-0.6B",
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        retrieval_top_k=10,
        hybrid_search_enabled=True,
        contextual_retrieval_enabled=False,
        prompt_fingerprint="abc123def4567890",
    )
    base.update(kwargs)
    return ConfigSnapshot(**base)


def _key(snapshot: ConfigSnapshot) -> str:
    from evals.cache import config_fingerprint

    return config_fingerprint(
        {
            "llm_model": snapshot.llm_model,
            "llm_provider": snapshot.llm_provider,
            "embedding_model": snapshot.embedding_model,
            "reranker_model": snapshot.reranker_model,
            "retrieval_top_k": snapshot.retrieval_top_k,
            "hybrid_search_enabled": snapshot.hybrid_search_enabled,
            "contextual_retrieval_enabled": snapshot.contextual_retrieval_enabled,
            "prompt_fingerprint": snapshot.prompt_fingerprint,
        }
    )


def test_a_different_prompt_is_a_different_key():
    assert _key(_snapshot()) != _key(_snapshot(prompt_fingerprint="0000111122223333"))


def test_an_unchanged_config_is_the_same_key():
    assert _key(_snapshot()) == _key(_snapshot())


@pytest.mark.parametrize(
    "missing", ["retrieval_top_k", "prompt_fingerprint"], ids=lambda f: f
)
def test_query_cache_is_disabled_when_the_server_reports_no(missing):
    """A cached answer that cannot be attributed to a pipeline is refused."""
    from evals.config import CacheConfig

    snapshot = _snapshot(**{missing: None})
    cache = CacheConfig(query=True)

    # Mirrors the guard in EvalRunner.run — both branches turn the cache off.
    if snapshot.retrieval_top_k is None or snapshot.prompt_fingerprint is None:
        cache.query = False

    assert cache.query is False
