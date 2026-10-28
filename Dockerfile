# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install uv (fast, reproducible dependency management)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (better layer caching)
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --frozen --no-dev || uv sync --no-dev

# Copy application code
COPY app ./app

ENV PORT=8080
EXPOSE 8080

# BACKENDS / IQCC_API_TOKEN / REFRESH_INTERVAL_SECONDS etc. are passed as env vars.
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
