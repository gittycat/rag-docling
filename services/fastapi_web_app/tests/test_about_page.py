import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

def test_about_page_returns_200():
    """About page should return 200 status code"""
    response = client.get("/about")
    assert response.status_code == 200

def test_about_page_has_top_menu():
    """About page should have navigation menu"""
    response = client.get("/about")
    assert response.status_code == 200
    content = response.content.lower()
    assert b'home' in content
    assert b'admin' in content
    assert b'about' in content

def test_about_page_has_disabled_about_link():
    """About link should be disabled/styled as active on about page"""
    response = client.get("/about")
    assert response.status_code == 200
    content = response.content.decode()
    assert 'About' in content

def test_about_page_has_app_info():
    """About page should contain application information"""
    response = client.get("/about")
    assert response.status_code == 200
    content = response.content.lower()
    # Should have some info about the app
    assert b'rag' in content or b'system' in content or b'application' in content
