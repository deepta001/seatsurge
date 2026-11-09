# One image for both process types (CLAUDE.md section 3): the API and the worker.
# Compose picks which one runs with `command:`. Build: docker compose build

FROM python:3.12-slim-bookworm

# uv, copied from its official image at a pinned version (same as local dev).
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

# Use the image's Python (never download one), compile .pyc files at build
# time for faster starts, and copy files instead of hard-linking them.
ENV UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first, in their own layer: they change rarely, so Docker can
# reuse this layer when only our code changes. --no-dev leaves out pytest etc.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

# Then the code. .dockerignore keeps .env, .venv and caches out of the image.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts

# Containers run as a normal user, not root (CLAUDE.md section 9): a bug in
# the app can't then change the system files inside the container.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
# The default command is the API; the worker and migrate services override it.
# Proxy settings come from FORWARDED_ALLOW_IPS (see docker-compose.yml).
# --no-access-log: the app writes its own access line, in JSON, with the correlation id.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", \
     "--no-access-log"]
