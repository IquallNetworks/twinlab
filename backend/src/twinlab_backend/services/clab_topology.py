"""Host policy applied to a generated containerlab topology at deploy time.

netlab writes the topology from the definition; these adjustments come from the
DEPLOYMENT (settings), not the lab, so they are applied to the shippable copy and
never stored or shown as part of the definition. Both are pure: a new topology
is returned and the input is left alone. Measurements and the host setup they
assume are in docs/resource-limits.md.
"""

import copy
from dataclasses import dataclass
from typing import cast

from twinlab_backend.services.netlab import ClabTopology


def _inner(topology: ClabTopology) -> dict[str, object] | None:
    inner = topology.get("topology")
    return cast("dict[str, object]", inner) if isinstance(inner, dict) else None


def place_in_cgroup(topology: ClabTopology, parent: str) -> ClabTopology:
    """Put every node under `parent` (containerlab's `cgroup-parent`, i.e.
    docker's `--cgroup-parent`), so one cgroup — a systemd slice on a systemd
    host — can bound what all labs use together.

    The limit is host policy, so it must not be escapable from a definition:
    the value is written on `defaults` AND on every node (node beats group,
    kind and defaults in containerlab's precedence), and any parent a kind or
    group names is removed. netlab rejects `clab.cgroup-parent` at node, group
    and device level today (its clab attribute list is closed, verified
    against 26.07), so this guards against that list growing, not a known
    path."""
    result = copy.deepcopy(topology)
    inner = _inner(result)
    if inner is None:
        return result
    defaults = inner.get("defaults")
    defaults_map = cast("dict[str, object]", defaults) if isinstance(defaults, dict) else {}
    defaults_map["cgroup-parent"] = parent
    inner["defaults"] = defaults_map
    for section in ("kinds", "groups"):
        entries = inner.get(section)
        if isinstance(entries, dict):
            for entry in cast("dict[str, object]", entries).values():
                if isinstance(entry, dict):
                    _ = cast("dict[str, object]", entry).pop("cgroup-parent", None)
    nodes = inner.get("nodes")
    if isinstance(nodes, dict):
        for node in cast("dict[str, object]", nodes).values():
            if isinstance(node, dict):
                cast("dict[str, object]", node)["cgroup-parent"] = parent
    return result


@dataclass(frozen=True, slots=True)
class BootStagger:
    """Nodes start in waves of `wave_size`, `interval_seconds` apart."""

    wave_size: int
    interval_seconds: int

    def waves(self, nodes: int) -> int:
        return -(-nodes // self.wave_size)


def stagger_boot(topology: ClabTopology, stagger: BootStagger) -> tuple[ClabTopology, int]:
    """Give each node a containerlab `startup-delay` so the lab boots in waves
    instead of all at once — a NOS boot is a CPU burst (VyOS: ~5 cores for ~30s
    on 7 nodes started together), and stacking them starves the whole host.

    Waves follow the topology's node order, which is the definition's. A node
    that already carries a `startup-delay` (netlab passes `clab.startup-delay`
    through) keeps it and is left out of the waves. Returns the topology and the
    number of nodes it delayed or scheduled."""
    result = copy.deepcopy(topology)
    inner = _inner(result)
    nodes = inner.get("nodes") if inner is not None else None
    if not isinstance(nodes, dict):
        return result, 0
    scheduled = 0
    for node in cast("dict[str, object]", nodes).values():
        if not isinstance(node, dict):
            continue
        node_map = cast("dict[str, object]", node)
        if "startup-delay" in node_map:
            continue
        wave = scheduled // stagger.wave_size
        if wave:
            node_map["startup-delay"] = wave * stagger.interval_seconds
        scheduled += 1
    return result, scheduled
