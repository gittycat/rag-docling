from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    session_id: str
