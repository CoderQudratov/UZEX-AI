FROM python:3.12-slim-bookworm AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/uzex
RUN pip install --no-cache-dir uv==0.13.7
COPY pyproject.toml uv.lock README.md ./
COPY app ./app
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    PORT=8000 \
    DATABASE_PATH=data/processed/uzex.duckdb

WORKDIR /srv/uzex

# Dedicated non-root user
RUN groupadd --gid 10001 uzex && useradd --uid 10001 --gid uzex --no-create-home uzex

# Virtualenv from build stage
COPY --from=build --chown=uzex:uzex /srv/uzex/.venv /srv/uzex/.venv

# Pre-built authoritative DuckDB warehouse (read-only artifact)
COPY --chown=root:root data/processed/ ./data/processed/
RUN chmod 0444 data/processed/uzex.duckdb

# Application code and static web assets
COPY --chown=uzex:uzex app ./app
COPY --chown=uzex:uzex web ./web

USER 10001:10001
EXPOSE 8000

# Zero-SQL, zero-Gemini lightweight healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["/srv/uzex/.venv/bin/python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=2).close()"]

# Supported entrypoint applies safe logging, bounded concurrency and dynamic PORT.
CMD ["/srv/uzex/.venv/bin/python", "-m", "app"]
