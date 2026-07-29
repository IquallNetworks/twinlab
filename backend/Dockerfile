# syntax=docker/dockerfile:1

# uv-managed build. The venv (including the netlab CLI, a runtime dependency the
# backend shells out to) is materialised from the lockfile for reproducibility.
FROM python:3.14-slim

# ssh-keygen for POST /auth/ssh-keys/generate (server-side keypairs). BSD.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so the layer caches until the lockfile changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Then the project source.
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# netlab validates clab bind-mount source paths at `create` time, in this
# container's filesystem. The vyos node binds /lib/modules; create only checks
# the path exists, and the real mount is resolved on the host (where it exists)
# at deploy time — so an empty dir here is enough to pass the check.
RUN mkdir -p /lib/modules

EXPOSE 8000
# Apply migrations, then serve (exec so uvicorn is PID 1 for signal handling).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn twinlab_backend.app:app --host 0.0.0.0 --port 8000"]
