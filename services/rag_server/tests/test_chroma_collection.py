import pytest
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

@patch('core_logic.chroma_manager.VectorStoreIndex')
@patch('chromadb.HttpClient')
def test_get_or_create_collection(mock_client_class, mock_index_class):
    """Get or create VectorStoreIndex with ChromaDB"""
    from core_logic.chroma_manager import get_or_create_collection

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_client_class.return_value = mock_client

    mock_index = MagicMock()
    mock_index_class.from_vector_store.return_value = mock_index

    index = get_or_create_collection()

    assert index is not None
    mock_index_class.from_vector_store.assert_called_once()


def test_add_documents_to_collection():
    """Add nodes to VectorStoreIndex"""
    from core_logic.chroma_manager import add_documents

    mock_index = MagicMock()

    mock_node1 = MagicMock()
    mock_node2 = MagicMock()
    nodes = [mock_node1, mock_node2]

    add_documents(mock_index, nodes)

    mock_index.insert_nodes.assert_called_once_with(nodes)


def test_query_collection():
    """Query VectorStoreIndex and return results in compatible format"""
    from core_logic.chroma_manager import query_documents

    mock_index = MagicMock()
    mock_retriever = MagicMock()
    mock_index.as_retriever.return_value = mock_retriever

    mock_node1 = MagicMock()
    mock_node1.get_content.return_value = "Result 1 text"
    mock_node1.metadata = {"source": "file1.txt"}
    mock_node1.node_id = "node1"
    mock_node1.score = 0.9

    mock_node2 = MagicMock()
    mock_node2.get_content.return_value = "Result 2 text"
    mock_node2.metadata = {"source": "file2.txt"}
    mock_node2.node_id = "node2"
    mock_node2.score = 0.7

    mock_retriever.retrieve.return_value = [mock_node1, mock_node2]

    results = query_documents(mock_index, "test query", n_results=2)

    assert results is not None
    assert len(results['documents'][0]) == 2
    assert 'Result 1 text' in results['documents'][0]
    assert 'Result 2 text' in results['documents'][0]
    mock_index.as_retriever.assert_called_once_with(similarity_top_k=2)


def test_delete_document_from_collection():
    """Delete document chunks from index by document_id"""
    from core_logic.chroma_manager import delete_document

    mock_index = MagicMock()
    mock_vector_store = MagicMock()
    mock_chroma_collection = MagicMock()
    mock_index._vector_store = mock_vector_store
    mock_vector_store._collection = mock_chroma_collection

    mock_chroma_collection.get.return_value = {
        'ids': ['doc1-chunk-0', 'doc1-chunk-1', 'doc1-chunk-2']
    }

    delete_document(mock_index, "doc1")

    mock_chroma_collection.get.assert_called_once_with(where={"document_id": "doc1"})
    mock_chroma_collection.delete.assert_called_once_with(
        ids=['doc1-chunk-0', 'doc1-chunk-1', 'doc1-chunk-2']
    )


def test_list_all_documents():
    """List all documents in index grouped by document_id"""
    from core_logic.chroma_manager import list_documents

    mock_index = MagicMock()
    mock_vector_store = MagicMock()
    mock_chroma_collection = MagicMock()
    mock_index._vector_store = mock_vector_store
    mock_vector_store._collection = mock_chroma_collection

    mock_chroma_collection.get.return_value = {
        'ids': ['doc1-chunk-0', 'doc1-chunk-1', 'doc2-chunk-0'],
        'metadatas': [
            {'document_id': 'doc1', 'file_name': 'file1.txt', 'file_type': '.txt', 'path': '/docs'},
            {'document_id': 'doc1', 'file_name': 'file1.txt', 'file_type': '.txt', 'path': '/docs'},
            {'document_id': 'doc2', 'file_name': 'file2.pdf', 'file_type': '.pdf', 'path': '/docs'}
        ]
    }

    documents = list_documents(mock_index)

    assert len(documents) == 2
    doc1 = next(d for d in documents if d['id'] == 'doc1')
    doc2 = next(d for d in documents if d['id'] == 'doc2')

    assert doc1['file_name'] == 'file1.txt'
    assert doc1['chunks'] == 2
    assert doc2['file_name'] == 'file2.pdf'
    assert doc2['chunks'] == 1
    mock_chroma_collection.get.assert_called_once()


@patch('core_logic.chroma_manager.VectorStoreIndex')
@patch('chromadb.HttpClient')
@patch('core_logic.chroma_manager.get_embedding_function')
def test_collection_uses_embedding_function(mock_embed_fn, mock_client_class, mock_index_class):
    """Verify index is configured with LlamaIndex Ollama embedding function"""
    from core_logic.chroma_manager import get_or_create_collection

    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    mock_client_class.return_value = mock_client

    mock_embedding = MagicMock()
    mock_embed_fn.return_value = mock_embedding

    mock_index = MagicMock()
    mock_index_class.from_vector_store.return_value = mock_index

    get_or_create_collection()

    mock_embed_fn.assert_called_once()

    call_kwargs = mock_index_class.from_vector_store.call_args.kwargs
    assert call_kwargs['embed_model'] == mock_embedding
