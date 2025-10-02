from pathlib import Path
from typing import List, Dict
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType
from docling.chunking import HybridChunker

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
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")

    # Use DoclingLoader with MARKDOWN export to get full document text
    loader = DoclingLoader(
        file_path=str(file_path),
        export_type=ExportType.MARKDOWN
    )

    docs = loader.load()

    if not docs:
        raise ValueError(f"Could not load document: {file_path}")

    # Combine all document chunks into single text
    # DoclingLoader may split into multiple docs, so join them
    full_text = "\n\n".join(doc.page_content for doc in docs)

    return full_text


def chunk_document(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """
    Split document text into overlapping chunks using Docling's HybridChunker.

    HybridChunker provides token-aware chunking with hierarchical document structure,
    which is superior to simple character-based chunking.

    Args:
        text: Document text to chunk
        chunk_size: Target token size for each chunk (default 500 tokens)
        chunk_overlap: Not used with HybridChunker (uses merge_peers strategy instead)

    Returns:
        List of text chunks
    """
    # For direct text chunking, we need to use DoclingLoader with DOC_CHUNKS
    # Save text to temp file and process with DoclingLoader
    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write(text)
        temp_path = f.name

    try:
        # Use DoclingLoader with DOC_CHUNKS and HybridChunker
        loader = DoclingLoader(
            file_path=temp_path,
            export_type=ExportType.DOC_CHUNKS,
            chunker=HybridChunker(
                tokenizer=EMBED_MODEL_TOKENIZER,
                max_tokens=chunk_size
            )
        )

        docs = loader.load()

        # Extract text chunks from LangChain documents
        chunks = [doc.page_content for doc in docs if doc.page_content.strip()]

        return chunks

    finally:
        # Clean up temp file
        Path(temp_path).unlink(missing_ok=True)


def chunk_document_from_file(file_path: str, chunk_size: int = 500) -> List[Dict]:
    """
    Process and chunk a document file directly using Docling.
    Returns list of dicts with chunk text and metadata.

    This is more efficient than process_document() + chunk_document()
    as it uses Docling's native chunking in one pass.

    Args:
        file_path: Path to document file
        chunk_size: Target token size for each chunk

    Returns:
        List of dicts with 'text' and 'metadata' keys
    """
    file_path_obj = Path(file_path)
    extension = file_path_obj.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")

    # Use DoclingLoader with DOC_CHUNKS for efficient chunking
    loader = DoclingLoader(
        file_path=str(file_path),
        export_type=ExportType.DOC_CHUNKS,
        chunker=HybridChunker(
            tokenizer=EMBED_MODEL_TOKENIZER,
            max_tokens=chunk_size
        )
    )

    docs = loader.load()

    # Convert LangChain documents to our format
    chunks = []
    for doc in docs:
        if doc.page_content.strip():
            chunks.append({
                'text': doc.page_content,
                'metadata': doc.metadata
            })

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
