from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from core_logic.rag_pipeline import query_rag

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
    """
    Process a RAG query:
    1. Retrieve relevant documents from ChromaDB
    2. Generate answer using Ollama LLM with context
    3. Return answer with sources
    """
    try:
        result = query_rag(request.query)
        return QueryResponse(
            answer=result['answer'],
            sources=result['sources']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
