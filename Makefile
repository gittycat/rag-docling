RAG_SERVER_DIR := services/rag_server

.PHONY: setup test test-unit test-integration test-eval test-eval-full docker-up docker-down docker-logs clean

setup:
	cd $(RAG_SERVER_DIR) && uv sync --group dev

test: test-unit

test-unit: setup
	cd $(RAG_SERVER_DIR) && .venv/bin/pytest tests/ --ignore=tests/integration --ignore=tests/evaluation --ignore=tests/test_rag_eval.py -v

test-integration: setup docker-up
	cd $(RAG_SERVER_DIR) && .venv/bin/pytest tests/integration -v --run-integration

test-eval: setup
	cd $(RAG_SERVER_DIR) && .venv/bin/pytest tests/test_rag_eval.py --run-eval --eval-samples=5 -v

test-eval-full: setup
	cd $(RAG_SERVER_DIR) && .venv/bin/pytest tests/test_rag_eval.py --run-eval -v

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs: docker-up
	docker compose logs -f

clean:
	cd $(RAG_SERVER_DIR) && \
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true; \
	find . -type f -name "*.pyc" -delete 2>/dev/null || true; \
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
