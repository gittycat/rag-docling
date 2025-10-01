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

def test_admin_page_has_upload_form():
    """Admin page should have file upload form"""
    response = client.get("/admin")
    assert response.status_code == 200
    content = response.content.lower()
    assert b'<form' in content
    assert b'enctype="multipart/form-data"' in content or b"enctype='multipart/form-data'" in content

def test_admin_page_has_file_input():
    """Admin page should have file input for uploads"""
    response = client.get("/admin")
    assert response.status_code == 200
    content = response.content.lower()
    assert b'type="file"' in content or b"type='file'" in content

def test_admin_upload_accepts_multiple_files():
    """File input should accept multiple files"""
    response = client.get("/admin")
    assert response.status_code == 200
    content = response.content.lower()
    # Should have multiple attribute on file input
    assert b'multiple' in content
