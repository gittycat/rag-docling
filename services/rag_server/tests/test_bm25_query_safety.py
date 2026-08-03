from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_pgsearch_retriever_uses_to_bm25query_for_raw_user_queries():
    """The live retriever passes raw user text to to_bm25query() as a bound parameter."""
    from infrastructure.search.bm25_retriever import PgSearchBM25Retriever

    query = "what's an LLM"
    retriever = PgSearchBM25Retriever(similarity_top_k=10)

    result_proxy = Mock()
    result_proxy.fetchall.return_value = []

    session = AsyncMock()
    session.execute.return_value = result_proxy

    results = await retriever._search_bm25(session, query)

    assert results == []
    sql, params = session.execute.await_args.args
    sql_str = str(sql)
    assert "to_bm25query(:query, 'idx_chunks_bm25')" in sql_str
    # Query text is never interpolated into the SQL — apostrophes and operators
    # reach pg_textsearch as data, not as syntax.
    assert query not in sql_str
    assert params["query"] == query
    assert params["limit"] == 10
