"""The fact namespace partition (contract delta 26).

Test-suite templates render against netlab's expanded per-node data. Serving it
raw made every key netlab happens to compute an implicit Twinlab promise, so
delta 17 shipped it PROVISIONAL and reserved the pinning decision for pre-v1.0.

This module is that decision: each node's dict is PARTITIONED into a promised
core — the members below, stable Twinlab contract with pinned shapes — and
`_extras`, carrying every other key verbatim with NO promises (netlab-internal
`_`-prefixed bookkeeping included). Nothing is dropped, and the stability
signal travels in the template path itself: `{{ node.ospf.router_id }}` is
contract, `{{ node._extras.mtu }}` is visibly unstable ground.

The partition is PER-OBJECT: every dict the schema recognizes carries its own
`_extras`, so an unpinned member inside a pinned subtree is marked too
(`ospf.areas` -> `ospf._extras.areas`). Lists are never index-mirrored — a list
entry is an object with its own `_extras`.

Pure and total: no I/O, and every input shape produces output (a member whose
value does not match its pinned shape stays in place — see `_apply`). The
member lists are contract text; `docs/twinlab_client_shape.py`'s "Pinned fact
namespace" appendix is their canonical spelling and
`test_fact_namespace.py::test_pinned_paths_survive_installed_netlab` is the
drift guard that keeps them true against the netlab actually installed.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

EXTRAS_KEY = "_extras"


def _no_children() -> Mapping[str, _Spec]:
    """Default for a spec with nothing to descend into (a typed factory rather
    than `dict`, which would infer as partially unknown)."""
    return {}


@dataclass(frozen=True, slots=True)
class _Spec:
    """One recognized object: which members are pinned, and which of them are
    themselves recognized objects.

    `pinned` holds EVERY pinned member name (the nested ones too, since they
    keep their position); `objects`/`lists`/`maps` say how to descend. A member
    named in `pinned` alone is kept verbatim — pinned position, undescended
    content (e.g. `module: [str]`, `import: [str]`)."""

    pinned: frozenset[str]
    objects: Mapping[str, _Spec] = field(default_factory=_no_children)
    lists: Mapping[str, _Spec] = field(default_factory=_no_children)
    maps: Mapping[str, _Spec] = field(default_factory=_no_children)


# --------------------------------------------------------------------------- #
# The promised core (delta 26). Absence is meaningful throughout: a role:host
# node with a router_id but no `loopback` is a fact about the lab, not a gap.
# --------------------------------------------------------------------------- #

_NEIGHBOR = _Spec(pinned=frozenset({"node", "ifname", "ipv4", "ipv6"}))

# The per-interface OSPF overlay. `network_type`/`passive` are deliberately
# extras: they are netlab's rendering decisions, not addressing facts.
_INTERFACE_OSPF = _Spec(pinned=frozenset({"area"}))

_INTERFACE = _Spec(
    # `ifname` is the NOS-side name (CHR: ether2). The container-side name is
    # the LINK TABLE's `interface` and is deliberately not duplicated here.
    pinned=frozenset(
        {"ifname", "ifindex", "type", "linkindex", "name", "ipv4", "ipv6", "neighbors", "ospf"}
    ),
    lists={"neighbors": _NEIGHBOR},
    objects={"ospf": _INTERFACE_OSPF},
)

# `mgmt` addresses are BARE (no prefix length); every other pinned address in
# the namespace is CIDR form. That asymmetry is netlab's and is pinned as-is.
_MGMT = _Spec(pinned=frozenset({"ifname", "ipv4", "ipv6", "mac"}))

# The loopback INTERFACE, when the node has one. Its interface-entry
# bookkeeping (ifindex, type, virtual_interface, module overlays) is extras:
# suites want the address, and `interfaces[]` carries the full entry anyway.
_LOOPBACK = _Spec(pinned=frozenset({"ifname", "ipv4", "ipv6"}))

_OSPF = _Spec(pinned=frozenset({"router_id", "area"}))

_BGP_NEIGHBOR = _Spec(pinned=frozenset({"name", "as", "type", "ipv4", "vpnv4"}))

_BGP = _Spec(
    pinned=frozenset({"as", "router_id", "neighbors"}),
    lists={"neighbors": _BGP_NEIGHBOR},
)

_LDP = _Spec(pinned=frozenset({"router_id"}))

_VRF_LOOPBACK_ADDRESS = _Spec(pinned=frozenset({"ipv4", "ipv6"}))

_VRF = _Spec(
    pinned=frozenset({"rd", "import", "export", "loopback_address"}),
    objects={"loopback_address": _VRF_LOOPBACK_ADDRESS},
)

_NODE = _Spec(
    pinned=frozenset(
        {
            "name",
            "id",
            "device",
            "hostname",
            "role",
            "af",
            "module",
            "mgmt",
            "loopback",
            "interfaces",
            "ospf",
            "bgp",
            "ldp",
            "vrfs",
        }
    ),
    objects={"mgmt": _MGMT, "loopback": _LOOPBACK, "ospf": _OSPF, "bgp": _BGP, "ldp": _LDP},
    lists={"interfaces": _INTERFACE},
    maps={"vrfs": _VRF},
)


def _apply(spec: _Spec, key: str, value: object) -> object:
    """Descend into a pinned member, or keep it verbatim.

    A value whose type contradicts its pinned shape (netlab moved a dict to a
    scalar) is kept IN PLACE rather than pushed to `_extras`: the key is pinned,
    so a consumer reading it must keep resolving — the drift guard is what
    fails, loudly, in CI. Silently relocating it would turn a shape change into
    a StrictUndefined render error for every suite."""
    if (child := spec.objects.get(key)) is not None:
        return partition_object(value, child)  # non-dict passes through
    if (entry := spec.lists.get(key)) is not None:
        if not isinstance(value, list):
            return value
        return [partition_object(item, entry) for item in cast("list[object]", value)]
    if (member := spec.maps.get(key)) is not None:
        if not isinstance(value, dict):
            return value
        return {k: partition_object(v, member) for k, v in cast("dict[str, object]", value).items()}
    return value


def partition_object(raw: object, spec: _Spec) -> object:
    """Partition one recognized object. Non-dict input passes through — callers
    check, this is the recursive base case."""
    if not isinstance(raw, dict):
        return raw
    pinned: dict[str, object] = {}
    extras: dict[str, object] = {}
    for key, value in cast("dict[str, object]", raw).items():
        if key in spec.pinned:
            pinned[key] = _apply(spec, key, value)
        else:
            # Verbatim, and never descended into — the partition does not
            # reach below an unpinned key. A netlab-supplied `_extras` key is
            # itself unpinned, so it lands at `_extras._extras`: ours always
            # wins the position.
            extras[key] = value
    if extras:
        pinned[EXTRAS_KEY] = extras
    return pinned


def partition_node_facts(facts: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    """The whole namespace, partitioned per node — what templates render
    against and what `GET /labs/{name}/facts` serves. The stored cache stays
    RAW: this applies at the serve boundaries, so a netlab upgrade or a change
    to the member lists needs no migration and no cache invalidation."""
    return {
        node: cast("dict[str, object]", partition_object(raw, _NODE)) for node, raw in facts.items()
    }


def reassemble_node_facts(
    partitioned: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Inverse of `partition_node_facts` — merge every `_extras` back into its
    object's position. Exists to make the partition invariant TESTABLE (no key
    invented, none dropped); nothing in the request path calls it. Key ORDER is
    not restored, and is not part of the promise."""
    return {node: cast("dict[str, object]", _reassemble(raw)) for node, raw in partitioned.items()}


def _reassemble(value: object) -> object:
    if isinstance(value, list):
        return [_reassemble(item) for item in cast("list[object]", value)]
    if not isinstance(value, dict):
        return value
    merged: dict[str, object] = {}
    for key, member in cast("dict[str, object]", value).items():
        if key == EXTRAS_KEY:
            continue
        merged[key] = _reassemble(member)
    extras = cast("dict[str, object]", value).get(EXTRAS_KEY)
    if isinstance(extras, dict):
        # Extras are stored verbatim, so they are NOT reassembled — descending
        # would corrupt a nested literal `_extras` key that was always data.
        merged.update(cast("dict[str, object]", extras))
    return merged
