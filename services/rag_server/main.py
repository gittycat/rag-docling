from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from core_logic.rag_pipeline import query_rag
from core_logic.chroma_manager import get_or_create_collection, list_documents, delete_document, add_documents
from core_logic.document_processor import process_document, chunk_document, extract_metadata, SUPPORTED_EXTENSIONS
from typing import List
from pathlib import Path
import tempfile
import uuid

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

class UploadResponse(BaseModel):
    status: str
    uploaded: int
    documents: list[dict]

def process_and_index_document(file_path: str, filename: str) -> dict:
    """
    Process a document file and add it to ChromaDB.
    Returns document info.
    """
    # Process document to text
    text = process_document(file_path)

    # Chunk document
    chunks = chunk_document(text)

    # Extract metadata
    metadata = extract_metadata(file_path)
    metadata["file_name"] = filename  # Use original filename

    # Generate unique IDs for chunks
    doc_id = str(uuid.uuid4())
    chunk_ids = [f"{doc_id}-chunk-{i}" for i in range(len(chunks))]

    # Prepare metadata for each chunk
    metadatas = [
        {**metadata, "chunk_index": i, "document_id": doc_id}
        for i in range(len(chunks))
    ]

    # Add to ChromaDB
    collection = get_or_create_collection()
    add_documents(collection, chunks, metadatas, chunk_ids)

    return {
        "id": doc_id,
        "file_name": filename,
        "chunks": len(chunks),
        "status": "success"
    }

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

@app.post("/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
    """
    Upload and index one or multiple documents.
    Supports txt, md, pdf, docx files.
    Files are processed, chunked, and added to ChromaDB.
    """
    print(f"Upload endpoint called with {len(files)} files")
    for f in files:
        print(f"  - {f.filename} ({f.content_type})")

    uploaded_docs = []
    errors = []

    for file in files:
        try:
            # Check file extension
            file_ext = Path(file.filename).suffix.lower()
            if file_ext not in SUPPORTED_EXTENSIONS:
                errors.append(f"{file.filename}: Unsupported file type")
                continue

            # Save file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name

            # Process and index
            doc_info = process_and_index_document(tmp_path, file.filename)
            uploaded_docs.append(doc_info)

            # Clean up temp file
            Path(tmp_path).unlink()

        except Exception as e:
            import traceback
            print(f"Error processing {file.filename}: {str(e)}")
            print(traceback.format_exc())
            errors.append(f"{file.filename}: {str(e)}")

    if not uploaded_docs and errors:
        error_msg = "; ".join(errors)
        print(f"Upload failed: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    return UploadResponse(
        status="success",
        uploaded=len(uploaded_docs),
        documents=uploaded_docs
    )

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
