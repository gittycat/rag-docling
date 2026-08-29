FROM python:3.13-slim

# Build tools: pytrec-eval-terrier (pulled in by ir-measures) publishes wheels for
# x86_64 but no Linux aarch64, so on arm64 hosts uv falls back to the sdist and
# needs a C compiler to build it. Do not remove this thinking it's unused.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Create non-root user with home directory
RUN groupadd -g 1000 appuser && \
    useradd -r -u 1000 -g appuser -m -d /home/appuser appuser && \
    chown -R appuser:appuser /app

# Copy project files
COPY --chown=appuser:appuser services/evals/pyproject.toml services/evals/uv.lock ./
COPY --chown=appuser:appuser services/evals/evals ./evals
COPY --chown=appuser:appuser services/evals/infrastructure ./infrastructure
COPY --chown=appuser:appuser services/evals/api ./api

# Install dependencies
RUN uv sync --frozen

# Switch to non-root user
USER appuser

EXPOSE 8002

# Default: run the API server. CLI still accessible via:
#   docker compose exec evals .venv/bin/python -m evals.cli ...
CMD [".venv/bin/uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8002", "--log-level", "warning"]
