from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    is_temporary: bool = False
    include_chunks: bool = False


class ContextPassage(BaseModel):
    text: str
    doc_id: str


class QueryWithContextRequest(BaseModel):
    query: str
    context_passages: list[ContextPassage]
    session_id: str | None = None


class TokenUsage(BaseModel):
    """Token usage statistics for a query."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class StageItem(BaseModel):
    """One ranked chunk emitted by a retrieval stage."""

    chunk_id: str
    doc_id: str
    score: float | None = None
    rank: int


class StageTrace(BaseModel):
    """Timing and ranked output captured for one query-pipeline stage."""

    name: str
    duration_ms: float
    item_count: int
    items: list[StageItem] | None = None
    status: str = "ok"
    error: str | None = None


class SearchRequest(BaseModel):
    """A retrieval-only query that does not create chat state or call an LLM."""

    query: str
    top_k: int = Field(default=10, ge=1)
    stages: list[str] | None = None


class QueryMetrics(BaseModel):
    """Performance metrics for a query."""
    latency_ms: float
    token_usage: TokenUsage | None = None
    stages: list[StageTrace] = Field(default_factory=list)
    time_to_first_token_ms: float | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    session_id: str
    citations: list[dict] | None = None
    metrics: QueryMetrics | None = None
