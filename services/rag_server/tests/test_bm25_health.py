"""BM25 failure visibility (docs/suggestions.md #4.5).

A BM25 fault never fails a query — it degrades hybrid search to vector-only.
These tests pin the signal that makes that degradation visible.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _reset_bm25_health():
    from infrastructure.search import bm25_retriever

    bm25_retriever._last_error = None
    bm25_retriever._last_error_at = None
    bm25_retriever._last_success_at = None
    bm25_retriever._failure_count = 0
    yield


def _session(execute_result=None, side_effect=None):
    session = AsyncMock()
    if side_effect is not None:
        session.execute.side_effect = side_effect
    else:
        result_proxy = Mock()
        result_proxy.fetchall.return_value = execute_result or []
        session.execute.return_value = result_proxy
    return session


def test_health_is_unknown_before_any_search():
    from infrastructure.search.bm25_retriever import get_bm25_health

    assert get_bm25_health()["status"] == "unknown"


@pytest.mark.asyncio
async def test_failed_search_returns_empty_and_is_recorded():
    from infrastructure.search.bm25_retriever import PgSearchBM25Retriever, get_bm25_health

    retriever = PgSearchBM25Retriever(similarity_top_k=5)
    results = await retriever._search_bm25(_session(side_effect=RuntimeError("index missing")), "q")

    assert results == []  # caller sees "no keyword matches", not an error
    health = get_bm25_health()
    assert health["status"] == "unhealthy"
    assert health["consecutive_failures"] == 1
    assert "index missing" in health["last_error"]


@pytest.mark.asyncio
async def test_consecutive_failures_accumulate_then_clear_on_success():
    from infrastructure.search.bm25_retriever import PgSearchBM25Retriever, get_bm25_health

    retriever = PgSearchBM25Retriever(similarity_top_k=5)
    for _ in range(3):
        await retriever._search_bm25(_session(side_effect=RuntimeError("boom")), "q")
    assert get_bm25_health()["consecutive_failures"] == 3

    await retriever._search_bm25(_session(), "q")

    health = get_bm25_health()
    assert health["status"] == "healthy"
    assert health["consecutive_failures"] == 0
    assert health["last_error"] is None


@pytest.mark.asyncio
async def test_probe_reports_unavailable_when_index_or_extension_is_broken():
    from infrastructure.search.bm25_retriever import probe_bm25

    probe = await probe_bm25(_session(side_effect=RuntimeError('operator "<@>" does not exist')))

    assert probe["status"] == "unavailable"
    assert "does not exist" in probe["error"]


@pytest.mark.asyncio
async def test_probe_uses_the_live_operator_and_index():
    from infrastructure.search.bm25_retriever import probe_bm25

    session = _session()
    probe = await probe_bm25(session)

    assert probe["status"] == "healthy"
    sql, _params = session.execute.await_args.args
    assert "to_bm25query(:query, 'idx_chunks_bm25')" in str(sql)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "probe,last_search_failed,expected",
    [
        ({"status": "healthy", "error": None}, False, "healthy"),
        ({"status": "healthy", "error": None}, True, "unhealthy"),
        ({"status": "unavailable", "error": "no extension"}, False, "unavailable"),
    ],
)
async def test_check_bm25_combines_probe_and_last_search(probe, last_search_failed, expected):
    """/metrics/system distinguishes "index is broken" from "last query failed"."""
    from contextlib import asynccontextmanager
    from unittest.mock import patch

    from infrastructure.search import bm25_retriever
    from services.metrics import _check_bm25

    if last_search_failed:
        bm25_retriever._record_failure(RuntimeError("boom"))
    else:
        bm25_retriever._record_success()

    @asynccontextmanager
    async def fake_session():
        yield AsyncMock()

    with patch("infrastructure.database.postgres.get_session", fake_session), \
         patch("infrastructure.search.bm25_retriever.probe_bm25", AsyncMock(return_value=probe)):
        assert await _check_bm25() == expected
