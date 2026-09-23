# syntax=docker/dockerfile:1

# MCP server: Twinlab's public API as Model Context Protocol tools, for agent
# hosts. A thin sidecar over twinlab-client that acts with each caller's own
# API key. No database, no secrets, and nothing of the backend's but its
# public API (see docs/mcp-server.md).
#
# Two additional build contexts, both supplied by compose:
# - `client`: twinlab-client is a path dependency (../client in uv.lock),
#   outside this context, so it lands at /client where the lock expects it.
# - `docs`: src/twinlab_mcp/guide is a symlink to ../../../docs/guide, which
#   resolves to /docs/guide in here. The `test` guards the silent failure: a
#   guide that never arrived would otherwise only surface at startup.
FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Only what building the package reads: that tree also holds a venv and caches.
COPY --from=client pyproject.toml README.md LICENSE /client/
COPY --from=client src /client/src/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
COPY --from=docs guide/ /docs/guide/
RUN test -f src/twinlab_mcp/guide/README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
CMD ["uvicorn", "twinlab_mcp.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
