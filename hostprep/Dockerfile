# syntax=docker/dockerfile:1

# Host-preparation sidecar: the one Twinlab component that touches host network
# devices. It creates/deletes the per-lab Linux bridges that multi-access links
# need (netlab's `netlab up` pre-start work, which Twinlab never runs) and
# modprobes the kernel modules netlab's clab provider asks for. Runs on the
# host network namespace with NET_ADMIN + SYS_MODULE only — no Docker socket,
# no netlab, no definitions (see compose.yaml).
#
# iproute2: bridge create/delete/up and the group_fwd_mask, all via netlink
#   (the container's /sys is read-only, so netlab's sysfs echo isn't an option).
# kmod: modprobe against the host's /lib/modules, mounted read-only.
FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update && apt-get install -y --no-install-recommends iproute2 kmod \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Host network: this IS a host port. 8091 sits beside clab-api's 8090; the env
# override exists because a host-network port can collide with anything on the
# machine. Bound on all interfaces — the token gates every mutating route —
# but operators can firewall it down to the Docker bridge.
EXPOSE 8091
CMD ["sh", "-c", "uvicorn hostprep.app:app --host 0.0.0.0 --port ${HOSTPREP_PORT:-8091}"]
