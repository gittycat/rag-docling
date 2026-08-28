"""
Document processing job for task worker.

Handles async document processing: chunking, embedding, indexing.
Progress tracking via PostgreSQL job_batches/job_tasks tables.
"""
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*validate_default.*")

import asyncio
import functools
import logging
import shutil
import time
from pathlib import Path
from uuid import UUID

from pipelines.ingestion import ingest_document, extract_file_metadata
from infrastructure.database.postgres import get_session
from infrastructure.database import jobs as db_jobs
from infrastructure.database import documents as db_docs
from services import document_service

# Persistent document storage path
DOCUMENT_STORAGE_PATH = Path("/app/documents")

logger = logging.getLogger(__name__)


async def process_document_async(file_path: str, filename: str, batch_id: str, task_id: str) -> dict:
    """
    Process a document: chunk text, metadata, BM25 rows and embedding vectors,
    all written to PostgreSQL.

    Args:
        file_path: Path to temporary file in /tmp/shared
        filename: Original filename
        batch_id: Batch ID for progress tracking
        task_id: Task ID for this specific file

    Returns:
        dict with document_id and chunks count
    """
    task_start = time.time()

    logger.info(f"[TASK {task_id}] ========== Starting document processing: {filename} ==========")

    try:
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise FileNotFoundError(
                f"Temporary upload file not found: {file_path}. "
                "The shared upload volume may have been reset or the file was already cleaned up. "
                "Please re-upload the document."
            )

        # Generate document ID (use task_id for consistency)
        doc_id = task_id
        logger.info(f"[TASK {task_id}] Using document ID: {doc_id}")

        # ingest_document() runs in an executor thread (see below), so this
        # callback fires from that thread — schedule its async DB updates back
        # onto the main event loop thread-safely rather than using
        # asyncio.get_running_loop()/asyncio.run(), neither of which is safe here.
        main_loop = asyncio.get_running_loop()

        def embedding_progress(current: int, total: int):
            async def _update():
                if current == 1:
                    await _set_task_total_chunks(task_id, total)
                await _increment_task_chunk_progress(task_id)

            asyncio.run_coroutine_threadsafe(_update(), main_loop)

        # Extract file metadata for Document record
        metadata = extract_file_metadata(file_path)

        # Reset any partial state from a previous failed retry attempt. Deleting
        # the documents row cascades to its chunks — and therefore to their
        # embeddings, which now live in the same rows — in one statement.
        logger.info(f"[TASK {task_id}] Preparing document record in database...")
        async with get_session() as session:
            await document_service.delete_document(session, UUID(doc_id))
            await db_docs.create_document(
                session,
                file_name=filename,
                file_type=metadata.get("file_type", ""),
                file_path=str(DOCUMENT_STORAGE_PATH / doc_id / filename),
                file_size_bytes=metadata.get("file_size_bytes", 0),
                file_hash=metadata.get("file_hash"),
                metadata=metadata,
                document_id=UUID(doc_id)
            )
        logger.info(f"[TASK {task_id}] Document record prepared successfully")

        # Run ingestion pipeline (creates chunks with document_id foreign key).
        # Offloaded to an executor thread: ingest_document() is synchronous and
        # would otherwise block the event loop (and every other concurrent
        # claim loop — see infrastructure/tasks/task_worker.py) for its full
        # duration. This also lets it safely use asyncio.run() internally for
        # concurrent contextual-retrieval LLM calls.
        logger.info(f"[TASK {task_id}] Running ingestion pipeline...")
        result = await main_loop.run_in_executor(
            None,
            functools.partial(
                ingest_document,
                file_path=file_path,
                document_id=doc_id,
                filename=filename,
                progress_callback=embedding_progress,
            ),
        )

        # Persist chunk text/metadata/embeddings in PostgreSQL — this single write
        # populates the BM25 index, the vector index and document introspection
        chunks_data = result.get("chunks_data", [])
        write_start = time.perf_counter()
        stages = list(result.get("stages", []))
        try:
            if chunks_data:
                logger.info(f"[TASK {task_id}] Storing {len(chunks_data)} chunks in PostgreSQL...")
                async with get_session() as session:
                    await db_docs.add_chunks(session, UUID(doc_id), chunks_data)
                    # Indexing happens as part of this insert (BM25 trigger and
                    # vector index); keep its measurement next to the other
                    # pipeline stages, not in an unstructured worker log line.
                    stages.append({
                        "name": "index",
                        "duration_ms": (time.perf_counter() - write_start) * 1000,
                        "item_count": len(chunks_data),
                        "input_tokens": None,
                        "output_tokens": None,
                        "status": "ok",
                        "error": None,
                    })
                    await db_docs.add_ingestion_stages(session, UUID(doc_id), stages)
            else:
                stages.append({
                    "name": "index", "duration_ms": 0.0, "item_count": 0,
                    "input_tokens": None, "output_tokens": None,
                    "status": "ok", "error": None,
                })
                async with get_session() as session:
                    await db_docs.add_ingestion_stages(session, UUID(doc_id), stages)
        except Exception as e:
            stages.append({
                "name": "index",
                "duration_ms": (time.perf_counter() - write_start) * 1000,
                "item_count": len(chunks_data),
                "input_tokens": None,
                "output_tokens": None,
                "status": "failed",
                "error": str(e),
            })
            raise
        write_duration = time.perf_counter() - write_start

        # Baseline timing summary for this document (parse/embed from the
        # ingestion pipeline, write from the DB round-trip above) — one line so
        # later phases have a per-document cost breakdown to compare against.
        timings = result.get("timings", {})
        logger.info(
            f"[TASK {task_id}] Timing breakdown: "
            f"parse={timings.get('parse_s', 0):.2f}s, "
            f"contextual={timings.get('contextual_s', 0):.2f}s, "
            f"embed={timings.get('embed_s', 0):.2f}s, "
            f"write={write_duration:.2f}s"
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

        # Update progress: completed
        await _complete_task(task_id)

        task_duration = time.time() - task_start
        logger.info(f"[TASK {task_id}] ========== Task completed in {task_duration:.2f}s ==========")

        # Clean up temp file on success
        _cleanup_temp_file(file_path, task_id)

        return result

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"[TASK {task_id}] Error processing {filename}: {str(e)}")
        logger.error(f"[TASK {task_id}] Traceback:\n{error_trace}")

        # Don't clean up temp file on failure — the task may be retried
        raise


async def _set_task_total_chunks(task_id: str, total: int) -> None:
    async with get_session() as session:
        await db_jobs.set_task_total_chunks(session, UUID(task_id), total)


async def _increment_task_chunk_progress(task_id: str) -> None:
    async with get_session() as session:
        await db_jobs.increment_task_chunk_progress(session, UUID(task_id))


async def _complete_task(task_id: str) -> None:
    async with get_session() as session:
        await db_jobs.complete_task(session, UUID(task_id))


async def _fail_task(task_id: str, error_message: str) -> None:
    async with get_session() as session:
        await db_jobs.fail_task(session, UUID(task_id), error_message)


def _cleanup_temp_file(file_path: str, task_id: str):
    """Clean up temporary file after processing."""
    try:
        path = Path(file_path)
        if path.exists():
            path.unlink()
            logger.info(f"[TASK {task_id}] Cleaned up temporary file: {file_path}")
    except Exception as e:
        logger.warning(f"[TASK {task_id}] Could not delete temp file {file_path}: {e}")
