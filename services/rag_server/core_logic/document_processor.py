import os
from pathlib import Path
from typing import List, Dict
from markitdown import MarkItDown

# Supported file extensions
SUPPORTED_EXTENSIONS = {'.txt', '.md', '.pdf', '.docx'}

def process_document(file_path: str) -> str:
    """
    Process a document file and return its text content.
    Supports: txt, md, pdf, docx
    """
    file_path = Path(file_path)
    extension = file_path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")

    # For simple text and markdown, read directly
    if extension in {'.txt', '.md'}:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()

    # For PDF and DOCX, use MarkItDown
    if extension in {'.pdf', '.docx'}:
        md = MarkItDown()
        result = md.convert(str(file_path))
        return result.text_content

    raise ValueError(f"Unsupported file type: {extension}")

def chunk_document(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """
    Split document text into overlapping chunks for embedding.

    Args:
        text: Document text to chunk
        chunk_size: Target size for each chunk (in characters)
        chunk_overlap: Number of characters to overlap between chunks

    Returns:
        List of text chunks
    """
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at sentence boundaries
        if end < len(text):
            # Look for period, question mark, or exclamation point
            for punct in ['. ', '? ', '! ', '\n\n']:
                last_punct = chunk.rfind(punct)
                if last_punct > chunk_size // 2:  # Only if in second half
                    chunk = text[start:start + last_punct + len(punct)]
                    break

        chunks.append(chunk.strip())
        start = max(start + chunk_size - chunk_overlap, start + 1)

    return [c for c in chunks if c]  # Remove empty chunks

def extract_metadata(file_path: str) -> Dict[str, str]:
    """
    Extract metadata from a document file path.

    Returns:
        Dictionary with file_name, file_type, and path
    """
    file_path = Path(file_path)

    return {
        "file_name": file_path.name,
        "file_type": file_path.suffix,
        "path": str(file_path.parent)
    }
