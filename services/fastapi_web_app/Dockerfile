# Use Python 3.12 slim image
FROM python:3.12-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency file first for layer caching
COPY services/fastapi_web_app/pyproject.toml ./

# Install dependencies using uv
RUN uv sync

# Copy application code (exclude pyproject.toml to avoid overwriting .venv)
COPY services/fastapi_web_app/main.py ./
COPY services/fastapi_web_app/env_config.py ./
COPY services/fastapi_web_app/templates ./templates
COPY services/fastapi_web_app/static ./static
COPY services/fastapi_web_app/tests ./tests

# Expose port
EXPOSE 8000

# Run using the pre-built virtual environment directly
CMD [".venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
