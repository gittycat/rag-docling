from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from core_logic.rag_pipeline import query_rag
from core_logic.chroma_manager import get_or_create_collection, list_documents, delete_document, add_documents
from core_logic.document_processor import chunk_document_from_file, extract_metadata, SUPPORTED_EXTENSIONS
from core_logic.settings import initialize_settings
from core_logic.progress_tracker import create_batch, get_batch_progress
from tasks import process_document_task
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

class TaskInfo(BaseModel):
    task_id: str
    filename: str

class BatchUploadResponse(BaseModel):
    status: str
    batch_id: str
    tasks: list[TaskInfo]

class BatchProgressResponse(BaseModel):
    batch_id: str
    total: int
    completed: int
    tasks: dict

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
        import traceback
        logger.error(f"[QUERY] Error processing query: {str(e)}")
        logger.error(f"[QUERY] Traceback:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents", response_model=DocumentListResponse)
async def get_documents():
    try:
        index = get_or_create_collection()
        documents = list_documents(index)
        return DocumentListResponse(documents=documents)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload", response_model=BatchUploadResponse)
async def upload_documents(files: List[UploadFile] = File(...)):
    logger.info(f"[UPLOAD] Upload endpoint called with {len(files)} files")
    for f in files:
        logger.info(f"[UPLOAD] File: {f.filename} (Content-Type: {f.content_type})")

    batch_id = str(uuid.uuid4())
    task_infos = []
    errors = []

    for file in files:
        try:
            file_ext = Path(file.filename).suffix.lower()
            logger.info(f"[UPLOAD] Processing {file.filename} with extension: {file_ext}")

            if file_ext not in SUPPORTED_EXTENSIONS:
                error_msg = f"{file.filename}: Unsupported file type {file_ext}"
                logger.warning(f"[UPLOAD] {error_msg}")
                errors.append(error_msg)
                continue

            logger.info(f"[UPLOAD] Saving {file.filename} to temporary file")
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext, dir="/tmp/shared") as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name
            logger.info(f"[UPLOAD] Saved to: {tmp_path}")

            task = process_document_task.apply_async(
                args=[tmp_path, file.filename, batch_id]
            )
            task_infos.append(TaskInfo(task_id=task.id, filename=file.filename))
            logger.info(f"[UPLOAD] Queued task {task.id} for {file.filename}")

        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"[UPLOAD] Error queueing {file.filename}: {str(e)}")
            logger.error(f"[UPLOAD] Traceback:\n{error_trace}")
            errors.append(f"{file.filename}: {str(e)}")

    if not task_infos and errors:
        error_msg = "; ".join(errors)
        logger.error(f"[UPLOAD] Upload failed: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    task_ids = [ti.task_id for ti in task_infos]
    filenames = [ti.filename for ti in task_infos]
    create_batch(batch_id, task_ids, filenames)

    logger.info(f"[UPLOAD] Created batch {batch_id} with {len(task_infos)} tasks")
    return BatchUploadResponse(
        status="queued",
        batch_id=batch_id,
        tasks=task_infos
    )

@app.get("/tasks/{batch_id}/status", response_model=BatchProgressResponse)
async def get_batch_status(batch_id: str):
    try:
        progress = get_batch_progress(batch_id)
        if not progress:
            raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")

        return BatchProgressResponse(
            batch_id=progress["batch_id"],
            total=progress["total"],
            completed=progress["completed"],
            tasks=progress["tasks"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
