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


@patch('core_logic.document_processor.get_contextual_retrieval_config')
@patch('core_logic.document_processor.SentenceSplitter')
@patch('core_logic.document_processor.SimpleDirectoryReader')
def test_chunk_document_with_txt_file(mock_reader_class, mock_splitter_class, mock_contextual_config):
    """Split text file into nodes using SimpleDirectoryReader + SentenceSplitter for txt files"""
    from core_logic.document_processor import chunk_document_from_file

    # Disable contextual retrieval for this test
    mock_contextual_config.return_value = {'enabled': False}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        long_text = "This is a sentence. " * 100
        f.write(long_text)
        temp_path = f.name

    try:
        mock_reader = MagicMock()
        mock_doc = MagicMock()
        mock_reader.load_data.return_value = [mock_doc]
        mock_reader_class.return_value = mock_reader

        mock_splitter = MagicMock()
        mock_node1 = MagicMock()
        mock_node1.get_content.return_value = "Chunk 1 text"
        mock_node2 = MagicMock()
        mock_node2.get_content.return_value = "Chunk 2 text"
        mock_splitter.get_nodes_from_documents.return_value = [mock_node1, mock_node2]
        mock_splitter_class.return_value = mock_splitter

        results = chunk_document_from_file(temp_path, chunk_size=200)

        assert len(results) == 2
        assert all(hasattr(n, 'get_content') for n in results)
    finally:
        os.unlink(temp_path)


def test_extract_metadata():
    """Extract metadata from document path"""
    from core_logic.document_processor import extract_metadata

    # Create a real temp file so stat() works
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(b"test content")
        temp_path = f.name

    try:
        metadata = extract_metadata(temp_path)

        assert metadata["file_name"].endswith(".pdf")
        assert metadata["file_type"] == ".pdf"
        assert "file_size_bytes" in metadata
        assert metadata["file_size_bytes"] > 0
    finally:
        os.unlink(temp_path)


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
