from celery_app import celery_app
from core_logic.document_processor import chunk_document_from_file, extract_metadata
from core_logic.chroma_manager import get_or_create_collection, add_documents
from core_logic.progress_tracker import update_task_progress, set_task_total_chunks, increment_task_chunk_progress
from core_logic.settings import initialize_settings
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

initialize_settings()

@celery_app.task(bind=True, name="tasks.process_document_task")
def process_document_task(self, file_path: str, filename: str, batch_id: str):
    task_id = self.request.id
    logger.info(f"[TASK {task_id}] Starting document processing: {filename}")

    try:
        update_task_progress(batch_id, task_id, "processing", {
            "filename": filename,
            "message": "Chunking document..."
        })

        logger.info(f"[TASK {task_id}] Chunking document: {filename}")
        nodes = chunk_document_from_file(file_path)
        logger.info(f"[TASK {task_id}] Created {len(nodes)} nodes from {filename}")

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

        logger.info(f"[TASK {task_id}] Adding {len(nodes)} nodes to index")
        index = get_or_create_collection()

        def embedding_progress(current: int, total: int):
            increment_task_chunk_progress(batch_id, task_id)
            update_task_progress(batch_id, task_id, "processing", {
                "filename": filename,
                "message": f"Embedding chunk {current}/{total}..."
            })

        add_documents(index, nodes, progress_callback=embedding_progress)
        logger.info(f"[TASK {task_id}] Successfully indexed document {filename} with ID {doc_id}")

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

        logger.info(f"[TASK {task_id}] Task completed successfully")
        return result

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"[TASK {task_id}] Error processing {filename}: {str(e)}")
        logger.error(f"[TASK {task_id}] Traceback:\n{error_trace}")

        update_task_progress(batch_id, task_id, "error", {
            "filename": filename,
            "error": str(e),
            "message": f"Error: {str(e)}"
        })

        raise
    finally:
        try:
            Path(file_path).unlink()
            logger.info(f"[TASK {task_id}] Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.warning(f"[TASK {task_id}] Could not delete temp file {file_path}: {e}")
