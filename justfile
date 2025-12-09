UV_CACHE_DIR := invocation_directory() + "/.cache/uv"

alias default := setup
alias test := test-unit

[working-directory: 'services/rag_server']
setup:
    UV_CACHE_DIR={{UV_CACHE_DIR}} uv sync --group dev

[working-directory: 'services/rag_server']
test-unit: setup
    .venv/bin/pytest tests/ --ignore=tests/integration --ignore=tests/evaluation --ignore=tests/test_rag_eval.py -v

[working-directory: 'services/rag_server']
test-integration: setup docker-up
    .venv/bin/pytest tests/integration -v --run-integration

[working-directory: 'services/rag_server']
test-eval: setup
    .venv/bin/pytest tests/test_rag_eval.py --run-eval --eval-samples=5 -v

[working-directory: 'services/rag_server']
test-eval-full: setup
    .venv/bin/pytest tests/test_rag_eval.py --run-eval -v

docker-up:
    docker compose up -d

docker-down:
    docker compose down

docker-logs: docker-up
    docker compose logs -f

[working-directory: 'services/rag_server']
clean:
    # -X batches results into single rm call (like find ... +)
    # -H includes hidden dirs (.pytest_cache)
    # -e pyc filters by extension directly
    # - prefix in justfile ignores errors (replaces || true)
    -fd -t d __pycache__ -X rm -rf
    -fd -t f -e pyc  -X rm
    -fd -t d -H .pytest_cache  -X rm -rf
