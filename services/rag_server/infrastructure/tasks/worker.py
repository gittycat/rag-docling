import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*validate_default.*")

from infrastructure.tasks.celery_app import celery_app
from pipelines.ingestion import ingest_document
from infrastructure.database.chroma import get_or_create_collection
from infrastructure.tasks.progress import update_task_progress, set_task_total_chunks, increment_task_chunk_progress
from core.config import initialize_settings
import logging
from pathlib import Path
import time
import shutil

# Persistent document storage path (shared with main.py via docker volume)
DOCUMENT_STORAGE_PATH = Path("/data/documents")

logger = logging.getLogger(__name__)

@celery_app.task(
    bind=True,
    name="infrastructure.tasks.worker.process_document_task",
    autoretry_for=(Exception,),
    retry_kwargs={'max_retries': 3, 'countdown': 5},
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def process_document_task(self, file_path: str, filename: str, batch_id: str):
    """
    Celery task for asynchronous document processing.

    Delegates to the ingestion pipeline and tracks progress via Redis.
    """
    import uuid

    task_id = self.request.id
    task_start = time.time()
    logger.info(f"[TASK {task_id}] ========== Starting document processing: {filename} ==========")

    try:
        # Generate document ID
        doc_id = str(uuid.uuid4())
        logger.info(f"[TASK {task_id}] Generated document ID: {doc_id}")

        # Update progress
        update_task_progress(batch_id, task_id, "processing", {
            "filename": filename,
            "message": "Processing document..."
        })

        # Get ChromaDB index
        index = get_or_create_collection()

        # Create progress callback for embedding tracking
        def embedding_progress(current: int, total: int):
            increment_task_chunk_progress(batch_id, task_id)
            update_task_progress(batch_id, task_id, "processing", {
                "filename": filename,
                "message": f"Embedding chunk {current}/{total}..."
            })

        # Run ingestion pipeline
        logger.info(f"[TASK {task_id}] Running ingestion pipeline...")
        result = ingest_document(
            file_path=file_path,
            index=index,
            document_id=doc_id,
            filename=filename,
            progress_callback=embedding_progress
        )

        # Store original document for download functionality
        logger.info(f"[TASK {task_id}] Storing original document for downloads...")
        try:
            doc_storage_dir = DOCUMENT_STORAGE_PATH / doc_id
            doc_storage_dir.mkdir(parents=True, exist_ok=True)
            dest_path = doc_storage_dir / filename
            shutil.copy2(file_path, dest_path)
            logger.info(f"[TASK {task_id}] Document stored at {dest_path}")
        except Exception as e:
            logger.warning(f"[TASK {task_id}] Failed to store document for downloads: {e}")
            # Non-critical - indexing succeeded, download won't work

        # Update progress to completed
        update_task_progress(batch_id, task_id, "completed", {
            "filename": filename,
            "document_id": result['document_id'],
            "chunks": result['chunks'],
            "message": "Successfully indexed"
        })

        task_duration = time.time() - task_start
        logger.info(f"[TASK {task_id}] ========== Task completed successfully in {task_duration:.2f}s ==========")
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
        will_retry = self.request.retries < self.max_retries

        if not will_retry:
            try:
                Path(file_path).unlink()
                logger.info(f"[TASK {task_id}] Cleaned up temporary file: {file_path}")
            except Exception as e:
                logger.warning(f"[TASK {task_id}] Could not delete temp file {file_path}: {e}")
        else:
            logger.info(f"[TASK {task_id}] Keeping temp file for retry (attempt {self.request.retries + 1}/{self.max_retries + 1})")
