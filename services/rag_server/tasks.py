import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*validate_default.*")

from celery_app import celery_app
from core_logic.document_processor import chunk_document_from_file, extract_metadata
from core_logic.chroma_manager import get_or_create_collection, add_documents
from core_logic.progress_tracker import update_task_progress, set_task_total_chunks, increment_task_chunk_progress
from core_logic.settings import initialize_settings
import logging
from pathlib import Path
import time

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    name="tasks.process_document_task",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 5},
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def process_document_task(self, file_path: str, filename: str, batch_id: str):
    task_id = self.request.id
    task_start = time.time()
    logger.info(f"[TASK {task_id}] ========== Starting document processing: {filename} ==========")

    try:
        update_task_progress(batch_id, task_id, "processing", {
            "filename": filename,
            "message": "Chunking document..."
        })

        logger.info(f"[TASK {task_id}] Phase 1: Document chunking and contextual retrieval")
        chunk_start = time.time()
        nodes = chunk_document_from_file(file_path)
        chunk_duration = time.time() - chunk_start
        logger.info(f"[TASK {task_id}] Phase 1 completed in {chunk_duration:.2f}s - Created {len(nodes)} nodes from {filename}")

        set_task_total_chunks(batch_id, task_id, len(nodes))

        update_task_progress(batch_id, task_id, "processing", {
            "filename": filename,
            "message": f"Created {len(nodes)} chunks, starting embedding..."
        })

        metadata = extract_metadata(file_path)
        metadata["file_name"] = filename
        logger.info(f"[TASK {task_id}] Extracted metadata: {metadata}")

        import uuid
        doc_id = str(uuid.uuid4())
        logger.info(f"[TASK {task_id}] Generated document ID: {doc_id}")

        for i, node in enumerate(nodes):
            node.metadata.update(metadata)
            node.metadata["chunk_index"] = i
            node.metadata["document_id"] = doc_id
            node.id_ = f"{doc_id}-chunk-{i}"

        logger.info(f"[TASK {task_id}] Phase 2: Embedding generation and ChromaDB indexing")
        index = get_or_create_collection()

        def embedding_progress(current: int, total: int):
            increment_task_chunk_progress(batch_id, task_id)
            update_task_progress(batch_id, task_id, "processing", {
                "filename": filename,
                "message": f"Embedding chunk {current}/{total}..."
            })

        embed_start = time.time()
        add_documents(index, nodes, progress_callback=embedding_progress)
        embed_duration = time.time() - embed_start
        logger.info(f"[TASK {task_id}] Phase 2 completed in {embed_duration:.2f}s - Successfully indexed document {filename} with ID {doc_id}")

        # Refresh BM25 retriever after adding documents (for hybrid search)
        logger.info(f"[TASK {task_id}] Phase 3: BM25 index refresh")
        try:
            bm25_start = time.time()
            from core_logic.hybrid_retriever import refresh_bm25_retriever
            refresh_bm25_retriever(index)
            bm25_duration = time.time() - bm25_start
            logger.info(f"[TASK {task_id}] Phase 3 completed in {bm25_duration:.2f}s - BM25 retriever refreshed")
        except Exception as e:
            logger.warning(f"[TASK {task_id}] Failed to refresh BM25 retriever: {e}")
            # Non-critical, continue

        result = {
            "id": doc_id,
            "file_name": filename,
            "chunks": len(nodes),
            "status": "success"
        }

        update_task_progress(batch_id, task_id, "completed", {
            "filename": filename,
            "document_id": doc_id,
            "chunks": len(nodes),
            "message": "Successfully indexed"
        })

        task_duration = time.time() - task_start
        logger.info(f"[TASK {task_id}] ========== Task completed successfully in {task_duration:.2f}s ==========")
        logger.info(f"[TASK {task_id}] Performance summary - Phase 1 (chunking): {chunk_duration:.2f}s, Phase 2 (embedding): {embed_duration:.2f}s, Phase 3 (BM25): {bm25_duration if 'bm25_duration' in locals() else 0:.2f}s, Total: {task_duration:.2f}s")
        return result

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"[TASK {task_id}] Error processing {filename}: {str(e)}")
        logger.error(f"[TASK {task_id}] Traceback:\n{error_trace}")

        # Create user-friendly error message (hide temp file paths)
        user_friendly_error = str(e).replace(file_path, filename)

        update_task_progress(batch_id, task_id, "error", {
            "filename": filename,
            "error": user_friendly_error,
            "message": f"Error: {user_friendly_error}"
        })

        raise
    finally:
        # Only delete file if task won't be retried
        # self.request.retries is current retry count
        # self.max_retries is max allowed retries (3 in our config)
        will_retry = self.request.retries < self.max_retries

        if not will_retry:
            try:
                Path(file_path).unlink()
                logger.info(f"[TASK {task_id}] Cleaned up temporary file: {file_path}")
            except Exception as e:
                logger.warning(f"[TASK {task_id}] Could not delete temp file {file_path}: {e}")
        else:
            logger.info(f"[TASK {task_id}] Keeping temp file for retry (attempt {self.request.retries + 1}/{self.max_retries + 1})")
