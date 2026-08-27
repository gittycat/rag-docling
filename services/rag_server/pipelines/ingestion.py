"""
Document Ingestion Pipeline

Complete flow for processing documents from upload to indexing:
1. Validate file format and extract metadata
2. Chunk document using Docling (complex) or SentenceSplitter (text)
3. Optionally add contextual prefixes via LLM (Anthropic method)
4. Generate embeddings and attach them to each chunk

The chunk rows, their metadata and their embedding vectors are written to
Postgres in a single `add_chunks` call by the caller; the BM25 index is
maintained automatically by pg_textsearch on that insert.
"""

from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.pii.service import TokenMapping
from datetime import datetime, timezone
import asyncio
import time
import hashlib
import logging

from llama_index.readers.docling import DoclingReader
from llama_index.node_parser.docling import DoclingNodeParser
from llama_index.core import SimpleDirectoryReader, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode, MetadataMode

from infrastructure.config.models_config import get_models_config
from infrastructure.llm.factory import get_llm_client

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Matches TEI's --max-client-batch-size default (32), so a single batch never
# gets rejected by the server-side cap.
INGEST_BATCH_SIZE = 32

SUPPORTED_EXTENSIONS = {
    '.txt', '.md', '.pdf', '.docx', '.pptx', '.xlsx',
    '.html', '.htm', '.asciidoc', '.adoc'
}

SIMPLE_TEXT_EXTENSIONS = {'.txt', '.md'}


def get_ingestion_config() -> Dict[str, bool]:
    """Get ingestion configuration from models config"""
    config = get_models_config()
    return {
        'contextual_retrieval_enabled': config.retrieval.enable_contextual_retrieval,
    }


def get_chunking_config() -> Dict[str, int]:
    """Get chunk size and overlap from models config"""
    config = get_models_config()
    return {
        'chunk_size': config.chunking.chunk_size,
        'chunk_overlap': config.chunking.chunk_overlap,
    }


# Which chunker a file extension routes to. Named rather than inferred at the
# call site so /metrics/retrieval and chunk_document() cannot disagree about
# which path a document took — the Docling path has no size or overlap to report.
def chunker_for_extension(extension: str) -> str:
    return "sentence_splitter" if extension in SIMPLE_TEXT_EXTENSIONS else "docling"


# ============================================================================
# STEP 1: METADATA EXTRACTION
# ============================================================================

def compute_file_hash(file_path: str) -> str:
    """
    Compute SHA256 hash of file content for duplicate detection.
    Matches LlamaIndex's document hashing approach.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def extract_file_metadata(file_path: str) -> Dict[str, Any]:
    """
    Extract basic metadata from file for storage.
    PostgreSQL JSONB supports nested structures, no flattening needed.
    """
    file_path_obj = Path(file_path)
    file_size = file_path_obj.stat().st_size
    file_hash = compute_file_hash(file_path)

    return {
        "file_name": file_path_obj.name,
        "file_type": file_path_obj.suffix,
        "path": str(file_path_obj.parent),
        "file_size_bytes": file_size,
        "file_hash": file_hash
    }


def clean_metadata_for_storage(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean metadata for storage. PostgreSQL JSONB handles most types,
    but we still need to handle non-JSON-serializable types.
    """
    cleaned = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, (str, int, float, bool, dict, list)):
            cleaned[key] = value
        else:
            # Convert other types to string
            logger.debug(f"[METADATA] Converting {key} ({type(value).__name__}) to string")
            cleaned[key] = str(value)

    return cleaned


# ============================================================================
# STEP 2: DOCUMENT CHUNKING
# ============================================================================

def chunk_document_with_docling(file_path: str) -> List[TextNode]:
    """
    Process complex documents (PDF, DOCX, etc.) using Docling.

    Flow:
    - DoclingReader extracts structured content (must use JSON export)
    - DoclingNodeParser creates chunks preserving document structure
    - Metadata is cleaned for storage

    Returns list of TextNode objects ready for embedding.
    """
    logger.info(f"[CHUNKING] Using DoclingReader for complex document: {file_path}")

    # CRITICAL: Must use JSON export for DoclingNodeParser compatibility
    reader = DoclingReader(export_type=DoclingReader.ExportType.JSON)

    # Phase 1: Read document structure
    logger.info(f"[CHUNKING] Phase 1: Reading document with Docling...")
    read_start = time.time()
    try:
        documents = reader.load_data(file_path=str(file_path))
        read_duration = time.time() - read_start
        logger.info(f"[CHUNKING] Phase 1 complete ({read_duration:.2f}s) - {len(documents)} documents extracted")
    except FileNotFoundError as e:
        raise FileNotFoundError(f"File not found during processing: {file_path}") from e
    except Exception as e:
        read_duration = time.time() - read_start
        logger.error(f"[CHUNKING] DoclingReader failed after {read_duration:.2f}s: {str(e)}")
        raise ValueError(f"Failed to process document {file_path}: {str(e)}") from e

    if not documents:
        raise ValueError(f"Could not load document: {file_path}")

    # Phase 2: Parse into chunks
    logger.info(f"[CHUNKING] Phase 2: Parsing into chunks...")
    parse_start = time.time()
    try:
        node_parser = DoclingNodeParser()
        nodes = node_parser.get_nodes_from_documents(documents)
        parse_duration = time.time() - parse_start
        logger.info(f"[CHUNKING] Phase 2 complete ({parse_duration:.2f}s) - {len(nodes)} chunks created")
    except Exception as e:
        parse_duration = time.time() - parse_start
        logger.error(f"[CHUNKING] DoclingNodeParser failed after {parse_duration:.2f}s: {str(e)}")
        raise ValueError(f"Failed to parse document into chunks: {str(e)}") from e

    # Clean metadata for storage
    logger.info(f"[CHUNKING] Cleaning metadata for storage")
    for node in nodes:
        node.metadata = clean_metadata_for_storage(node.metadata)

    return nodes


def chunk_document_with_text_splitter(
    file_path: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> List[TextNode]:
    """
    Process simple text documents using SentenceSplitter.

    Flow:
    - SimpleDirectoryReader loads text file
    - SentenceSplitter creates semantic chunks with overlap

    Returns list of TextNode objects ready for embedding.
    """
    logger.info(f"[CHUNKING] Using SimpleDirectoryReader for text file: {file_path}")

    # Phase 1: Load text file
    logger.info(f"[CHUNKING] Phase 1: Loading text file...")
    try:
        reader = SimpleDirectoryReader(input_files=[str(file_path)])
        documents = reader.load_data()
        logger.info(f"[CHUNKING] Phase 1 complete - {len(documents)} documents loaded")
    except FileNotFoundError as e:
        raise FileNotFoundError(f"File not found during processing: {file_path}") from e
    except Exception as e:
        raise ValueError(f"Failed to read file {file_path}: {str(e)}") from e

    if not documents:
        raise ValueError(f"Could not load document: {file_path}")

    # Phase 2: Split into chunks
    chunking = get_chunking_config()
    chunk_size = chunking['chunk_size'] if chunk_size is None else chunk_size
    chunk_overlap = chunking['chunk_overlap'] if chunk_overlap is None else chunk_overlap
    logger.info(
        f"[CHUNKING] Phase 2: Splitting into chunks "
        f"(chunk_size={chunk_size}, chunk_overlap={chunk_overlap})..."
    )
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    nodes = splitter.get_nodes_from_documents(documents)
    logger.info(f"[CHUNKING] Phase 2 complete - {len(nodes)} chunks created")

    return nodes


def chunk_document(
    file_path: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> List[TextNode]:
    """
    Main chunking dispatcher - routes to appropriate chunking method based on file type.

    Returns list of TextNode objects ready for contextual enrichment and embedding.
    """
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()

    # Validate file exists
    if not file_path_obj.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")

    # Validate file type
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")

    logger.info(f"[CHUNKING] Starting chunking for {file_path_obj.name} (type: {extension})")

    # Route to appropriate chunker
    if extension in SIMPLE_TEXT_EXTENSIONS:
        nodes = chunk_document_with_text_splitter(file_path, chunk_size, chunk_overlap)
    else:
        nodes = chunk_document_with_docling(file_path)

    # Log preview of first chunk
    if nodes:
        first_text = nodes[0].get_content()
        preview = first_text[:80] + "..." if len(first_text) > 80 else first_text
        logger.info(f"[CHUNKING] First chunk preview: {preview}")

    logger.info(f"[CHUNKING] Chunking complete - {len(nodes)} chunks created from {file_path_obj.name}")
    return nodes


# ============================================================================
# STEP 3: CONTEXTUAL RETRIEVAL (OPTIONAL)
# ============================================================================

def _mask_contextual_inputs(
    document_name: str, chunk_preview: str, token_mapping: Optional["TokenMapping"]
) -> tuple[str, str, Optional["TokenMapping"]]:
    """Mask PII in the prompt inputs before they reach the (possibly cloud) LLM.

    Returns (document_name, chunk_preview, mapping); passthrough when PII masking
    is disabled (mapping stays None so unmasking is skipped too).
    """
    from infrastructure.pii.config import get_pii_config
    from infrastructure.pii.service import TokenMapping, mask_text

    if not get_pii_config().enabled:
        return document_name, chunk_preview, None

    mapping = token_mapping if token_mapping is not None else TokenMapping()
    masked_name = mask_text(document_name, existing_mapping=mapping, context_id=document_name).masked_text
    masked_preview = mask_text(chunk_preview, existing_mapping=mapping, context_id=document_name).masked_text
    return masked_name, masked_preview, mapping


def _unmask_contextual_prefix(context: str, token_mapping: Optional["TokenMapping"], document_name: str) -> str:
    """Restore original PII values in the generated prefix (it is stored and embedded locally)."""
    from infrastructure.pii.service import get_pii_service, unmask_text

    if token_mapping is None:
        return context

    recovered = get_pii_service().attempt_fuzzy_recovery(context, token_mapping)
    return unmask_text(recovered, token_mapping, context_id=document_name).unmasked_text


def add_contextual_prefix_to_chunk(
    node: TextNode, document_name: str, document_type: str, token_mapping: Optional["TokenMapping"] = None
) -> TextNode:
    """
    Add LLM-generated contextual prefix to chunk (Anthropic method).

    Research (Anthropic 2024): 49% reduction in retrieval failures
    Combined with hybrid search + reranking: 67% reduction

    Flow:
    - Extract chunk preview (first 400 chars)
    - Send to LLM with prompt for 1-2 sentence context
    - Prepend context to original chunk text
    - Return enhanced node (or original if LLM fails)
    """
    from infrastructure.llm import get_contextual_prefix_prompt

    logger.info(f"[CONTEXTUAL] Generating contextual prefix for chunk via LLM...")
    start_time = time.time()

    chunk_preview = node.get_content()[:400]
    masked_name, masked_preview, pii_mapping = _mask_contextual_inputs(document_name, chunk_preview, token_mapping)
    prompt = get_contextual_prefix_prompt(masked_name, document_type, masked_preview)

    try:
        llm = get_llm_client()
        llm_start = time.time()
        response = llm.complete(prompt)
        llm_duration = time.time() - llm_start

        context = _unmask_contextual_prefix(response.text.strip(), pii_mapping, document_name)

        # Prepend context to original text
        enhanced_text = f"{context}\n\n{node.text}"
        node.text = enhanced_text

        total_duration = time.time() - start_time
        logger.info(f"[CONTEXTUAL] LLM call completed in {llm_duration:.2f}s (total: {total_duration:.2f}s)")
        logger.debug(f"[CONTEXTUAL] Added prefix: {context[:80]}...")
        return node

    except Exception as e:
        duration = time.time() - start_time
        logger.warning(f"[CONTEXTUAL] Failed to generate context after {duration:.2f}s: {e}")
        # Return original node if context generation fails
        return node


async def add_contextual_prefix_to_chunk_async(
    node: TextNode, document_name: str, document_type: str, token_mapping: Optional["TokenMapping"] = None
) -> TextNode:
    """Async variant of add_contextual_prefix_to_chunk, using llm.acomplete()."""
    from infrastructure.llm import get_contextual_prefix_prompt

    logger.info(f"[CONTEXTUAL] Generating contextual prefix for chunk via LLM...")
    start_time = time.time()

    chunk_preview = node.get_content()[:400]
    masked_name, masked_preview, pii_mapping = _mask_contextual_inputs(document_name, chunk_preview, token_mapping)
    prompt = get_contextual_prefix_prompt(masked_name, document_type, masked_preview)

    try:
        llm = get_llm_client()
        llm_start = time.time()
        response = await llm.acomplete(prompt)
        llm_duration = time.time() - llm_start

        context = _unmask_contextual_prefix(response.text.strip(), pii_mapping, document_name)

        # Prepend context to original text
        enhanced_text = f"{context}\n\n{node.text}"
        node.text = enhanced_text

        total_duration = time.time() - start_time
        logger.info(f"[CONTEXTUAL] LLM call completed in {llm_duration:.2f}s (total: {total_duration:.2f}s)")
        logger.debug(f"[CONTEXTUAL] Added prefix: {context[:80]}...")
        return node

    except Exception as e:
        duration = time.time() - start_time
        logger.warning(f"[CONTEXTUAL] Failed to generate context after {duration:.2f}s: {e}")
        # Return original node if context generation fails
        return node


async def _add_contextual_retrieval_async(nodes: List[TextNode], file_path: str, concurrency: int) -> List[TextNode]:
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()
    total = len(nodes)

    sem = asyncio.Semaphore(concurrency)
    contextual_start = time.time()
    completed = 0

    # One mapping per document so the same entity gets the same token in every chunk.
    # mask() runs synchronously between awaits, so concurrent tasks can't interleave mutations.
    from infrastructure.pii.config import get_pii_config
    from infrastructure.pii.service import TokenMapping

    doc_token_mapping = TokenMapping() if get_pii_config().enabled else None

    async def _process(node: TextNode) -> TextNode:
        nonlocal completed
        async with sem:
            result = await add_contextual_prefix_to_chunk_async(
                node, file_path_obj.name, extension, token_mapping=doc_token_mapping
            )
            completed += 1
            if completed % 10 == 0:
                elapsed = time.time() - contextual_start
                avg_per_node = elapsed / completed
                est_remaining = avg_per_node * (total - completed)
                logger.info(f"[CONTEXTUAL] Progress: {completed}/{total} - Elapsed: {elapsed:.1f}s, Est. remaining: {est_remaining:.1f}s")
            return result

    # gather preserves input order in the returned list
    return list(await asyncio.gather(*(_process(node) for node in nodes)))


def add_contextual_retrieval(nodes: List[TextNode], file_path: str) -> List[TextNode]:
    """
    Add contextual prefixes to all chunks using LLM (if enabled).

    Runs LLM calls concurrently (bounded by retrieval.contextual_concurrency) instead
    of sequentially. This is the most time-consuming step when enabled.

    Returns enhanced nodes with contextual prefixes prepended, in original order.
    """
    config = get_ingestion_config()

    if not config['contextual_retrieval_enabled']:
        logger.info("[CONTEXTUAL] Contextual retrieval disabled - skipping")
        return nodes

    if not nodes:
        return nodes

    concurrency = get_models_config().retrieval.contextual_concurrency

    logger.info(f"[CONTEXTUAL] Starting contextual prefix generation for {len(nodes)} chunks (concurrency={concurrency})")

    contextual_start = time.time()
    # Safe: this function only runs inside the task-worker's executor thread
    # (see infrastructure/tasks/worker.py), which has no running event loop.
    enhanced_nodes = asyncio.run(_add_contextual_retrieval_async(nodes, file_path, concurrency))

    contextual_duration = time.time() - contextual_start
    avg_per_node = contextual_duration / len(nodes)
    logger.info(f"[CONTEXTUAL] Contextual prefixes complete ({contextual_duration:.2f}s, avg: {avg_per_node:.2f}s per chunk)")

    return enhanced_nodes


# ============================================================================
# STEP 4: EMBEDDING
# ============================================================================

def add_document_metadata_to_chunks(
    nodes: List[TextNode],
    document_id: str,
    file_metadata: Dict[str, Any],
    uploaded_at: Optional[str] = None
) -> List[TextNode]:
    """
    Add document-level metadata and IDs to all chunks.

    Each chunk gets:
    - All file metadata (name, type, size, hash, path)
    - document_id for tracking and deletion
    - chunk_index for ordering
    - uploaded_at timestamp (ISO 8601 format)
    - Unique node ID: {document_id}-chunk-{index}

    Args:
        uploaded_at: ISO 8601 timestamp representing when document processing
                     completed and the document was ingested into the vector db.
                     If not provided, uses current UTC time.
    """
    if uploaded_at is None:
        uploaded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for i, node in enumerate(nodes):
        node.metadata.update(file_metadata)
        node.metadata["chunk_index"] = i
        node.metadata["document_id"] = document_id
        node.metadata["uploaded_at"] = uploaded_at
        node.id_ = f"{document_id}-chunk-{i}"

    logger.info(f"[METADATA] Added metadata to {len(nodes)} chunks (document_id={document_id}, uploaded_at={uploaded_at})")
    return nodes


def _is_retryable_error(e: Exception) -> tuple[bool, float | None]:
    """Classify an embedding-batch failure as retryable, and pull a Retry-After hint.

    TEI returns HTTP 429 when its internal queue is full and 5xx on transient
    server trouble — both are worth retrying, unlike a 400 (bad request, e.g. a
    chunk that overflows the model's max input length), which will never succeed
    on retry. Non-httpx errors (raw connection failures, timeouts from the
    underlying transport) fall back to the substring check.

    Returns (retryable, retry_after_seconds).
    """
    import httpx

    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status not in (429, 500, 502, 503, 504):
            return False, None
        retry_after = e.response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return True, float(retry_after)
            except ValueError:
                pass
        return True, None

    error_msg = str(e).lower()
    is_connection_error = any(
        term in error_msg for term in ["eof", "connection", "timeout", "refused", "unavailable"]
    )
    return is_connection_error, None


async def _process_batch_with_retry(
    batch: List[TextNode], max_retries: int = 3, base_delay: float = 2.0
) -> None:
    """Embed a batch of nodes with exponential backoff retry on retryable errors."""
    last_error = None

    for attempt in range(max_retries):
        try:
            texts = [node.get_content(metadata_mode=MetadataMode.EMBED) for node in batch]
            embeddings = await Settings.embed_model.aget_text_embedding_batch(texts)
            for node, embedding in zip(batch, embeddings):
                node.embedding = embedding
            return  # Success
        except Exception as e:
            last_error = e
            retryable, retry_after = _is_retryable_error(e)

            if retryable and attempt < max_retries - 1:
                delay = retry_after if retry_after is not None else base_delay * (2 ** attempt)
                logger.warning(f"[EMBEDDING] Retryable error (attempt {attempt + 1}/{max_retries}): {str(e)}")
                logger.info(f"[EMBEDDING] Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
            else:
                # Not retryable or last attempt - raise immediately
                raise

    # All retries failed
    raise Exception(f"Failed to embed batch after {max_retries} attempts. Last error: {str(last_error)}") from last_error


async def _embed_chunks_async(
    nodes: List[TextNode],
    progress_callback: Optional[Callable[[int, int], None]],
    concurrency: int,
) -> None:
    total_nodes = len(nodes)
    batches = [
        (batch_start, nodes[batch_start:batch_start + INGEST_BATCH_SIZE])
        for batch_start in range(0, total_nodes, INGEST_BATCH_SIZE)
    ]
    total_batches = len(batches)

    sem = asyncio.Semaphore(concurrency)
    embedding_start = time.time()
    processed = 0

    async def _process(batch_start: int, batch: List[TextNode]) -> None:
        nonlocal processed
        batch_num = batch_start // INGEST_BATCH_SIZE + 1
        async with sem:
            batch_start_time = time.time()
            try:
                await _process_batch_with_retry(batch, max_retries=3, base_delay=2.0)
            except Exception as e:
                raise Exception(
                    f"Failed to embed batch {batch_num} "
                    f"(chunks {batch_start + 1}-{batch_start + len(batch)}/{total_nodes}): {str(e)}"
                ) from e

            processed += len(batch)
            batch_duration = time.time() - batch_start_time
            elapsed = time.time() - embedding_start
            avg_per_node = elapsed / processed
            est_remaining = avg_per_node * (total_nodes - processed)
            logger.info(
                f"[EMBEDDING] Batch {batch_num}/{total_batches} embedded ({batch_duration:.2f}s) - "
                f"Elapsed: {elapsed:.1f}s, Est. remaining: {est_remaining:.1f}s"
            )
            if progress_callback:
                progress_callback(processed, total_nodes)

    await asyncio.gather(*(_process(batch_start, batch) for batch_start, batch in batches))


def embed_chunks(
    nodes: List[TextNode],
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> None:
    """
    Generate embeddings for chunks in batches, assigning them to node.embedding.

    Batches of INGEST_BATCH_SIZE chunks are embedded concurrently, bounded by
    retrieval.embed_concurrency (mirrors the contextual-retrieval concurrency
    pattern in _add_contextual_retrieval_async), with per-batch retry on
    retryable TEI errors (see _process_batch_with_retry).

    Nothing is persisted here: the embeddings ride along with the chunk rows
    into Postgres in a single add_chunks() write.
    """
    logger.info(f"[EMBEDDING] Starting embedding generation for {len(nodes)} chunks")

    if not nodes:
        return

    first_text = nodes[0].get_content()
    preview = first_text[:100] + "..." if len(first_text) > 100 else first_text
    logger.info(f"[EMBEDDING] First chunk preview: {preview}")

    concurrency = get_models_config().retrieval.embed_concurrency

    embedding_start = time.time()
    # Safe: this function only runs inside the task-worker's executor thread
    # (see infrastructure/tasks/worker.py), which has no running event loop —
    # same guarantee add_contextual_retrieval() relies on for its asyncio.run().
    asyncio.run(_embed_chunks_async(nodes, progress_callback, concurrency))

    total_duration = time.time() - embedding_start
    avg_per_node = total_duration / len(nodes)
    logger.info(f"[EMBEDDING] Embedding complete ({total_duration:.2f}s, avg: {avg_per_node:.2f}s per chunk)")


# ============================================================================
# MAIN INGESTION PIPELINE
# ============================================================================

def ingest_document(
    file_path: str,
    document_id: str,
    filename: str,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Dict[str, Any]:
    """
    Complete document ingestion pipeline.

    Flow:
    1. Extract file metadata (hash, size, type)
    2. Chunk document (Docling or SentenceSplitter)
    3. Add contextual prefixes (optional, LLM-based)
    4. Add document metadata to chunks
    5. Generate embeddings and attach them to each chunk

    Nothing is persisted here. The returned `chunks_data` carries the text,
    metadata and embedding of every chunk; the caller writes all three to
    Postgres in one add_chunks() call, which is also what refreshes the
    pg_textsearch BM25 index and populates the vector index.

    Args:
        file_path: Path to document file
        document_id: Unique document identifier
        filename: Display name for document
        progress_callback: Optional callback for progress tracking (current, total)

    Returns:
        Dictionary with ingestion results:
        {
            'document_id': str,
            'filename': str,
            'chunks': int,
            'status': 'success'
        }
    """
    pipeline_start = time.time()
    logger.info(f"[INGESTION] ========== Starting ingestion pipeline for {filename} ==========")

    # STEP 1: Extract metadata
    logger.info(f"[INGESTION] Step 1: Extracting file metadata...")
    metadata = extract_file_metadata(file_path)
    metadata["file_name"] = filename  # Use provided filename instead of temp file name
    logger.info(f"[INGESTION] Metadata extracted: {metadata}")

    # STEP 2: Chunk document
    logger.info(f"[INGESTION] Step 2: Chunking document...")
    chunk_start = time.time()
    nodes = chunk_document(file_path)
    chunk_duration = time.time() - chunk_start
    logger.info(f"[INGESTION] Step 2 complete ({chunk_duration:.2f}s) - {len(nodes)} chunks created")

    # STEP 3: Add contextual prefixes (optional)
    logger.info(f"[INGESTION] Step 3: Adding contextual retrieval prefixes...")
    contextual_start = time.time()
    nodes = add_contextual_retrieval(nodes, file_path)
    contextual_duration = time.time() - contextual_start
    logger.info(f"[INGESTION] Step 3 complete ({contextual_duration:.2f}s)")

    # STEP 4: Add document metadata
    logger.info(f"[INGESTION] Step 4: Adding document metadata to chunks...")
    nodes = add_document_metadata_to_chunks(nodes, document_id, metadata)
    logger.info(f"[INGESTION] Step 4 complete")

    # Flatten metadata to scalars. Postgres JSONB would happily take nested
    # structures — this is kept only because changing the shape of persisted
    # chunk metadata is out of scope here, and downstream consumers (retrievers,
    # eval tooling, the dashboard) currently assume flat scalar values.
    for node in nodes:
        node.metadata = {
            k: v for k, v in node.metadata.items()
            if isinstance(v, (str, int, float, bool)) or v is None
        }

    # STEP 5: Embed
    logger.info(f"[INGESTION] Step 5: Generating embeddings...")
    embed_start = time.time()
    embed_chunks(nodes, progress_callback)
    embed_duration = time.time() - embed_start
    logger.info(f"[INGESTION] Step 5 complete ({embed_duration:.2f}s)")

    # Summary
    pipeline_duration = time.time() - pipeline_start
    logger.info(f"[INGESTION] ========== Ingestion pipeline complete ({pipeline_duration:.2f}s) ==========")
    logger.info(f"[INGESTION] Performance breakdown:")
    logger.info(f"[INGESTION]   - Chunking: {chunk_duration:.2f}s ({chunk_duration/pipeline_duration*100:.1f}%)")
    logger.info(f"[INGESTION]   - Contextual: {contextual_duration:.2f}s ({contextual_duration/pipeline_duration*100:.1f}%)")
    logger.info(f"[INGESTION]   - Embedding: {embed_duration:.2f}s ({embed_duration/pipeline_duration*100:.1f}%)")
    logger.info(f"[INGESTION]   - Total: {pipeline_duration:.2f}s")

    # Build chunk data for PostgreSQL storage
    chunks_data = []
    for i, node in enumerate(nodes):
        # node text already carries the contextual prefix when contextual
        # retrieval is enabled (add_contextual_prefix_to_chunk prepends it),
        # so `content` is the same text that was embedded and BM25-indexed.
        chunks_data.append({
            "chunk_index": i,
            "content": node.get_content(),
            "metadata": dict(node.metadata),
            "embedding": node.embedding,
        })

    return {
        'document_id': document_id,
        'filename': filename,
        'chunks': len(nodes),
        'chunks_data': chunks_data,
        'status': 'success',
        # Baseline timings for the parse/embed/write breakdown the caller logs
        # once the DB write (outside this pipeline — see infrastructure/tasks/
        # worker.py) completes.
        'timings': {
            'parse_s': chunk_duration,
            'contextual_s': contextual_duration,
            'embed_s': embed_duration,
        },
    }


# ============================================================================
# BACKWARD COMPATIBILITY ALIASES (for tests)
# ============================================================================

# Alias old function names to new ones for backward compatibility
chunk_document_from_file = chunk_document
extract_metadata = extract_file_metadata
get_contextual_retrieval_config = get_ingestion_config
