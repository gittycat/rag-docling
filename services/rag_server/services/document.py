from pathlib import Path
from typing import List, Any, Dict
from llama_index.readers.docling import DoclingReader
from llama_index.node_parser.docling import DoclingNodeParser
from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import Document, TextNode
from infrastructure.config.models_config import get_models_config
import logging
import time
import hashlib

logger = logging.getLogger(__name__)


def clean_metadata_for_chroma(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean metadata to only include types compatible with ChromaDB.
    ChromaDB only supports: str, int, float, bool, None
    """
    cleaned = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, dict):
            if 'filename' in value:
                cleaned[f"{key}_filename"] = str(value['filename'])
            if 'mimetype' in value:
                cleaned[f"{key}_mimetype"] = str(value['mimetype'])
        elif isinstance(value, list):
            logger.debug(f"[METADATA] Skipping list metadata field: {key}")
        else:
            logger.debug(f"[METADATA] Converting {key} ({type(value).__name__}) to string")
            cleaned[key] = str(value)

    return cleaned

SUPPORTED_EXTENSIONS = {
    '.txt', '.md', '.pdf', '.docx', '.pptx', '.xlsx',
    '.html', '.htm', '.asciidoc', '.adoc'
}

SIMPLE_TEXT_EXTENSIONS = {'.txt', '.md'}


def get_contextual_retrieval_config():
    """Get contextual retrieval configuration from models config file"""
    config = get_models_config()
    return {
        'enabled': config.retrieval.enable_contextual_retrieval,
    }


def add_contextual_prefix(node: TextNode, document_name: str, document_type: str) -> TextNode:
    """
    Add contextual prefix to chunk using LLM.

    Research (Anthropic 2024): 49% reduction in retrieval failures
    Combined with hybrid search + reranking: 67% reduction

    Args:
        node: TextNode to enhance with context
        document_name: Name of source document
        document_type: File type/extension

    Returns:
        Enhanced TextNode with contextual prefix
    """
    start_time = time.time()
    logger.info(f"[CONTEXTUAL] Starting LLM call for contextual prefix generation")

    from infrastructure.llm.factory import get_llm_client

    chunk_preview = node.get_content()[:400]  # Use first 400 chars for context

    prompt = f"""Document: {document_name} ({document_type})

Chunk content:
{chunk_preview}

Provide a concise 1-2 sentence context for this chunk, explaining what document it's from and what topic it discusses.
Format: "This section from [document/topic] discusses [specific topic/concept]."

Context (1-2 sentences only):"""

    try:
        llm = get_llm_client()
        llm_start = time.time()
        response = llm.complete(prompt)
        llm_duration = time.time() - llm_start

        context = response.text.strip()

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


def chunk_document_from_file(file_path: str, chunk_size: int = 500):
    logger.info(f"[DOCLING] chunk_document_from_file called for: {file_path}")
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()
    logger.info(f"[DOCLING] File extension: {extension}, chunk_size: {chunk_size}")

    # Check file exists before processing
    if not file_path_obj.exists():
        raise FileNotFoundError(f"File does not exist: {file_path}")

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")

    if extension in SIMPLE_TEXT_EXTENSIONS:
        logger.info(f"[DOCLING] Using SimpleDirectoryReader for text file")
        try:
            reader = SimpleDirectoryReader(input_files=[str(file_path)])
            documents = reader.load_data()
            logger.info(f"[DOCLING] SimpleDirectoryReader returned {len(documents)} documents")
        except FileNotFoundError as e:
            # Re-raise with clear error message
            raise FileNotFoundError(f"File not found during processing: {file_path}") from e
        except Exception as e:
            # Catch other reader errors and provide context
            raise ValueError(f"Failed to read file {file_path}: {str(e)}") from e

        if not documents:
            error_msg = f"Could not load document: {file_path}"
            logger.error(f"[DOCLING] {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"[DOCLING] Using SentenceSplitter for chunking")
        splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=50)
        nodes = splitter.get_nodes_from_documents(documents)
        logger.info(f"[DOCLING] SentenceSplitter returned {len(nodes)} nodes")
    else:
        logger.info(f"[DOCLING] Using DoclingReader for complex document")
        reader = DoclingReader(export_type=DoclingReader.ExportType.JSON)

        logger.info(f"[DOCLING] Starting DoclingReader.load_data() - this may take time for large/complex documents")
        read_start = time.time()
        try:
            documents = reader.load_data(file_path=str(file_path))
            read_duration = time.time() - read_start
            logger.info(f"[DOCLING] DoclingReader.load_data() completed in {read_duration:.2f}s - returned {len(documents)} documents")
        except FileNotFoundError as e:
            # Re-raise with clear error message
            raise FileNotFoundError(f"File not found during processing: {file_path}") from e
        except Exception as e:
            # Catch DoclingReader errors (corrupted files, parsing errors, etc.)
            read_duration = time.time() - read_start
            logger.error(f"[DOCLING] DoclingReader failed after {read_duration:.2f}s: {str(e)}")
            raise ValueError(f"Failed to process document {file_path}: {str(e)}") from e

        if not documents:
            error_msg = f"Could not load document: {file_path}"
            logger.error(f"[DOCLING] {error_msg}")
            raise ValueError(error_msg)

        logger.info(f"[DOCLING] Starting DoclingNodeParser.get_nodes_from_documents()")
        parse_start = time.time()
        try:
            node_parser = DoclingNodeParser()
            nodes = node_parser.get_nodes_from_documents(documents)
            parse_duration = time.time() - parse_start
            logger.info(f"[DOCLING] DoclingNodeParser completed in {parse_duration:.2f}s - returned {len(nodes)} nodes")
        except Exception as e:
            parse_duration = time.time() - parse_start
            logger.error(f"[DOCLING] DoclingNodeParser failed after {parse_duration:.2f}s: {str(e)}")
            raise ValueError(f"Failed to parse document into chunks: {str(e)}") from e

        logger.info(f"[DOCLING] Cleaning metadata for ChromaDB compatibility")
        for node in nodes:
            node.metadata = clean_metadata_for_chroma(node.metadata)

    # Add contextual retrieval prefixes if enabled (Anthropic method)
    contextual_config = get_contextual_retrieval_config()
    if contextual_config['enabled'] and nodes:
        logger.info(f"[DOCLING] Starting contextual prefix generation for {len(nodes)} nodes - this involves {len(nodes)} LLM calls")
        contextual_start = time.time()

        for i, node in enumerate(nodes):
            if i % 10 == 0:  # Log progress every 10 chunks
                elapsed = time.time() - contextual_start
                avg_per_node = elapsed / (i + 1) if i > 0 else 0
                est_remaining = avg_per_node * (len(nodes) - i - 1)
                logger.info(f"[DOCLING] Contextual prefix progress: {i+1}/{len(nodes)} - Elapsed: {elapsed:.1f}s, Est. remaining: {est_remaining:.1f}s")
            nodes[i] = add_contextual_prefix(node, file_path_obj.name, extension)

        contextual_duration = time.time() - contextual_start
        avg_per_node = contextual_duration / len(nodes)
        logger.info(f"[DOCLING] Contextual prefixes completed in {contextual_duration:.2f}s (avg: {avg_per_node:.2f}s per node)")
    elif not contextual_config['enabled']:
        logger.info("[DOCLING] Contextual retrieval disabled")

    if nodes:
        first_text = nodes[0].get_content()
        preview = first_text[:80] + "..." if len(first_text) > 80 else first_text
        logger.info(f"[DOCLING] First node preview: {preview}")

    logger.info(f"[DOCLING] Created {len(nodes)} nodes from {file_path_obj.name}")
    return nodes


def compute_file_hash(file_path: str) -> str:
    """
    Compute SHA256 hash of file content.
    Matches LlamaIndex's document hashing approach.

    Args:
        file_path: Path to file

    Returns:
        Hex digest of SHA256 hash
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read file in chunks to handle large files
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def extract_metadata(file_path: str) -> dict[str, str]:
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
