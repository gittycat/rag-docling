# syntax=docker/dockerfile:1
# Use Python 3.12 slim image
FROM python:3.12-slim

# Install system dependencies for docling (OCR support)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:0.9.0 /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Create non-root user early
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /tmp/shared && \
    chown -R appuser:appuser /tmp/shared

# Switch to non-root user for dependency installation
USER appuser

# Copy dependency file first for layer caching
COPY --chown=appuser:appuser services/rag_server/pyproject.toml ./

# Install dependencies using uv with CPU-only PyTorch for smaller image
# Use unsafe-best-match to allow finding best versions across all indexes
# Cache mount persists downloaded packages across builds
RUN --mount=type=cache,target=/home/appuser/.cache/uv,uid=1000,gid=1000 \
    uv sync --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match

# Copy application code (exclude pyproject.toml to avoid overwriting .venv)
COPY --chown=appuser:appuser services/rag_server/core_logic ./core_logic
COPY --chown=appuser:appuser services/rag_server/tests ./tests
COPY --chown=appuser:appuser services/rag_server/main.py ./
COPY --chown=appuser:appuser services/rag_server/celery_app.py ./
COPY --chown=appuser:appuser services/rag_server/tasks.py ./

# Expose port
EXPOSE 8001

# Run using the pre-built virtual environment directly
CMD [".venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
