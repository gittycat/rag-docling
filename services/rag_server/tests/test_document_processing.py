import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_process_text_file():
    """Process plain text file and return content"""
    from core_logic.document_processor import process_document

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This is a test document.\nIt has multiple lines.")
        temp_path = f.name

    try:
        result = process_document(temp_path)
        assert result is not None
        assert "test document" in result.lower()
        assert "multiple lines" in result.lower()
    finally:
        os.unlink(temp_path)

def test_process_markdown_file():
    """Process markdown file and return content"""
    from core_logic.document_processor import process_document

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# Header\n\nThis is **bold** text.")
        temp_path = f.name

    try:
        result = process_document(temp_path)
        assert result is not None
        assert "header" in result.lower()
        assert "bold" in result.lower()
    finally:
        os.unlink(temp_path)

@patch('core_logic.document_processor.MarkItDown')
def test_process_pdf_file(mock_markitdown):
    """Process PDF file using MarkItDown"""
    from core_logic.document_processor import process_document

    # Mock MarkItDown converter
    mock_converter = MagicMock()
    mock_converter.convert.return_value.text_content = "PDF content here"
    mock_markitdown.return_value = mock_converter

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        temp_path = f.name

    try:
        result = process_document(temp_path)
        assert result is not None
        assert "PDF content" in result
        mock_converter.convert.assert_called_once_with(temp_path)
    finally:
        os.unlink(temp_path)

@patch('core_logic.document_processor.MarkItDown')
def test_process_docx_file(mock_markitdown):
    """Process DOCX file using MarkItDown"""
    from core_logic.document_processor import process_document

    # Mock MarkItDown converter
    mock_converter = MagicMock()
    mock_converter.convert.return_value.text_content = "DOCX content here"
    mock_markitdown.return_value = mock_converter

    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as f:
        temp_path = f.name

    try:
        result = process_document(temp_path)
        assert result is not None
        assert "DOCX content" in result
        mock_converter.convert.assert_called_once_with(temp_path)
    finally:
        os.unlink(temp_path)

def test_unsupported_file_type():
    """Raise error for unsupported file types"""
    from core_logic.document_processor import process_document

    with tempfile.NamedTemporaryFile(suffix='.xyz', delete=False) as f:
        temp_path = f.name

    try:
        with pytest.raises(ValueError, match="Unsupported file type"):
            process_document(temp_path)
    finally:
        os.unlink(temp_path)

def test_chunk_document():
    """Split document into chunks for embedding"""
    from core_logic.document_processor import chunk_document

    long_text = "This is a sentence. " * 100  # 100 sentences
    chunks = chunk_document(long_text, chunk_size=200, chunk_overlap=50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 250 for chunk in chunks)  # Some overlap tolerance
    # Check that chunks have overlap
    assert any(chunks[i][-20:] in chunks[i+1] for i in range(len(chunks)-1))

def test_extract_metadata():
    """Extract metadata from document path"""
    from core_logic.document_processor import extract_metadata

    file_path = "/documents/test_folder/my_document.pdf"
    metadata = extract_metadata(file_path)

    assert metadata["file_name"] == "my_document.pdf"
    assert metadata["file_type"] == ".pdf"
    assert "test_folder" in metadata["path"]
