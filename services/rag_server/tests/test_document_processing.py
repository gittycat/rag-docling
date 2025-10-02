import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))

def test_process_text_file():
    """Process plain text file using Docling and return content"""
    from core_logic.document_processor import process_document

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        f.write("This is a test document.\nIt has multiple lines.")
        temp_path = f.name

    try:
        with patch('core_logic.document_processor.DoclingLoader') as mock_loader_class:
            # Mock the loader instance and its load method
            mock_loader = MagicMock()
            mock_doc = MagicMock()
            mock_doc.page_content = "This is a test document.\nIt has multiple lines."
            mock_loader.load.return_value = [mock_doc]
            mock_loader_class.return_value = mock_loader

            result = process_document(temp_path)
            assert result is not None
            assert "test document" in result.lower()
            assert "multiple lines" in result.lower()
    finally:
        os.unlink(temp_path)


def test_process_markdown_file():
    """Process markdown file using Docling and return content"""
    from core_logic.document_processor import process_document

    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# Header\n\nThis is **bold** text.")
        temp_path = f.name

    try:
        with patch('core_logic.document_processor.DoclingLoader') as mock_loader_class:
            mock_loader = MagicMock()
            mock_doc = MagicMock()
            mock_doc.page_content = "# Header\n\nThis is **bold** text."
            mock_loader.load.return_value = [mock_doc]
            mock_loader_class.return_value = mock_loader

            result = process_document(temp_path)
            assert result is not None
            assert "header" in result.lower()
            assert "bold" in result.lower()
    finally:
        os.unlink(temp_path)


@patch('core_logic.document_processor.DoclingLoader')
def test_process_pdf_file(mock_loader_class):
    """Process PDF file using Docling"""
    from core_logic.document_processor import process_document

    # Mock DoclingLoader
    mock_loader = MagicMock()
    mock_doc = MagicMock()
    mock_doc.page_content = "PDF content here"
    mock_loader.load.return_value = [mock_doc]
    mock_loader_class.return_value = mock_loader

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        temp_path = f.name

    try:
        result = process_document(temp_path)
        assert result is not None
        assert "PDF content" in result
        mock_loader_class.assert_called_once()
    finally:
        os.unlink(temp_path)


@patch('core_logic.document_processor.DoclingLoader')
def test_process_docx_file(mock_loader_class):
    """Process DOCX file using Docling"""
    from core_logic.document_processor import process_document

    # Mock DoclingLoader
    mock_loader = MagicMock()
    mock_doc = MagicMock()
    mock_doc.page_content = "DOCX content here"
    mock_loader.load.return_value = [mock_doc]
    mock_loader_class.return_value = mock_loader

    with tempfile.NamedTemporaryFile(suffix='.docx', delete=False) as f:
        temp_path = f.name

    try:
        result = process_document(temp_path)
        assert result is not None
        assert "DOCX content" in result
        mock_loader_class.assert_called_once()
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


@patch('core_logic.document_processor.DoclingLoader')
def test_chunk_document(mock_loader_class):
    """Split document into chunks using HybridChunker"""
    from core_logic.document_processor import chunk_document

    long_text = "This is a sentence. " * 100  # 100 sentences

    # Mock DoclingLoader to return chunked documents
    mock_loader = MagicMock()
    mock_chunks = [
        MagicMock(page_content="Chunk 1 text"),
        MagicMock(page_content="Chunk 2 text"),
        MagicMock(page_content="Chunk 3 text"),
    ]
    mock_loader.load.return_value = mock_chunks
    mock_loader_class.return_value = mock_loader

    chunks = chunk_document(long_text, chunk_size=200, chunk_overlap=50)

    assert len(chunks) >= 1
    assert all(isinstance(chunk, str) for chunk in chunks)
    assert all(chunk for chunk in chunks)  # No empty chunks


def test_extract_metadata():
    """Extract metadata from document path"""
    from core_logic.document_processor import extract_metadata

    file_path = "/documents/test_folder/my_document.pdf"
    metadata = extract_metadata(file_path)

    assert metadata["file_name"] == "my_document.pdf"
    assert metadata["file_type"] == ".pdf"
    assert "test_folder" in metadata["path"]


@patch('core_logic.document_processor.DoclingLoader')
def test_chunk_document_from_file(mock_loader_class):
    """Test efficient file chunking with chunk_document_from_file"""
    from core_logic.document_processor import chunk_document_from_file

    # Mock DoclingLoader to return chunked documents with metadata
    mock_loader = MagicMock()
    mock_chunks = [
        MagicMock(page_content="Chunk 1", metadata={"page": 1, "source": "test.pdf"}),
        MagicMock(page_content="Chunk 2", metadata={"page": 2, "source": "test.pdf"}),
    ]
    mock_loader.load.return_value = mock_chunks
    mock_loader_class.return_value = mock_loader

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        temp_path = f.name

    try:
        results = chunk_document_from_file(temp_path, chunk_size=500)

        assert len(results) == 2
        assert all('text' in r and 'metadata' in r for r in results)
        assert results[0]['text'] == "Chunk 1"
        assert results[1]['text'] == "Chunk 2"
        assert 'page' in results[0]['metadata']
    finally:
        os.unlink(temp_path)


@patch('core_logic.document_processor.DoclingLoader')
def test_process_pptx_file(mock_loader_class):
    """Test that PPTX files are now supported via Docling"""
    from core_logic.document_processor import process_document

    mock_loader = MagicMock()
    mock_doc = MagicMock()
    mock_doc.page_content = "Presentation content"
    mock_loader.load.return_value = [mock_doc]
    mock_loader_class.return_value = mock_loader

    with tempfile.NamedTemporaryFile(suffix='.pptx', delete=False) as f:
        temp_path = f.name

    try:
        result = process_document(temp_path)
        assert result is not None
        assert "Presentation content" in result
    finally:
        os.unlink(temp_path)
