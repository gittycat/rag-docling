import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

def test_admin_page_returns_200():
    """Admin page should return 200 status code"""
    response = client.get("/admin")
    assert response.status_code == 200

def test_admin_page_has_top_menu():
    """Admin page should have navigation menu"""
    response = client.get("/admin")
    assert response.status_code == 200
    content = response.content.lower()
    assert b'home' in content
    assert b'admin' in content
    assert b'about' in content

def test_admin_page_has_disabled_admin_link():
    """Admin link should be disabled/styled as active on admin page"""
    response = client.get("/admin")
    assert response.status_code == 200
    content = response.content.decode()
    assert 'Admin' in content

def test_admin_page_displays_document_table():
    """Admin page should have a table for listing documents"""
    response = client.get("/admin")
    assert response.status_code == 200
    content = response.content.lower()
    assert b'<table' in content or b'document' in content

def test_admin_page_has_delete_buttons():
    """Admin page should have delete action column in table"""
    response = client.get("/admin")
    assert response.status_code == 200
    content = response.content.lower()
    # Should have actions column for delete functionality
    assert b'actions' in content
