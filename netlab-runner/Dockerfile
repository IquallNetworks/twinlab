# syntax=docker/dockerfile:1

# netlab config-push runner: netlab + ansible in one venv (so netlab finds the
# `ansible-playbook` it shells out to), plus the docker CLI (netlab drives the
# `docker` ansible connection, which execs into nodes via the mounted socket).
FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Docker CLI (static binary) for the community.docker `docker` connection. Pinned
# for reproducibility; only the client is needed (the daemon is the host's).
ARG DOCKER_VERSION=27.5.1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VERSION}.tgz" \
       | tar -xz -C /usr/local/bin --strip-components=1 docker/docker \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# netlab drives Ansible over the `docker` connection; that plugin ships in the
# community.docker collection.
RUN ansible-galaxy collection install community.docker

# netlab validates the vyos /lib/modules bind path at `create` time in this
# container's filesystem (the real mount is the host's, at deploy time).
RUN mkdir -p /lib/modules

EXPOSE 8000
CMD ["uvicorn", "netlab_runner.app:app", "--host", "0.0.0.0", "--port", "8000"]
