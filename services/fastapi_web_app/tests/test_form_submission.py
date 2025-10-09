import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

def test_form_post_with_query_parameter():
    """Test that form submission with query parameter works"""
    # Mock the RAG server response
    mock_response = AsyncMock()
    mock_response.json.return_value = {
        "answer": "Test answer",
        "sources": []
    }
    mock_response.raise_for_status = lambda: None

    with patch('httpx.AsyncClient') as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_response)

        # Simulate form submission
        response = client.post("/", data={"query": "test query"})

        print(f"Status code: {response.status_code}")
        print(f"Response: {response.text[:500]}")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

def test_form_post_without_query_parameter():
    """Test that form submission without query parameter returns 422"""
    response = client.post("/", data={})

    print(f"Status code: {response.status_code}")
    print(f"Response: {response.text[:200]}")

    assert response.status_code == 422, "Should return 422 when query is missing"

def test_form_post_with_empty_query():
    """Test that form submission with empty query returns 422"""
    response = client.post("/", data={"query": ""})

    print(f"Status code: {response.status_code}")
    print(f"Response: {response.text[:200]}")

    assert response.status_code == 422, "Should return 422 when query is empty"

def test_form_post_content_type():
    """Test that form submission uses correct content type"""
    # Test with form data (should work)
    response1 = client.post("/", data={"query": "test"})
    print(f"Form data submission: {response1.status_code}")

    # Test with JSON (should fail because endpoint expects Form)
    response2 = client.post("/", json={"query": "test"})
    print(f"JSON submission: {response2.status_code}")
    print(f"JSON response: {response2.text[:200]}")
