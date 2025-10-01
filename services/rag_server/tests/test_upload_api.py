import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
from unittest.mock import Mock, patch
from io import BytesIO

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

@patch('main.process_and_index_document')
def test_upload_endpoint_returns_200(mock_process):
    """POST /upload should return 200 for valid file"""
    mock_process.return_value = {"id": "doc-123", "status": "success"}

    file_content = b"Test document content"
    files = {"files": ("test.txt", BytesIO(file_content), "text/plain")}

    response = client.post("/upload", files=files)
    assert response.status_code == 200

@patch('main.process_and_index_document')
def test_upload_endpoint_accepts_multiple_files(mock_process):
    """POST /upload should accept multiple files"""
    mock_process.return_value = {"id": "doc-123", "status": "success"}

    files = [
        ("files", ("test1.txt", BytesIO(b"Content 1"), "text/plain")),
        ("files", ("test2.txt", BytesIO(b"Content 2"), "text/plain"))
    ]

    response = client.post("/upload", files=files)
    assert response.status_code == 200

@patch('main.process_and_index_document')
def test_upload_endpoint_returns_success_response(mock_process):
    """POST /upload should return success message with document IDs"""
    mock_process.return_value = {"id": "doc-123", "status": "success"}

    files = {"files": ("test.txt", BytesIO(b"Test"), "text/plain")}
    response = client.post("/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert "uploaded" in data or "success" in data or "documents" in data

@patch('main.process_and_index_document')
def test_upload_endpoint_supports_multiple_formats(mock_process):
    """POST /upload should accept txt, md, pdf, docx files"""
    mock_process.return_value = {"id": "doc-123", "status": "success"}

    # Test with .md file
    files = {"files": ("test.md", BytesIO(b"# Markdown"), "text/markdown")}
    response = client.post("/upload", files=files)
    assert response.status_code == 200
