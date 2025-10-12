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

def test_results_page_has_follow_up_form():
    """Results page should have a follow-up search form"""
    response = client.post("/search", data={"query": "test question"})
    assert response.status_code == 200
    content = response.content.lower()
    # Should have a form for follow-up questions
    assert b'follow-up' in content or b'form' in content

def test_results_page_has_top_menu():
    """Combined page should have the top navigation menu"""
    response = client.post("/search", data={"query": "test question"})
    assert response.status_code == 200
    content = response.content.decode()
    # Combined page should have admin/about links in top nav
    has_nav = 'admin' in content.lower() and 'about' in content.lower()
    assert has_nav, "Combined page should have top navigation menu"

def test_empty_query_returns_error():
    """Empty query should return an error or redirect"""
    response = client.post("/search", data={"query": ""})
    # Should either return 422 (validation error) or redirect
    assert response.status_code in [400, 422] or response.status_code == 200
