from pathlib import Path
from typing import List, Dict
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType
from docling.chunking import HybridChunker
import logging

logger = logging.getLogger(__name__)

# Docling supports many more formats than the previous implementation
SUPPORTED_EXTENSIONS = {
    '.txt', '.md', '.pdf', '.docx', '.pptx', '.xlsx',
    '.html', '.htm', '.asciidoc', '.adoc'
}

# Tokenizer for chunking - use sentence-transformers/all-MiniLM-L6-v2 (compatible with nomic-embed-text)
# This is a HuggingFace model that HybridChunker can download
EMBED_MODEL_TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"

def process_document(file_path: str) -> str:
    """
    Process a document file using Docling and return its text content.
    Supports: txt, md, pdf, docx, pptx, xlsx, html, asciidoc

    Uses DoclingLoader with MARKDOWN export for complete document parsing.
    """
    logger.info(f"[DOCLING] Starting to process document: {file_path}")
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()
    logger.info(f"[DOCLING] File extension: {extension}")

    if extension not in SUPPORTED_EXTENSIONS:
        error_msg = f"Unsupported file type: {extension}"
        logger.error(f"[DOCLING] {error_msg}")
        raise ValueError(error_msg)

    # Use DoclingLoader with MARKDOWN export to get full document text
    logger.info(f"[DOCLING] Initializing DoclingLoader with MARKDOWN export")
    loader = DoclingLoader(
        file_path=str(file_path),
        export_type=ExportType.MARKDOWN
    )

    logger.info(f"[DOCLING] Loading document with DoclingLoader")
    docs = loader.load()
    logger.info(f"[DOCLING] Loaded {len(docs)} document sections")

    if not docs:
        error_msg = f"Could not load document: {file_path}"
        logger.error(f"[DOCLING] {error_msg}")
        raise ValueError(error_msg)

    # Combine all document chunks into single text
    # DoclingLoader may split into multiple docs, so join them
    full_text = "\n\n".join(doc.page_content for doc in docs)
    logger.info(f"[DOCLING] Extracted {len(full_text)} characters of text")

    return full_text


def chunk_document_from_file(file_path: str, chunk_size: int = 500) -> List[Dict]:
    """
    Process and chunk a document file directly using Docling.
    Returns list of dicts with chunk text and metadata.

    This preserves document structure (layout, formatting, tables) by passing
    the original file to Docling, rather than extracting text first.

    Args:
        file_path: Path to document file
        chunk_size: Target token size for each chunk

    Returns:
        List of dicts with 'text' and 'metadata' keys
    """
    logger.info(f"[DOCLING] chunk_document_from_file called for: {file_path}")
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()
    logger.info(f"[DOCLING] File extension: {extension}, chunk_size: {chunk_size}")

    if extension not in SUPPORTED_EXTENSIONS:
        error_msg = f"Unsupported file type: {extension}"
        logger.error(f"[DOCLING] {error_msg}")
        raise ValueError(error_msg)

    # Use DoclingLoader with DOC_CHUNKS for efficient chunking
    logger.info(f"[DOCLING] Initializing DoclingLoader with DOC_CHUNKS export")
    logger.info(f"[DOCLING] HybridChunker settings: tokenizer={EMBED_MODEL_TOKENIZER}, max_tokens={chunk_size}")
    loader = DoclingLoader(
        file_path=str(file_path),
        export_type=ExportType.DOC_CHUNKS,
        chunker=HybridChunker(
            tokenizer=EMBED_MODEL_TOKENIZER,
            max_tokens=chunk_size
        )
    )

    logger.info(f"[DOCLING] Loading and chunking document")
    docs = loader.load()
    logger.info(f"[DOCLING] DoclingLoader returned {len(docs)} chunks")

    # Convert LangChain documents to our format
    chunks = []
    for i, doc in enumerate(docs):
        if doc.page_content.strip():
            chunk_preview = doc.page_content[:80] + "..." if len(doc.page_content) > 80 else doc.page_content
            logger.debug(f"[DOCLING] Chunk {i}: {len(doc.page_content)} chars - {chunk_preview}")
            chunks.append({
                'text': doc.page_content,
                'metadata': doc.metadata
            })

    logger.info(f"[DOCLING] Created {len(chunks)} valid chunks (filtered out empty chunks)")
    return chunks


def extract_metadata(file_path: str) -> Dict[str, str]:
    """
    Extract metadata from a document file path.

    Returns:
        Dictionary with file_name, file_type, and path
    """
    file_path_obj = Path(file_path)

    return {
        "file_name": file_path_obj.name,
        "file_type": file_path_obj.suffix,
        "path": str(file_path_obj.parent)
    }
