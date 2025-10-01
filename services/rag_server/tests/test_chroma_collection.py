import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

@patch('chromadb.HttpClient')
def test_get_or_create_collection(mock_client_class):
    """Get or create ChromaDB collection with embedding function"""
    from core_logic.chroma_manager import get_or_create_collection

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    collection = get_or_create_collection()

    assert collection is not None
    mock_client.get_or_create_collection.assert_called_once()
    # Should be called with name and embedding_function
    call_args = mock_client.get_or_create_collection.call_args
    assert 'name' in call_args.kwargs or len(call_args.args) > 0
    assert 'embedding_function' in call_args.kwargs or len(call_args.args) > 1

@patch('chromadb.HttpClient')
def test_add_documents_to_collection(mock_client_class):
    """Add documents with metadata to ChromaDB collection"""
    from core_logic.chroma_manager import add_documents

    mock_client = MagicMock()
    mock_collection = MagicMock()

    documents = ["Doc 1 content", "Doc 2 content"]
    metadatas = [{"source": "file1.txt"}, {"source": "file2.txt"}]
    ids = ["doc1", "doc2"]

    add_documents(mock_collection, documents, metadatas, ids)

    mock_collection.add.assert_called_once_with(
        documents=documents,
        metadatas=metadatas,
        ids=ids
    )

@patch('chromadb.HttpClient')
def test_query_collection(mock_client_class):
    """Query ChromaDB collection and return results"""
    from core_logic.chroma_manager import query_documents

    mock_collection = MagicMock()

    # Mock query response
    mock_collection.query.return_value = {
        'documents': [['Result 1 text', 'Result 2 text']],
        'metadatas': [[{'source': 'file1.txt'}, {'source': 'file2.txt'}]],
        'distances': [[0.1, 0.3]],
        'ids': [['doc1', 'doc2']]
    }

    results = query_documents(mock_collection, "test query", n_results=2)

    assert results is not None
    assert len(results['documents'][0]) == 2
    assert 'Result 1 text' in results['documents'][0]
    mock_collection.query.assert_called_once_with(
        query_texts=["test query"],
        n_results=2
    )

@patch('chromadb.HttpClient')
def test_delete_document_from_collection(mock_client_class):
    """Delete document from ChromaDB collection by ID"""
    from core_logic.chroma_manager import delete_document

    mock_collection = MagicMock()

    delete_document(mock_collection, "doc1")

    mock_collection.delete.assert_called_once_with(ids=["doc1"])

@patch('chromadb.HttpClient')
def test_list_all_documents(mock_client_class):
    """List all documents in ChromaDB collection"""
    from core_logic.chroma_manager import list_documents

    mock_collection = MagicMock()

    # Mock get response
    mock_collection.get.return_value = {
        'ids': ['doc1', 'doc2', 'doc3'],
        'metadatas': [
            {'source': 'file1.txt', 'file_name': 'file1.txt'},
            {'source': 'file2.txt', 'file_name': 'file2.txt'},
            {'source': 'file3.pdf', 'file_name': 'file3.pdf'}
        ]
    }

    documents = list_documents(mock_collection)

    assert len(documents) == 3
    assert documents[0]['id'] == 'doc1'
    assert documents[0]['file_name'] == 'file1.txt'
    mock_collection.get.assert_called_once()

@patch('chromadb.HttpClient')
def test_collection_uses_embedding_function(mock_client_class):
    """Verify collection is configured with Ollama embedding function"""
    from core_logic.chroma_manager import get_or_create_collection

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    get_or_create_collection()

    # Verify that embedding_function parameter was passed
    call_args = mock_client.get_or_create_collection.call_args
    assert 'embedding_function' in call_args.kwargs
    # The embedding function should be an OllamaEmbeddingFunction
    embedding_fn = call_args.kwargs['embedding_function']
    assert embedding_fn is not None
