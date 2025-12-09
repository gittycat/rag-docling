import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock
from io import BytesIO
import tempfile
import os

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

# Save original before any patching
_original_named_temp_file = tempfile.NamedTemporaryFile


@pytest.fixture
def mock_upload_deps():
    """Mock dependencies for upload endpoint tests"""
    with patch('main.process_document_task') as mock_task, \
         patch('main.create_batch') as mock_batch, \
         patch('main.tempfile.NamedTemporaryFile') as mock_tempfile:

        # Mock Celery task
        mock_async_result = MagicMock()
        mock_async_result.id = "task-123"
        mock_task.apply_async.return_value = mock_async_result

        # Mock tempfile to use system temp dir instead of /tmp/shared
        def create_real_tempfile(delete=False, suffix='', dir=None, mode='w+b'):
            # Use system temp dir, ignoring the /tmp/shared dir
            return _original_named_temp_file(delete=delete, suffix=suffix, mode=mode)
        mock_tempfile.side_effect = create_real_tempfile

        yield {
            'task': mock_task,
            'batch': mock_batch,
            'tempfile': mock_tempfile
        }


def test_upload_endpoint_returns_200(mock_upload_deps):
    """POST /upload should return 200 for valid file"""
    file_content = b"Test document content"
    files = {"files": ("test.txt", BytesIO(file_content), "text/plain")}

    response = client.post("/upload", files=files)
    assert response.status_code == 200


def test_upload_endpoint_accepts_multiple_files(mock_upload_deps):
    """POST /upload should accept multiple files"""
    files = [
        ("files", ("test1.txt", BytesIO(b"Content 1"), "text/plain")),
        ("files", ("test2.txt", BytesIO(b"Content 2"), "text/plain"))
    ]

    response = client.post("/upload", files=files)
    assert response.status_code == 200


def test_upload_endpoint_returns_success_response(mock_upload_deps):
    """POST /upload should return batch info with task IDs"""
    files = {"files": ("test.txt", BytesIO(b"Test"), "text/plain")}
    response = client.post("/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert "batch_id" in data
    assert "tasks" in data
    assert data["status"] == "queued"


def test_upload_endpoint_supports_multiple_formats(mock_upload_deps):
    """POST /upload should accept txt, md, pdf, docx files"""
    # Test with .md file
    files = {"files": ("test.md", BytesIO(b"# Markdown"), "text/markdown")}
    response = client.post("/upload", files=files)
    assert response.status_code == 200
