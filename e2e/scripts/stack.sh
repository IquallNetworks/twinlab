#!/usr/bin/env bash
# Lifecycle of the twinlab-e2e stack (see ../stack.env for what it is).
#
#   stack.sh up [dev]     build + start, wait for health
#   stack.sh down         stop (volumes kept)
#   stack.sh reset [dev]  the pristine cycle the gated suite run sits on: sweep
#                         leftover e2e lab containers/bridges -> down -v (drops
#                         the database and jump host keys) -> clear the
#                         lab-files dir -> up
#   stack.sh clean        the ITERATION alternative: empty the RUNNING stack
#                         through the API (scripts/api-clean.mjs — labs, users,
#                         groups, templates, keys; seconds, not minutes), then
#                         sweep docker-level strays. Not pristine — sessions
#                         and id sequences survive — so the gated run stays on
#                         reset.
#
# The test OIDC provider (oidc-test/compose.yaml: Dex, on DEX_PORT from
# stack.env) is always layered in — the sign-in specs drive it.
#
# `dev` layers compose.dev.yaml in: the frontend becomes the Vite dev server
# over bind-mounted source (HMR), so frontend edits need NO rebuild between
# runs. Both modes share one image tag — up/reset always pass --build, so
# switching modes is safe; after a frontend dependency change use `reset dev`
# (the down -v drops the stale node_modules anonymous volume).
#
# Requires the repo-root .env (for CLAB_API_USERNAME / CLAB_API_PASSWORD, the
# host PAM credentials shared by every stack on this host).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "${here}/../.." && pwd)"

# `dev` as the second argument selects the Vite dev-server frontend.
mode="${2:-}"
case "${mode}" in
  ''|dev) ;;
  *) echo "stack.sh: unknown mode '${mode}' (only 'dev')" >&2; exit 2 ;;
esac

compose() {
  local overlay=()
  [ "${mode}" = dev ] && overlay=(-f "${repo}/compose.dev.yaml")
  docker compose -p twinlab-e2e \
    --env-file "${repo}/.env" --env-file "${repo}/e2e/stack.env" \
    -f "${repo}/compose.yaml" "${overlay[@]}" -f "${repo}/e2e/compose.e2e.yaml" \
    -f "${repo}/oidc-test/compose.yaml" \
    "$@"
}

lab_files_dir="$(sed -n 's/^LAB_FILES_DIR=//p' "${repo}/e2e/stack.env")"
[ -n "${lab_files_dir}" ] || { echo "stack.sh: LAB_FILES_DIR missing from stack.env" >&2; exit 1; }

stack_env() {
  sed -n "s/^${1}=//p" "${repo}/e2e/stack.env"
}

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
  # A crashed run can also leak the labs' mgmt docker networks (<lab>_mgmt);
  # a name-colliding network with a stale subnet fails the next deploy.
  local networks
  networks="$(docker network ls -q --filter 'name=e2e-')"
  if [ -n "${networks}" ]; then
    echo "stack.sh: removing leftover e2e lab networks"
    # shellcheck disable=SC2086
    docker network rm ${networks} >/dev/null 2>&1 || true
  fi
  # containerlab's node-stop parks interfaces into /run/netns/clab-park-*
  # namespaces; a crashed run can strand them as plain files that poison the
  # next stop ("unknown FS magic"). Sweep the e2e ones (privileged one-off —
  # entries may be live nsfs mounts that need an umount first).
  # -e follows symlinks, so a DANGLING one (netns entries can be links to a
  # /proc/<pid>/ns/net that is gone) would be skipped and persist; -L catches it.
  docker run --rm --privileged -v /run/netns:/netns alpine sh -c '
    for f in /netns/clab-park-clab-e2e* /netns/clab-e2e-*; do
      [ -e "$f" ] || [ -L "$f" ] || continue
      umount "$f" 2>/dev/null
      rm -f "$f" && echo "stack.sh: removed stale park ns ${f##*/}"
    done' 2>/dev/null || true
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
  clean)
    E2E_BASE_URL="$(stack_env DEPLOYMENT_URL)" \
      E2E_ADMIN_USERNAME="$(stack_env BOOTSTRAP_ADMIN_USERNAME)" \
      E2E_ADMIN_PASSWORD="$(stack_env BOOTSTRAP_ADMIN_PASSWORD)" \
      node "${here}/api-clean.mjs"
    # Docker-level strays only exist where a record went missing (a crashed
    # run); with every record just destroyed this is usually a no-op.
    sweep_labs
    clear_lab_files
    ;;
  *)
    echo "usage: stack.sh {up [dev]|down|reset [dev]|clean}" >&2
    exit 2
    ;;
esac
