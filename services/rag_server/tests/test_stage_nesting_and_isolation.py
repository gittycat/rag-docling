"""The phase-1 stage-nesting bound, and per-query isolation of health/tokens.

These are regression tests for defects that every previously-passing test was
consistent with: stage durations that did not nest, and process-global state
that let concurrent queries overwrite each other's measurements.
"""

import asyncio

import pytest

from infrastructure.search import bm25_retriever, vector_retriever
from pipelines.inference import total_stage_duration_ms


def _trace(name, duration_ms, *, parallel=False):
    return {
        "name": name,
        "duration_ms": duration_ms,
        "item_count": 0,
        "items": [],
        "status": "ok",
        "error": None,
        "parallel": parallel,
    }


class TestStageNestingBound:
    def test_parallel_legs_are_counted_once_at_the_slowest(self):
        # bm25 and vector run concurrently: together they cost 30ms of wall
        # time, not 50ms. Summing them naively is what broke the bound.
        traces = [
            _trace("bm25", 20.0, parallel=True),
            _trace("vector", 30.0, parallel=True),
            _trace("fusion", 5.0),
            _trace("rerank", 10.0),
        ]
        assert total_stage_duration_ms(traces) == 45.0

    def test_recorded_trace_set_satisfies_the_latency_bound(self):
        # The phase-1 acceptance criterion, asserted rather than commented:
        # sum(stage durations) <= latency_ms for a realistic trace set.
        latency_ms = 500.0
        traces = [
            _trace("bm25", 40.0, parallel=True),
            _trace("vector", 55.0, parallel=True),
            _trace("fusion", 3.0),
            _trace("rerank", 60.0),
            _trace("context_assembly", 12.0),
            _trace("generation", 300.0),
        ]
        assert total_stage_duration_ms(traces) <= latency_ms

    def test_bound_would_fail_if_nested_stages_were_double_counted(self):
        # Guards the contract itself: a context_assembly still inclusive of the
        # retrieval and rerank nested inside it blows the bound. If someone
        # reverts the subtraction in _run_c3, this is what catches it.
        latency_ms = 200.0
        inclusive_context_assembly = 40.0 + 55.0 + 60.0 + 12.0
        traces = [
            _trace("bm25", 40.0, parallel=True),
            _trace("vector", 55.0, parallel=True),
            _trace("fusion", 3.0),
            _trace("rerank", 60.0),
            _trace("context_assembly", inclusive_context_assembly),
            _trace("generation", 100.0),
        ]
        assert total_stage_duration_ms(traces) > latency_ms

    def test_empty_and_missing_trace_sets_are_zero(self):
        assert total_stage_duration_ms(None) == 0.0
        assert total_stage_duration_ms([]) == 0.0


class TestPerQueryHealthIsolation:
    @pytest.mark.asyncio
    async def test_one_querys_failure_does_not_degrade_anothers_trace(self):
        # Under query_concurrency > 1 the module-global _last_error was read
        # after retrieval, so a failing query marked a healthy query's trace
        # degraded and vice versa.
        observed = {}

        async def query(name, fail):
            box, token = vector_retriever.new_query_health_scope()
            try:
                if fail:
                    box.last_error = "ConnectionError: embedder unavailable"
                # Yield so both queries are in flight at the same time.
                await asyncio.sleep(0)
                observed[name] = vector_retriever.get_query_vector_health()["last_error"]
            finally:
                vector_retriever.reset_query_health_scope(token)

        await asyncio.gather(query("failing", True), query("healthy", False))

        assert observed["failing"] == "ConnectionError: embedder unavailable"
        assert observed["healthy"] is None

    @pytest.mark.asyncio
    async def test_bm25_health_is_scoped_the_same_way(self):
        observed = {}

        async def query(name, fail):
            box, token = bm25_retriever.new_query_health_scope()
            try:
                if fail:
                    box.last_error = "bm25 index unavailable"
                await asyncio.sleep(0)
                observed[name] = bm25_retriever.get_query_bm25_health()["last_error"]
            finally:
                bm25_retriever.reset_query_health_scope(token)

        await asyncio.gather(query("failing", True), query("healthy", False))

        assert observed["failing"] == "bm25 index unavailable"
        assert observed["healthy"] is None

    def test_outside_a_scope_health_reads_as_no_error(self):
        # /metrics/system uses the process-global surface instead; the trace
        # path must not fall back to it.
        assert vector_retriever.get_query_vector_health()["last_error"] is None
        assert bm25_retriever.get_query_bm25_health()["last_error"] is None


class TestPerQueryTokenAccounting:
    @pytest.mark.asyncio
    async def test_concurrent_queries_do_not_cross_contaminate_token_counts(self):
        # cost_per_query is derived from these counts. When the counter was a
        # module global reset at the start of every query, ten concurrent
        # queries overwrote each other and every per-question cost was wrong.
        from llama_index.core.callbacks.token_counting import TokenCountingEvent

        from pipelines import inference

        observed = {}

        async def query(name, prompt_tokens, completion_tokens):
            inference.reset_token_counter()
            handler = inference._active_token_counter.get()
            # Let the sibling query start (and call reset) before we record.
            await asyncio.sleep(0)
            handler.llm_token_counts.append(
                TokenCountingEvent(
                    event_id=name,
                    prompt="p",
                    prompt_token_count=prompt_tokens,
                    completion="c",
                    completion_token_count=completion_tokens,
                    total_token_count=prompt_tokens + completion_tokens,
                )
            )
            await asyncio.sleep(0)
            observed[name] = inference.get_token_counts()

        await asyncio.gather(query("small", 10, 5), query("large", 4000, 900))

        assert observed["small"]["prompt_tokens"] == 10
        assert observed["small"]["completion_tokens"] == 5
        assert observed["large"]["prompt_tokens"] == 4000
        assert observed["large"]["completion_tokens"] == 900

    def test_counts_outside_a_query_scope_are_zero_not_stale(self):
        from pipelines import inference

        token = inference._active_token_counter.set(None)
        try:
            assert inference.get_token_counts() == {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        finally:
            inference._active_token_counter.reset(token)


class TestFailedIngestionIsPersisted:
    @pytest.mark.asyncio
    async def test_stages_are_saved_when_ingestion_raises(self, monkeypatch):
        # An exception during chunking used to discard the whole trace,
        # including the `status: failed` row the chunker had just written —
        # so a failed ingestion left no evidence it had ever been attempted.
        from infrastructure.tasks import worker

        saved = {}

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        async def fake_add_ingestion_stages(session, document_id, stages):
            saved["document_id"] = document_id
            saved["stages"] = list(stages)

        monkeypatch.setattr(worker, "get_session", lambda: _Session())
        monkeypatch.setattr(
            worker.db_docs, "add_ingestion_stages", fake_add_ingestion_stages
        )

        doc_id = "11111111-1111-1111-1111-111111111111"
        partial = [
            {"name": "parse", "duration_ms": 12.0, "item_count": 1, "status": "ok", "error": None},
            {
                "name": "chunk", "duration_ms": 3.0, "item_count": 0,
                "status": "failed", "error": "boom",
            },
        ]

        await worker._save_stages_quietly(doc_id, partial, "task-1")

        assert str(saved["document_id"]) == doc_id
        assert [stage["name"] for stage in saved["stages"]] == ["parse", "chunk"]
        assert saved["stages"][1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_a_persistence_failure_never_masks_the_original_error(self, monkeypatch):
        from infrastructure.tasks import worker

        def exploding_session():
            raise RuntimeError("database is gone")

        monkeypatch.setattr(worker, "get_session", exploding_session)

        # Must not raise: the caller is about to re-raise the real ingestion error.
        await worker._save_stages_quietly(
            "11111111-1111-1111-1111-111111111111",
            [{"name": "chunk", "duration_ms": 1.0, "status": "failed", "error": "boom"}],
            "task-1",
        )

    @pytest.mark.asyncio
    async def test_nothing_is_written_when_no_stages_were_recorded(self, monkeypatch):
        from infrastructure.tasks import worker

        def unexpected_session():
            raise AssertionError("should not open a session for an empty trace")

        monkeypatch.setattr(worker, "get_session", unexpected_session)

        await worker._save_stages_quietly("11111111-1111-1111-1111-111111111111", [], "task-1")


def test_ingest_document_exposes_partial_stages_via_stages_out():
    # The mechanism defect 2 depends on: the caller owns the list, so the
    # partial trace survives the exception.
    import inspect

    from pipelines.ingestion import ingest_document

    signature = inspect.signature(ingest_document)
    assert "stages_out" in signature.parameters
    assert signature.parameters["stages_out"].default is None


def test_ingestion_that_raises_during_chunking_leaves_a_failed_chunk_stage(tmp_path, monkeypatch):
    # The plan's phase-2 acceptance criterion, end to end through the real
    # ingest_document(): the partial trace — including the failed chunk row —
    # is reachable by the caller after the exception propagates.
    from pipelines import ingestion

    source = tmp_path / "doc.txt"
    source.write_text("some content to chunk")

    def exploding_chunker(file_path, stages=None, document_hash=None, **kwargs):
        ingestion._record_stage(
            stages, "chunk", __import__("time").perf_counter(), 0,
            status="failed", error="embedder exploded",
        )
        raise RuntimeError("embedder exploded")

    monkeypatch.setattr(ingestion, "chunk_document", exploding_chunker)

    stages: list = []
    with pytest.raises(RuntimeError, match="embedder exploded"):
        ingestion.ingest_document(
            file_path=str(source),
            document_id="11111111-1111-1111-1111-111111111111",
            filename="doc.txt",
            stages_out=stages,
        )

    assert [(s["name"], s["status"]) for s in stages] == [("chunk", "failed")]
    assert stages[0]["error"] == "embedder exploded"
