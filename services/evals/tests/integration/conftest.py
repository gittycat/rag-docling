"""Integration fixtures for eval tests that need the running RAG server."""

import os

import httpx
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration", action="store_true", default=False,
        help="run integration tests that require the docker stack",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def rag_base_url():
    url = os.environ.get("RAG_SERVER_URL", "http://localhost:8001")
    try:
        response = httpx.get(f"{url}/health", timeout=10.0)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"RAG server not reachable at {url}: {exc}")
    return url
