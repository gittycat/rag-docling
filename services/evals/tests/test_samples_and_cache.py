"""Per-question sample sidecar and the response cache."""

import json

import pytest

from evals.cache import CacheConfig, ResponseCache, clear_cache, config_fingerprint
from evals.samples import SAMPLES_SUFFIX, load_samples, samples_path_for, save_samples
from evals.schemas import (
    Citation,
    EvalQuestion,
    EvalResponse,
    GoldPassage,
    QueryMetrics,
    RetrievedChunk,
    StageItem,
    StageTrace,
    TokenUsage,
)


@pytest.fixture
def sample_pair():
    question = EvalQuestion(
        id="q1",
        question="What is X?",
        expected_answer="Y",
        gold_passages=[GoldPassage(doc_id="d1", chunk_id="d1:1", text="X is Y")],
        domain="wiki",
        metadata={"subset": "test"},
    )
    response = EvalResponse(
        question_id="q1",
        answer="Y [1]",
        retrieved_chunks=[
            RetrievedChunk(doc_id="d1", chunk_id="d1:1", text="X is Y", score=0.9, rank=1)
        ],
        citations=[Citation(source_index=1, doc_id="d1", chunk_id="d1:1")],
        metrics=QueryMetrics(
            latency_ms=123.4,
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            time_to_first_token_ms=12.3,
            stages=[
                StageTrace(
                    name="fusion",
                    duration_ms=4.5,
                    item_count=1,
                    items=[StageItem(chunk_id="d1:1", doc_id="d1", score=0.9, rank=1)],
                )
            ],
        ),
    )
    return question, response


class TestSamples:
    def test_round_trip_preserves_review_relevant_fields(self, tmp_path, sample_pair):
        question, response = sample_pair
        run_path = tmp_path / "abc123_20260101_000000.json"

        save_samples(run_path, "abc123", [question], [response])
        loaded_q, loaded_r = load_samples(run_path)

        assert len(loaded_q) == 1
        assert loaded_q[0].id == question.id
        assert loaded_q[0].expected_answer == question.expected_answer
        assert loaded_q[0].gold_passages[0].chunk_id == "d1:1"
        assert loaded_r[0].answer == response.answer
        assert loaded_r[0].citations[0].doc_id == "d1"
        assert loaded_r[0].retrieved_chunks[0].score == 0.9
        assert loaded_r[0].metrics.token_usage.total_tokens == 15
        assert loaded_r[0].metrics.time_to_first_token_ms == 12.3
        assert loaded_r[0].metrics.stages[0].items[0].chunk_id == "d1:1"

    def test_sidecar_sits_next_to_the_run_with_a_distinct_suffix(self, tmp_path):
        run_path = tmp_path / "abc123_20260101_000000.json"
        sidecar = samples_path_for(run_path)

        assert sidecar.parent == run_path.parent
        assert sidecar.name.endswith(SAMPLES_SUFFIX)
        # A run-file glob must be able to tell them apart
        assert sidecar.name != run_path.name

    def test_missing_sidecar_returns_empty_not_an_error(self, tmp_path):
        assert load_samples(tmp_path / "nothing.json") == ([], [])


class TestResponseCache:
    def test_miss_then_hit(self, tmp_path):
        cache = ResponseCache(tmp_path)
        assert cache.get("judge", ["model", "prompt"]) is None

        cache.set("judge", ["model", "prompt"], {"score": 0.8})
        assert cache.get("judge", ["model", "prompt"]) == {"score": 0.8}
        assert cache.stats() == {"hits": 1, "misses": 1}

    def test_different_inputs_do_not_collide(self, tmp_path):
        cache = ResponseCache(tmp_path)
        cache.set("judge", ["model", "prompt a"], {"score": 1.0})

        assert cache.get("judge", ["model", "prompt b"]) is None
        assert cache.get("judge", ["other-model", "prompt a"]) is None

    def test_namespaces_are_isolated(self, tmp_path):
        cache = ResponseCache(tmp_path)
        cache.set("judge", ["k"], "judged")

        assert cache.get("query", ["k"]) is None

    def test_corrupt_entry_degrades_to_a_miss(self, tmp_path):
        cache = ResponseCache(tmp_path)
        cache.set("judge", ["k"], {"score": 0.5})
        entry = next((tmp_path / "judge").glob("*.json"))
        entry.write_text("{not json")

        assert cache.get("judge", ["k"]) is None

    def test_unwritable_directory_does_not_raise(self, tmp_path):
        cache = ResponseCache(tmp_path / "file-not-dir")
        (tmp_path / "file-not-dir").write_text("blocking file")

        cache.set("judge", ["k"], {"score": 0.5})  # must not raise
        assert cache.get("judge", ["k"]) is None

    def test_clear_removes_entries(self, tmp_path):
        cache = ResponseCache(tmp_path)
        cache.set("judge", ["a"], 1)
        cache.set("query", ["b"], 2)

        assert clear_cache(tmp_path) == 2
        assert cache.get("judge", ["a"]) is None


class TestConfigFingerprint:
    def test_same_configuration_hashes_identically(self):
        snapshot = {"llm_model": "m", "retrieval_top_k": 10, "hybrid_search_enabled": True}
        assert config_fingerprint(snapshot) == config_fingerprint(dict(snapshot))

    def test_changing_a_retrieval_setting_changes_the_key(self):
        base = {"llm_model": "m", "retrieval_top_k": 10, "hybrid_search_enabled": True}
        changed = {**base, "retrieval_top_k": 20}
        assert config_fingerprint(base) != config_fingerprint(changed)

    def test_uncaptured_settings_are_distinct_from_captured_ones(self):
        # None means "unknown", and must not hash the same as a real value
        base = {"llm_model": "m", "hybrid_search_enabled": True}
        unknown = {"llm_model": "m", "hybrid_search_enabled": None}
        assert config_fingerprint(base) != config_fingerprint(unknown)


class TestCacheConfig:
    def test_judge_cache_is_on_and_query_cache_is_off_by_default(self):
        # Query caching cannot see the indexed corpus, so it must be opt-in
        config = CacheConfig()
        assert config.judge is True
        assert config.query is False

    def test_disabled_when_neither_cache_is_active(self):
        assert CacheConfig(judge=False, query=False).enabled is False
        assert CacheConfig(judge=True, query=False).enabled is True


class TestJudgeCaching:
    @pytest.mark.asyncio
    async def test_identical_prompt_is_not_paid_for_twice(self, tmp_path):
        from evals.config import JudgeConfig
        from evals.judges.llm_judge import LLMJudge

        calls = []

        class _FakeLLM:
            async def acomplete(self, prompt):
                calls.append(prompt)
                return "SCORE: 0.75\nREASONING: fine"

        cache = ResponseCache(tmp_path)
        judge = LLMJudge(JudgeConfig(provider="openai", model="m"), cache=cache)
        judge._llm = _FakeLLM()

        first = await judge.evaluate_faithfulness(answer="a", context="c")
        second = await judge.evaluate_faithfulness(answer="a", context="c")

        assert len(calls) == 1
        assert first.score == second.score == 0.75
        assert second.metadata["cached"] is True

    @pytest.mark.asyncio
    async def test_different_answers_are_judged_separately(self, tmp_path):
        from evals.config import JudgeConfig
        from evals.judges.llm_judge import LLMJudge

        calls = []

        class _FakeLLM:
            async def acomplete(self, prompt):
                calls.append(prompt)
                return "SCORE: 0.5\nREASONING: ok"

        judge = LLMJudge(JudgeConfig(provider="openai", model="m"), cache=ResponseCache(tmp_path))
        judge._llm = _FakeLLM()

        await judge.evaluate_faithfulness(answer="a", context="c")
        await judge.evaluate_faithfulness(answer="b", context="c")

        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_no_cache_means_every_call_hits_the_model(self, tmp_path):
        from evals.config import JudgeConfig
        from evals.judges.llm_judge import LLMJudge

        calls = []

        class _FakeLLM:
            async def acomplete(self, prompt):
                calls.append(prompt)
                return "SCORE: 0.5\nREASONING: ok"

        judge = LLMJudge(JudgeConfig(provider="openai", model="m"), cache=None)
        judge._llm = _FakeLLM()

        await judge.evaluate_faithfulness(answer="a", context="c")
        await judge.evaluate_faithfulness(answer="a", context="c")

        assert len(calls) == 2
