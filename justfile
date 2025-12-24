# UV_CACHE_DIR := invocation_directory() + "/.cache/uv"

alias test := test-unit

default:
    @just --list --list-heading "Usage: list <recipe>" 

setup:
    cd services/rag_server && \
    uv sync --group dev

test-unit: setup
    cd services/rag_server && \
    .venv/bin/pytest tests/ --ignore=tests/integration --ignore=tests/evaluation --ignore=tests/test_rag_eval.py -v

test-integration: setup docker-up
    cd services/rag_server && \
    .venv/bin/pytest tests/integration -v --run-integration

test-eval: setup
    cd services/rag_server && \
    .venv/bin/pytest tests/test_rag_eval.py --run-eval --eval-samples=5 -v

test-eval-full: setup
    cd services/rag_server && \
    .venv/bin/pytest tests/test_rag_eval.py --run-eval -v

docker-up:
    docker compose up -d

docker-down:
    docker compose down

docker-logs: docker-up
    docker compose logs -f

migrate-sessions: docker-up
    docker compose exec rag-server python scripts/migrate_sessions.py

@clean:
    # These fd commands run in parallel
    # -H includes hidden dirs (.pytest_cache)
    # -e pyc filters by extension directly
    # -X batches results into single rm call
    @fd -t d -H -X rm -rf __pycache__ ./services/rag_server
    @fd -t d -H -X rm -rf '\.pytest_cache' ./services/rag_server
    @fd -t f -H -e pyc -X rm . ./services/rag_server
    