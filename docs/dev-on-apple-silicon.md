# Developing Twinlab on an Apple Silicon Mac

**Status:** investigation, not yet actioned. Captured 2026-07-21 so it survives context
loss. No decision committed; no setup built yet.

## The problem

Twinlab's lab-deployment layer (`clab-api` + `netlab-runner` in `compose.yaml`) is
host-coupled to Linux: `network_mode: host`, `pid: host`, `privileged: true`, PAM auth
against mounted `/etc/passwd`+`/etc/shadow`, and Linux-only bind paths
(`/var/run/netns`, `/var/lib/docker/containers`, `/lib/modules`). It rests on
**containerlab**, which drives Linux kernel networking directly (netns, veth, bridges,
`tc`/netem — the Phase 3 impairment). **None of that runs natively on macOS**; on a Mac
"the host" is the Docker VM, not macOS, which breaks the host-network SSH path, PAM auth,
and the Linux bind mounts.

The `frontend` / `backend` / `postgres` services would run on macOS fine, but a lab
deploy, config push, netem, and the web terminal all route through the host-coupled
services and would fail. So the whole stack has to run inside a **Linux guest**.

Developer's need: work on this from an Apple Silicon Mac, self-contained (no external SSH
back home, nothing prod-like). Currently SSHes into a Linux PC, unavailable away from home.

## Key finding: arm64 VM + Rosetta beats a full x86_64 VM

A full x86_64 VM on Apple Silicon is **QEMU TCG software emulation** — no cross-arch
hardware assist exists (Apple's hypervisor only virtualizes arm64). Everything runs
~10–20× slower, including the *dev loop itself* (docker builds, vite, pytest, Ansible),
not just the lab nodes. Works, but miserable as a daily driver.

The containerlab ecosystem's converged answer: an **arm64 Linux VM** (near-native via
Apple's hypervisor) with **Rosetta translating individual amd64 containers** inside it.
Our stack is almost entirely arm64-clean already.

### Architecture audit (manifests checked from the Linux PC, 2026-07-21)

| Component | arm64? | Evidence |
|---|---|---|
| `clab-api-server` v0.5.0 | ✅ native | manifest ships `linux/arm64` |
| postgres 17 / backend / runner (python-slim) / frontend (node) | ✅ native | multi-arch official bases |
| containerlab itself | ✅ native | bundled in the arm64 clab-api image |
| netlab + ansible | ✅ | pure Python |
| netem (Phase 3) | ✅ | `sch_netem` in stock Ubuntu arm64 kernels |
| FRR node (`quay.io/frrouting/frr`) | ✅ native | manifest: arm64 present |
| **VyOS node (`ghcr.io/sysoleg/vyos-container`)** | ❌ **amd64-only** | manifest has no arm64; none published anywhere |

**The single gap is the VyOS container** — the one node platform Twinlab verifies today.
Under Rosetta it *may* just work (Debian 12 userland; Rosetta handles cEOS and Cisco IOL
per the containerlab docs), but no published VyOS-under-Rosetta report exists, so it needs
a ~15-min smoke test. The `/lib/modules` bind is fine either way: module loading is
kernel-side, so the VM's arm64 modules load regardless of the container userland arch.

## Options

- **A. arm64 Linux VM on the Mac — recommended.** Lima (Apache-2.0, fits our all-OSS
  posture) or OrbStack (faster/slicker but proprietary — free personal, paid for
  commercial). Ubuntu guest, `vmType: vz` + `rosetta: enabled`, Docker inside, same
  prereqs as the Linux PC (user in `clab_api` group, images pulled). SSH / VS Code Remote
  into the VM as today; Claude Code runs inside it. Port-forwarding surfaces the frontend
  at `localhost:5173` in the Mac browser. Works offline.
  - **Hedge if VyOS-under-Rosetta fails:** netlab is device-agnostic; do daily dev on FRR
    (arm64-native, fast) and keep full-fidelity VyOS verification on real x86 (the PC, or
    C/D). Matches the project's own stance ("works for any platform netlab supports; VyOS
    verified today").
- **B. Full x86_64 VM (UTM/QEMU).** The original idea. Max fidelity, fully offline, but
  TCG-slow across the whole dev loop. Fallback for occasional bit-exact verification, not
  daily work.
- **C. Tailscale/WireGuard to the Linux PC.** Literally solves "not available outside my
  home", zero project changes, ~1h, free. Needs the PC on and you online.
- **D. Cheap x86 cloud VM** (~€5/mo). Real amd64 from anywhere; online-only.

Forward-looking: if Twinlab ever adds **vrnetlab VM-based nodes** (vMX, XRv, …), those are
x86 QEMU VMs needing nested virtualization — M3+ chip, macOS 15+, and still emulation-slow.
Container-based nodes (current scope) are unaffected.

## Recommendation

**Option A with the FRR hedge**: Lima arm64 VM + Rosetta; smoke-test VyOS under Rosetta on
day one; fall back to FRR-for-dev / x86-for-verification if it misbehaves. Stand up option
C alongside (~1h) for an immediate second path.

## Next steps (when picked up)

1. Smoke-test `ghcr.io/sysoleg/vyos-container` under Rosetta in an arm64 Ubuntu VM — the
   decisive unknown.
2. Write a Lima template (`vz` + Rosetta + Docker + clab-api prereqs baked in).
3. Add a `docs/` setup guide (this file → a runnable checklist).
4. Optional: a minimal FRR dev topology as the arm64-native default for day-to-day work.

## Sources

- Containerlab on macOS (official): https://containerlab.dev/macos/
- Marc's Tech Blog — Containerlab with macOS on Apple Silicon: https://marcstech.blog/archives/containerlab-macos-apple-silicon/
- VyOS forum — building for arm64 fails: https://forum.vyos.io/t/building-for-arm64-fails/15720
- vyos-arm64-builder: https://github.com/mcbridematt/vyos-arm64-builder
