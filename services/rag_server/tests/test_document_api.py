import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

@patch('main.get_or_create_collection')
@patch('main.list_documents')
def test_list_documents_returns_200(mock_list_docs, mock_get_collection):
    """GET /documents should return 200 status code"""
    mock_collection = Mock()
    mock_get_collection.return_value = mock_collection
    mock_list_docs.return_value = []

    response = client.get("/documents")
    assert response.status_code == 200

@patch('main.get_or_create_collection')
@patch('main.list_documents')
def test_list_documents_returns_json(mock_list_docs, mock_get_collection):
    """GET /documents should return JSON with documents list"""
    mock_collection = Mock()
    mock_get_collection.return_value = mock_collection
    mock_list_docs.return_value = [
        {"id": "doc1", "file_name": "test.txt", "file_type": "txt"}
    ]

    response = client.get("/documents")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert isinstance(data["documents"], list)

@patch('main.get_or_create_collection')
@patch('main.delete_document')
def test_delete_document_returns_200(mock_delete_doc, mock_get_collection):
    """DELETE /documents/{id} should return 200 status code"""
    mock_collection = Mock()
    mock_get_collection.return_value = mock_collection
    mock_delete_doc.return_value = None

    response = client.delete("/documents/test-doc-id")
    assert response.status_code == 200

@patch('main.get_or_create_collection')
@patch('main.delete_document')
def test_delete_document_returns_success_message(mock_delete_doc, mock_get_collection):
    """DELETE /documents/{id} should return success message"""
    mock_collection = Mock()
    mock_get_collection.return_value = mock_collection
    mock_delete_doc.return_value = None

    response = client.delete("/documents/test-doc-id")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data or "status" in data
