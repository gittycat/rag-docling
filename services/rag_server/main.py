from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="RAG Server")

class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    # Placeholder implementation
    return QueryResponse(
        answer="Placeholder response",
        sources=[]
    )
