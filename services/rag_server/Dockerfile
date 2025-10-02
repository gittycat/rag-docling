# Use Python 3.12 slim image
FROM python:3.12-slim

# Install system dependencies for docling (OCR support)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy dependency files
COPY services/rag_server/pyproject.toml ./

# Install dependencies using uv with CPU-only PyTorch for smaller image
# Use unsafe-best-match to allow finding best versions across all indexes
RUN uv sync --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match

# Copy application code
COPY services/rag_server/ ./

# Expose port
EXPOSE 8001

# Run with uv
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
