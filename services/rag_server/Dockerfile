# Use Python 3.12 slim image
FROM python:3.12-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files
COPY services/rag_server/pyproject.toml ./

# Install dependencies using uv
RUN uv sync

# Copy application code
COPY services/rag_server/ ./

# Expose port
EXPOSE 8001

# Run with uv
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
