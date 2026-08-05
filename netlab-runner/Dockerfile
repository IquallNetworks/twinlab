# syntax=docker/dockerfile:1

# netlab config-push runner: netlab + ansible in one venv (so netlab finds the
# `ansible-playbook` it shells out to), plus the docker CLI (netlab drives the
# `docker` ansible connection, which execs into nodes via the mounted socket).
FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Docker CLI (static binary) for the community.docker `docker` connection (VyOS
# and other in-container-CLI NOSes). openssh-client + sshpass are for the Ansible
# network_cli connection Cisco IOS/IOL devices use — netlab pushes their config
# over SSH to the node mgmt IP (password auth: admin/admin), not the docker
# socket, and its SSH-readiness check shells out to sshpass. Docker CLI is pinned
# for reproducibility; only the client is needed (the daemon is the host's).
# sudo + iproute2 + procps serve netlab's netns config path for plain-container
# nodes (linux, and daemons): `netlab initial` deploys their config by running
# the generated script as `sudo ip netns exec clab-<lab>-<node> sh <script>` —
# the script runs THIS container's tools (full iproute2, procps sysctl) against
# the node's network namespace (alpine node images only carry busybox). The
# container runs as root, so sudo is a passthrough, but netlab hardcodes the
# prefix. See compose.yaml for the namespace access this needs (host pid
# namespace + /var/run/netns + SYS_ADMIN/SYS_PTRACE).
ARG DOCKER_VERSION=27.5.1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates openssh-client sshpass sudo iproute2 procps \
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

# Ansible collections netlab drives — ONE PER SUPPORTED TRANSPORT, so every
# device the catalog admits needs its collection here. A missing one does not
# look like a packaging problem: netlab renders the config fine and Ansible
# then reports "network os <x> is not supported" + UNREACHABLE per node.
#   community.docker  — the `docker` connection (VyOS, FRR, bird, dnsmasq et
#     al., exec via the socket; the daemons need no collection of their own)
#   cisco.ios + ansible.netcommon — the `network_cli` connection for Cisco
#     IOS/IOL, whose config push is SSH to the node mgmt IP (see openssh-client
#     above; the paramiko transport comes from pyproject).
#   community.routeros — `network_cli` for MikroTik RouterOS 7 (CHR), same SSH
#     path as IOL.
RUN ansible-galaxy collection install \
      community.docker cisco.ios ansible.netcommon community.routeros

# netlab validates the vyos /lib/modules bind path at `create` time in this
# container's filesystem (the real mount is the host's, at deploy time).
RUN mkdir -p /lib/modules

# Lab nodes are ephemeral: every (re)deploy recreates the container with a NEW
# SSH host key, so host-key pinning only ever breaks — a stale known_hosts entry
# makes the next config push fail with "host key mismatch". The Ansible
# network_cli/paramiko connection Cisco IOS/IOL uses loads ~/.ssh/known_hosts even
# though netlab sets host_key_checking=False, so the reliable fix is to make that
# file unable to hold a stale key: point it at /dev/null. There is then never a
# prior key to mismatch (a missing key is auto-added and the connection proceeds),
# and netlab's record_host_keys=false means nothing is written back. These are
# throwaway sandbox nodes on a private mgmt net, so pinning buys nothing. The ssh
# config + env cover any plain-ssh/other-tool path (netlab's own readiness probe
# already passes these flags inline).
ENV ANSIBLE_HOST_KEY_CHECKING=False
RUN mkdir -p /root/.ssh \
    && ln -sf /dev/null /root/.ssh/known_hosts \
    && printf 'Host *\n    StrictHostKeyChecking no\n    UserKnownHostsFile /dev/null\n' \
       > /root/.ssh/config \
    && chmod 700 /root/.ssh && chmod 600 /root/.ssh/config

EXPOSE 8000
CMD ["uvicorn", "netlab_runner.app:app", "--host", "0.0.0.0", "--port", "8000"]
