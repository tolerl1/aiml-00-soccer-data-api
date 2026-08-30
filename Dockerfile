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

# Bake the native TLS client library into the image. soccerdata's Understat
# scraper uses wrapper-tls-requests, which downloads a ~4MB tls-client .so from
# GitHub on first use. Fetching it at build time keeps container startup quiet
# and removes a runtime dependency on GitHub being reachable.
RUN uv run --no-sync python -c "from tls_requests.models.libraries import TLSLibrary; TLSLibrary.load()"

EXPOSE 8000

# Bind to 0.0.0.0 so the container's port mapping actually works.
# --no-sync: the environment is already built above; without it `uv run`
# re-syncs at startup and reinstalls the dev group (ruff), undoing --no-dev.
CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
