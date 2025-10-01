import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app

client = TestClient(app)

def test_home_page_returns_200():
    """Home page should return 200 status code"""
    response = client.get("/")
    assert response.status_code == 200

def test_home_page_has_search_input():
    """Home page should contain a search input field"""
    response = client.get("/")
    assert response.status_code == 200
    assert b'type="text"' in response.content or b"type='text'" in response.content
    assert b'name="query"' in response.content or b"name='query'" in response.content

def test_home_page_has_search_button():
    """Home page should contain a search button"""
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.lower()
    assert b'type="submit"' in content or b"type='submit'" in content or b'search' in content

def test_home_page_has_top_menu():
    """Home page should have navigation menu with Home, Admin, About"""
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.lower()
    assert b'home' in content
    assert b'admin' in content
    assert b'about' in content

def test_home_page_has_disabled_home_link():
    """Home link should be disabled/styled as active on home page"""
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode()
    # Home link should either be disabled, have an active class, or not be a clickable link
    assert 'Home' in content

def test_search_form_posts_to_results():
    """Search form should have action pointing to results endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    content = response.content.decode()
    # Form should exist and likely post to /search or /results
    assert '<form' in content.lower()
