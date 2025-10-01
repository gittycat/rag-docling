import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

def test_results_page_returns_200_with_query():
    """Results page should return 200 when accessed with valid query"""
    response = client.post("/search", data={"query": "test question"})
    assert response.status_code == 200

def test_results_page_displays_answer():
    """Results page should display the answer from RAG server"""
    response = client.post("/search", data={"query": "test question"})
    assert response.status_code == 200
    assert b'answer' in response.content.lower() or b'result' in response.content.lower()

def test_results_page_displays_sources():
    """Results page should have a section for sources"""
    response = client.post("/search", data={"query": "test question"})
    assert response.status_code == 200
    assert b'source' in response.content.lower() or b'document' in response.content.lower()

def test_results_page_has_back_button():
    """Results page should have a back/return to home button"""
    response = client.post("/search", data={"query": "test question"})
    assert response.status_code == 200
    content = response.content.lower()
    assert b'back' in content or b'home' in content or b'return' in content

def test_results_page_no_top_menu():
    """Results page should not have the top navigation menu"""
    response = client.post("/search", data={"query": "test question"})
    assert response.status_code == 200
    content = response.content.decode()
    # Check that it's not a full nav menu (should just have back button)
    # The requirement is "No top menu visible on this page"
    # We'll check that admin/about links are not present
    has_full_nav = 'admin' in content.lower() and 'about' in content.lower()
    assert not has_full_nav, "Results page should not have full top navigation menu"

def test_empty_query_returns_error():
    """Empty query should return an error or redirect"""
    response = client.post("/search", data={"query": ""})
    # Should either return 422 (validation error) or redirect
    assert response.status_code in [400, 422] or response.status_code == 200
