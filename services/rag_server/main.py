from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from core_logic.rag_pipeline import query_rag
from core_logic.chroma_manager import get_or_create_collection, list_documents, delete_document

app = FastAPI(title="RAG Server")

class QueryRequest(BaseModel):
    query: str

class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]

class DocumentListResponse(BaseModel):
    documents: list[dict]

class DeleteResponse(BaseModel):
    status: str
    message: str

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

@app.get("/documents", response_model=DocumentListResponse)
async def get_documents():
    """
    List all indexed documents in ChromaDB.
    Returns document metadata including id, file_name, file_type, and path.
    """
    try:
        collection = get_or_create_collection()
        documents = list_documents(collection)
        return DocumentListResponse(documents=documents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/documents/{document_id}", response_model=DeleteResponse)
async def delete_document_by_id(document_id: str):
    """
    Delete a document from ChromaDB by its ID.
    """
    try:
        collection = get_or_create_collection()
        delete_document(collection, document_id)
        return DeleteResponse(
            status="success",
            message=f"Document {document_id} deleted successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
