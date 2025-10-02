import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

@patch('core_logic.chroma_manager.Chroma')
@patch('chromadb.HttpClient')
def test_get_or_create_collection(mock_client_class, mock_chroma_class):
    """Get or create Chroma vectorstore with embedding function"""
    from core_logic.chroma_manager import get_or_create_collection

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_vectorstore = MagicMock()
    mock_chroma_class.return_value = mock_vectorstore

    collection = get_or_create_collection()

    assert collection is not None
    # Verify Chroma was called with correct parameters
    mock_chroma_class.assert_called_once()
    call_kwargs = mock_chroma_class.call_args.kwargs
    assert 'client' in call_kwargs
    assert 'collection_name' in call_kwargs
    assert 'embedding_function' in call_kwargs


def test_add_documents_to_collection():
    """Add documents with metadata to Chroma vectorstore using add_texts"""
    from core_logic.chroma_manager import add_documents

    mock_collection = MagicMock()

    documents = ["Doc 1 content", "Doc 2 content"]
    metadatas = [{"source": "file1.txt"}, {"source": "file2.txt"}]
    ids = ["doc1", "doc2"]

    add_documents(mock_collection, documents, metadatas, ids)

    # LangChain Chroma uses add_texts method
    mock_collection.add_texts.assert_called_once_with(
        texts=documents,
        metadatas=metadatas,
        ids=ids
    )


def test_query_collection():
    """Query Chroma vectorstore and return results in ChromaDB-compatible format"""
    from core_logic.chroma_manager import query_documents

    mock_collection = MagicMock()

    # Mock LangChain similarity_search_with_score response
    mock_doc1 = MagicMock()
    mock_doc1.page_content = "Result 1 text"
    mock_doc1.metadata = {"source": "file1.txt", "id": "doc1"}

    mock_doc2 = MagicMock()
    mock_doc2.page_content = "Result 2 text"
    mock_doc2.metadata = {"source": "file2.txt", "id": "doc2"}

    mock_collection.similarity_search_with_score.return_value = [
        (mock_doc1, 0.9),
        (mock_doc2, 0.7)
    ]

    results = query_documents(mock_collection, "test query", n_results=2)

    assert results is not None
    assert len(results['documents'][0]) == 2
    assert 'Result 1 text' in results['documents'][0]
    assert 'Result 2 text' in results['documents'][0]
    mock_collection.similarity_search_with_score.assert_called_once()


def test_delete_document_from_collection():
    """Delete document chunks from collection by document_id"""
    from core_logic.chroma_manager import delete_document

    # Mock the vectorstore and underlying collection
    mock_collection = MagicMock()
    mock_chroma_collection = MagicMock()
    mock_collection._collection = mock_chroma_collection

    # Mock get response with chunks for the document
    mock_chroma_collection.get.return_value = {
        'ids': ['doc1-chunk-0', 'doc1-chunk-1', 'doc1-chunk-2']
    }

    delete_document(mock_collection, "doc1")

    # Should query for document_id
    mock_chroma_collection.get.assert_called_once_with(where={"document_id": "doc1"})
    # Should delete the chunk IDs
    mock_chroma_collection.delete.assert_called_once_with(
        ids=['doc1-chunk-0', 'doc1-chunk-1', 'doc1-chunk-2']
    )


def test_list_all_documents():
    """List all documents in collection grouped by document_id"""
    from core_logic.chroma_manager import list_documents

    # Mock the vectorstore and underlying collection
    mock_collection = MagicMock()
    mock_chroma_collection = MagicMock()
    mock_collection._collection = mock_chroma_collection

    # Mock get response with chunks from multiple documents
    mock_chroma_collection.get.return_value = {
        'ids': ['doc1-chunk-0', 'doc1-chunk-1', 'doc2-chunk-0'],
        'metadatas': [
            {'document_id': 'doc1', 'file_name': 'file1.txt', 'file_type': '.txt', 'path': '/docs'},
            {'document_id': 'doc1', 'file_name': 'file1.txt', 'file_type': '.txt', 'path': '/docs'},
            {'document_id': 'doc2', 'file_name': 'file2.pdf', 'file_type': '.pdf', 'path': '/docs'}
        ]
    }

    documents = list_documents(mock_collection)

    assert len(documents) == 2
    # Find doc1 and doc2
    doc1 = next(d for d in documents if d['id'] == 'doc1')
    doc2 = next(d for d in documents if d['id'] == 'doc2')

    assert doc1['file_name'] == 'file1.txt'
    assert doc1['chunks'] == 2
    assert doc2['file_name'] == 'file2.pdf'
    assert doc2['chunks'] == 1
    mock_chroma_collection.get.assert_called_once()


@patch('core_logic.chroma_manager.Chroma')
@patch('chromadb.HttpClient')
@patch('core_logic.chroma_manager.get_embedding_function')
def test_collection_uses_embedding_function(mock_embed_fn, mock_client_class, mock_chroma_class):
    """Verify vectorstore is configured with LangChain Ollama embedding function"""
    from core_logic.chroma_manager import get_or_create_collection

    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    mock_embedding = MagicMock()
    mock_embed_fn.return_value = mock_embedding

    mock_vectorstore = MagicMock()
    mock_chroma_class.return_value = mock_vectorstore

    get_or_create_collection()

    # Verify embedding function was retrieved
    mock_embed_fn.assert_called_once()

    # Verify Chroma was called with the embedding function
    call_kwargs = mock_chroma_class.call_args.kwargs
    assert call_kwargs['embedding_function'] == mock_embedding
