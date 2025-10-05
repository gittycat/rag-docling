import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))





def test_unsupported_file_type():
    """Raise error for unsupported file types"""
    from core_logic.document_processor import chunk_document_from_file

    with tempfile.NamedTemporaryFile(suffix='.xyz', delete=False) as f:
        temp_path = f.name

    try:
        with pytest.raises(ValueError, match="Unsupported file type"):
            chunk_document_from_file(temp_path)
    finally:
        os.unlink(temp_path)


@patch('core_logic.document_processor.DoclingNodeParser')
@patch('core_logic.document_processor.DoclingReader')
def test_chunk_document_with_txt_file(mock_reader_class, mock_parser_class):
    """Split text file into nodes using DoclingReader + DoclingNodeParser"""
    from core_logic.document_processor import chunk_document_from_file

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        long_text = "This is a sentence. " * 100
        f.write(long_text)
        temp_path = f.name

    try:
        mock_reader = MagicMock()
        mock_doc = MagicMock()
        mock_reader.load_data.return_value = [mock_doc]
        mock_reader_class.return_value = mock_reader

        mock_parser = MagicMock()
        mock_node1 = MagicMock()
        mock_node1.get_content.return_value = "Chunk 1 text"
        mock_node2 = MagicMock()
        mock_node2.get_content.return_value = "Chunk 2 text"
        mock_parser.get_nodes_from_documents.return_value = [mock_node1, mock_node2]
        mock_parser_class.return_value = mock_parser

        results = chunk_document_from_file(temp_path, chunk_size=200)

        assert len(results) == 2
        assert all(hasattr(n, 'get_content') for n in results)
    finally:
        os.unlink(temp_path)


def test_extract_metadata():
    """Extract metadata from document path"""
    from core_logic.document_processor import extract_metadata

    file_path = "/documents/test_folder/my_document.pdf"
    metadata = extract_metadata(file_path)

    assert metadata["file_name"] == "my_document.pdf"
    assert metadata["file_type"] == ".pdf"
    assert "test_folder" in metadata["path"]


@patch('core_logic.document_processor.DoclingNodeParser')
@patch('core_logic.document_processor.DoclingReader')
def test_chunk_document_from_file(mock_reader_class, mock_parser_class):
    """Test efficient file chunking with chunk_document_from_file"""
    from core_logic.document_processor import chunk_document_from_file

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        temp_path = f.name

    try:
        mock_reader = MagicMock()
        mock_doc = MagicMock()
        mock_reader.load_data.return_value = [mock_doc]
        mock_reader_class.return_value = mock_reader

        mock_parser = MagicMock()
        mock_node1 = MagicMock()
        mock_node1.get_content.return_value = "Chunk 1"
        mock_node1.metadata = {"page": 1, "source": "test.pdf"}
        mock_node2 = MagicMock()
        mock_node2.get_content.return_value = "Chunk 2"
        mock_node2.metadata = {"page": 2, "source": "test.pdf"}
        mock_parser.get_nodes_from_documents.return_value = [mock_node1, mock_node2]
        mock_parser_class.return_value = mock_parser

        results = chunk_document_from_file(temp_path, chunk_size=500)

        assert len(results) == 2
        assert results[0].get_content() == "Chunk 1"
        assert results[1].get_content() == "Chunk 2"
        assert 'page' in results[0].metadata
    finally:
        os.unlink(temp_path)
