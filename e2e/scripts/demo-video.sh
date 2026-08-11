#!/usr/bin/env bash
# Collect the videos a run recorded and leave ONE file behind.
#
#   TWINLAB_DEMO=1 pnpm exec playwright test 11-builder-l3vpn --project=fast
#   scripts/demo-video.sh                 # -> report/demo/walkthrough.webm
#   scripts/demo-video.sh --mp4           # also transcode to H.264
#
# In demo mode the walkthrough is a single test, so there is usually one video
# and this just copies it. The joining path is for when several tests recorded
# (a full `TWINLAB_DEMO=1 pnpm test:fast`, or an older per-test spec): clips
# are concatenated in the order Playwright wrote them, which is run order.
#
# Watching it over SSH: serve it and forward the port, e.g.
#   python3 -m http.server 9325 --directory report/demo --bind 127.0.0.1
#   ssh -L 9325:localhost:9325 <host>     # then open http://localhost:9325
# or just fetch it:
#   scp <host>:<repo>/e2e/report/demo/walkthrough.webm .
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
e2e="$(cd "${here}/.." && pwd)"
src="${e2e}/test-results"
out="${e2e}/report/demo"

command -v ffmpeg >/dev/null || { echo "demo-video: ffmpeg is not installed" >&2; exit 1; }
[ -d "${src}" ] || { echo "demo-video: no test-results/ — run the suite first" >&2; exit 1; }

# Oldest first: Playwright writes each video when its test ends, so mtime order
# is run order. -print0/read -d handles the spaces Playwright puts in its
# result directory names.
mapfile -d '' -t videos < <(find "${src}" -name '*.webm' -printf '%T@\t%p\0' \
  | sort -zn | cut -z -f2-)

if [ "${#videos[@]}" -eq 0 ]; then
  echo "demo-video: no .webm files under test-results/" >&2
  echo "            did the run set TWINLAB_DEMO=1? (video is off by default)" >&2
  exit 1
fi

mkdir -p "${out}"
echo "demo-video: ${#videos[@]} clip(s)"
for v in "${videos[@]}"; do printf '  %s\n' "${v#"${src}/"}"; done

if [ "${#videos[@]}" -eq 1 ]; then
  cp "${videos[0]}" "${out}/walkthrough.webm"
else
  # The concat DEMUXER re-muxes without re-encoding: every clip comes from the
  # same browser at the same size, so no transcode is needed. Paths are quoted
  # for the list format, which treats a bare ' as a delimiter.
  list="$(mktemp)"
  trap 'rm -f "${list}"' EXIT
  for v in "${videos[@]}"; do printf "file '%s'\n" "${v//\'/\'\\\'\'}" >> "${list}"; done
  ffmpeg -nostdin -loglevel error -y -f concat -safe 0 -i "${list}" -c copy \
    "${out}/walkthrough.webm"
fi

if [ "${1:-}" = "--mp4" ]; then
  # For players that will not take VP8/webm. Re-encode, so it is opt-in.
  ffmpeg -nostdin -loglevel error -y -i "${out}/walkthrough.webm" \
    -c:v libx264 -pix_fmt yuv420p -movflags +faststart "${out}/walkthrough.mp4"
  echo "demo-video: wrote ${out}/walkthrough.mp4"
fi

echo "demo-video: wrote ${out}/walkthrough.webm"
