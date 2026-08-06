#!/usr/bin/env bash
# Lifecycle of the twinlab-e2e stack (see ../stack.env for what it is).
#
#   stack.sh up      build + start, wait for health
#   stack.sh down    stop (volumes kept)
#   stack.sh reset   the pristine cycle the suite runs on: sweep leftover e2e
#                    lab containers/bridges -> down -v (drops the database and
#                    jump host keys) -> clear the lab-files dir -> up
#
# Requires the repo-root .env (for CLAB_API_USERNAME / CLAB_API_PASSWORD, the
# host PAM credentials shared by every stack on this host).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "${here}/../.." && pwd)"

compose() {
  docker compose -p twinlab-e2e \
    --env-file "${repo}/.env" --env-file "${repo}/e2e/stack.env" \
    -f "${repo}/compose.yaml" -f "${repo}/e2e/compose.e2e.yaml" \
    "$@"
}

lab_files_dir="$(sed -n 's/^LAB_FILES_DIR=//p' "${repo}/e2e/stack.env")"
[ -n "${lab_files_dir}" ] || { echo "stack.sh: LAB_FILES_DIR missing from stack.env" >&2; exit 1; }

# Suite lab names are e2e-prefixed, so their containerlab containers are
# clab-e2e… and their host bridges (lab name truncated to 10 chars + _linkindex)
# start with e2e-. Both sweeps are best-effort: a clean run leaves nothing.
sweep_labs() {
  local containers
  containers="$(docker ps -aq --filter 'name=clab-e2e')"
  if [ -n "${containers}" ]; then
    echo "stack.sh: removing leftover e2e lab containers"
    # shellcheck disable=SC2086
    docker rm -f ${containers} >/dev/null || true
  fi
  # Bridges live in the host netns and are root-owned; a one-off NET_ADMIN
  # container avoids needing sudo. Only actual bridges are touched.
  docker run --rm --net=host --cap-add=NET_ADMIN alpine sh -c '
    for b in /sys/class/net/e2e-*; do
      [ -d "$b/bridge" ] || continue
      echo "stack.sh: removing leftover bridge ${b##*/}"
      ip link del "${b##*/}" || true
    done' 2>/dev/null || true
}

clear_lab_files() {
  # The dir and its contents are root-owned (written by the backend container);
  # clear it through a container mount rather than sudo. Mounting also creates
  # the dir if this host has never run the stack.
  docker run --rm -v "${lab_files_dir}:/lab-files" alpine \
    sh -c 'find /lab-files -mindepth 1 -delete' || true
}

case "${1:-}" in
  up)
    compose up -d --build --wait
    ;;
  down)
    compose down
    ;;
  reset)
    sweep_labs
    compose down -v
    clear_lab_files
    compose up -d --build --wait
    ;;
  *)
    echo "usage: stack.sh {up|down|reset}" >&2
    exit 2
    ;;
esac
