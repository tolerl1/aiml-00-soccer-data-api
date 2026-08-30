# syntax=docker/dockerfile:1

FROM python:3.12-slim

# Install uv (fast Python package manager) into the image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (better layer caching), then copy the app.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY main.py ./

RUN uv sync --frozen --no-dev

EXPOSE 8000

# Bind to 0.0.0.0 so the container's port mapping actually works.
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
