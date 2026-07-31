"""Host-preparation primitives: lab bridges and kernel modules.

Multi-access (3+ endpoint) links make netlab's clab provider reference a HOST
Linux bridge (`<name[0:10]>_<linkindex>`) that containerlab expects to
pre-exist, and some netlab modules need host kernel modules loaded (mpls, vrf,
vxlan, ...). Both are `netlab up` pre-start work — which Twinlab never runs —
so this sidecar performs exactly those two actions, and nothing else.

It is a deliberately dumb executor: it validates inputs against the exact
shapes netlab generates, runs fixed-argv commands (no shell, no caller
strings), and reports per-item outcomes. All bookkeeping — which lab owns
which bridge, collision policy, which module failures matter — lives in the
backend. Errors are values; `subprocess` is the one boundary.
"""

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# A Twinlab bridge name exactly as netlab generates it (augment/links.py): the
# lab name truncated to 10 chars, "_", the linkindex — ≤15 chars total, inside
# IFNAMSIZ. The prefix charset is the backend's lab-name charset. Anything
# else is refused before any command runs.
BRIDGE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,9}_[0-9]{1,4}$"
_BRIDGE_NAME = re.compile(BRIDGE_NAME_PATTERN)

# Every kernel module netlab's clab provider can ask for — the provider-level
# `kmods` map (lag/mpls/sr/vxlan/vrf) plus the per-device extras — mirrored
# from netlab 26.06 providers/clab.yml and devices/*.yml. This is the fixed
# allowlist: the service never modprobes a name outside it, whoever asks.
KERNEL_MODULES = frozenset(
    {
        "bonding",  # lag
        "mpls-router",  # mpls, sr
        "mpls-iptunnel",  # mpls, sr
        "vxlan",  # vxlan
        "udp_tunnel",  # vxlan
        "ip6_udp_tunnel",  # vxlan
        "vrf",  # vrf
        "ebtables",  # cumulus_nvue initial
        "openvswitch",  # cisco8000v initial
    }
)

_RUN_TIMEOUT_SECONDS = 10


def valid_bridge_name(name: str) -> bool:
    return _BRIDGE_NAME.match(name) is not None


@dataclass(frozen=True, slots=True)
class CommandFailure:
    message: str


# Injected into the primitives so tests exercise the full decision paths
# without touching the host.
type Run = Callable[[list[str]], CommandFailure | None]


def run_command(argv: list[str]) -> CommandFailure | None:
    """Boundary adapter: run one fixed-argv command (never a shell). None means
    success; a failure carries stderr (or stdout, or the exit code) as detail."""
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_RUN_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return CommandFailure(f"could not run {argv[0]}: {exc}")
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit code {proc.returncode}"
        return CommandFailure(detail)
    return None


type InterfaceState = Literal["absent", "bridge_empty", "bridge_ports", "other"]


def interface_state(sysfs_net: Path, name: str) -> InterfaceState:
    """What the host has at this interface name, read from /sys/class/net
    (injected for tests; reads work on the container's read-only /sys). `other`
    is an interface that is not a bridge — never something this service made."""
    iface = sysfs_net / name
    if not iface.exists():
        return "absent"
    if not (iface / "bridge").is_dir():
        return "other"
    brif = iface / "brif"
    has_ports = brif.is_dir() and any(brif.iterdir())
    return "bridge_ports" if has_ports else "bridge_empty"


type BridgeStatus = Literal[
    "created", "existed", "deleted", "absent", "in_use", "not_bridge", "error"
]


@dataclass(frozen=True, slots=True)
class BridgeOutcome:
    name: str
    status: BridgeStatus
    # Empty for the self-explanatory statuses; a message for refusals/errors.
    detail: str = ""


def ensure_bridge(name: str, *, sysfs_net: Path, run: Run) -> BridgeOutcome:
    """Create-if-missing, bring up, and open group_fwd_mask to 65528 (LLDP and
    other link-local protocols forwarded — mirrors netlab's own bridge setup;
    STP/LACP cannot be unmasked in a stock kernel). Idempotent and convergent:
    an existing bridge is re-upped and re-masked, so a retry or an interrupted
    earlier run ends in the same state. An existing NON-bridge interface of the
    same name is never touched."""
    state = interface_state(sysfs_net, name)
    if state == "other":
        return BridgeOutcome(
            name, "not_bridge", "an interface of this name exists and is not a bridge"
        )
    if state == "absent":
        failed = run(["ip", "link", "add", "name", name, "type", "bridge"])
        if failed is not None:
            return BridgeOutcome(name, "error", failed.message)
    # The fwd-mask goes via netlink (`ip link set ... type bridge`), not netlab's
    # sysfs echo: the container's /sys is mounted read-only.
    for argv in (
        ["ip", "link", "set", "dev", name, "up"],
        ["ip", "link", "set", "dev", name, "type", "bridge", "group_fwd_mask", "65528"],
    ):
        failed = run(argv)
        if failed is not None:
            return BridgeOutcome(name, "error", failed.message)
    return BridgeOutcome(name, "created" if state == "absent" else "existed")


def delete_bridge(name: str, *, sysfs_net: Path, run: Run) -> BridgeOutcome:
    """Delete-if-present. Refuses an interface that is not a bridge (never ours)
    and a bridge that still has ports attached: after a clean containerlab
    destroy the lab's veths are gone, so attached ports mean something else is
    still wired to it (e.g. a name-truncation-colliding lab)."""
    state = interface_state(sysfs_net, name)
    if state == "absent":
        return BridgeOutcome(name, "absent")
    if state == "other":
        return BridgeOutcome(
            name, "not_bridge", "an interface of this name exists and is not a bridge"
        )
    if state == "bridge_ports":
        return BridgeOutcome(name, "in_use", "bridge still has interfaces attached")
    failed = run(["ip", "link", "del", "dev", name])
    if failed is not None:
        return BridgeOutcome(name, "error", failed.message)
    return BridgeOutcome(name, "deleted")


@dataclass(frozen=True, slots=True)
class ModuleOutcome:
    name: str
    ok: bool
    # Empty on success; the modprobe failure detail otherwise.
    detail: str = ""


def load_module(name: str, *, run: Run) -> ModuleOutcome:
    """modprobe one allowlisted module (loading a loaded module is a no-op
    success). Never unloads anything: modules are host-shared across labs. The
    caller decides which failures matter (required vs optional) — this executor
    just reports."""
    failed = run(["modprobe", name])
    if failed is not None:
        return ModuleOutcome(name, ok=False, detail=failed.message)
    return ModuleOutcome(name, ok=True)
