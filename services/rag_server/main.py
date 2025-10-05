from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from core_logic.rag_pipeline import query_rag
from core_logic.chroma_manager import get_or_create_collection, list_documents, delete_document, add_documents
from core_logic.document_processor import chunk_document_from_file, extract_metadata, SUPPORTED_EXTENSIONS
from core_logic.settings import initialize_settings
from typing import List
from pathlib import Path
import tempfile
import uuid
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

app = FastAPI(title="RAG Server")

@app.on_event("startup")
async def startup_event():
    initialize_settings()

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
    logger.info(f"[CHUNKING] Calling chunk_document_from_file for {filename}")
    nodes = chunk_document_from_file(file_path)
    logger.info(f"[CHUNKING] Created {len(nodes)} nodes from {filename}")

    if nodes:
        first_text = nodes[0].get_content()
        preview = first_text[:100] + "..." if len(first_text) > 100 else first_text
        logger.info(f"[CHUNKING] First node preview: {preview}")

    metadata = extract_metadata(file_path)
    metadata["file_name"] = filename
    logger.info(f"[METADATA] Extracted metadata: {metadata}")

    doc_id = str(uuid.uuid4())
    logger.info(f"[INDEXING] Generated document ID: {doc_id}")

    for i, node in enumerate(nodes):
        node.metadata.update(metadata)
        node.metadata["chunk_index"] = i
        node.metadata["document_id"] = doc_id
        node.id_ = f"{doc_id}-chunk-{i}"

    logger.info(f"[INDEXING] Adding {len(nodes)} nodes to index")
    index = get_or_create_collection()
    add_documents(index, nodes)
    logger.info(f"[INDEXING] Successfully indexed document {filename} with ID {doc_id}")

    return {
        "id": doc_id,
        "file_name": filename,
        "chunks": len(nodes),
        "status": "success"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
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
    try:
        index = get_or_create_collection()
        documents = list_documents(index)
        return DocumentListResponse(documents=documents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
    logger.info(f"[UPLOAD] Upload endpoint called with {len(files)} files")
    for f in files:
        logger.info(f"[UPLOAD] File: {f.filename} (Content-Type: {f.content_type})")

    uploaded_docs = []
    errors = []

    for file in files:
        try:
            # Check file extension
            file_ext = Path(file.filename).suffix.lower()
            logger.info(f"[UPLOAD] Processing {file.filename} with extension: {file_ext}")

            if file_ext not in SUPPORTED_EXTENSIONS:
                error_msg = f"{file.filename}: Unsupported file type {file_ext}"
                logger.warning(f"[UPLOAD] {error_msg}")
                errors.append(error_msg)
                continue

            # Save file temporarily
            logger.info(f"[UPLOAD] Saving {file.filename} to temporary file")
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name
            logger.info(f"[UPLOAD] Saved to: {tmp_path}")

            # Process and index
            doc_info = process_and_index_document(tmp_path, file.filename)
            uploaded_docs.append(doc_info)

            # Clean up temp file
            Path(tmp_path).unlink()
            logger.info(f"[UPLOAD] Cleaned up temporary file for {file.filename}")

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"[UPLOAD] Error processing {file.filename}: {str(e)}")
            logger.error(f"[UPLOAD] Traceback:\n{error_trace}")
            errors.append(f"{file.filename}: {str(e)}")

    if not uploaded_docs and errors:
        error_msg = "; ".join(errors)
        logger.error(f"[UPLOAD] Upload failed: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    logger.info(f"[UPLOAD] Successfully uploaded {len(uploaded_docs)} documents")
    return UploadResponse(
        status="success",
        uploaded=len(uploaded_docs),
        documents=uploaded_docs
    )

@app.delete("/documents/{document_id}", response_model=DeleteResponse)
async def delete_document_by_id(document_id: str):
    try:
        index = get_or_create_collection()
        delete_document(index, document_id)
        return DeleteResponse(
            status="success",
            message=f"Document {document_id} deleted successfully"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
