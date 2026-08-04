"""Explicit wiring: the topology comes from the caller, not from a guess.

Configs cannot contain cabling, and addressing only implies it — so delta 23
made the wiring list a REQUIRED input and removed inferred adjacency: a link
exists because the caller said so. Each entry is a list of `node:interface`
endpoints; endpoint count decides, mirroring netlab's own model (2 = p2p,
3+ = LAN), and a wire whose endpoints are all unaddressed becomes a
`prefix: false` L2 link — the ISIS-core / trunk / LAG-member case addressing
could never see. The subnet join survives only as advice (`suggestion.py`).

What is NOT adjacency stays automatic, because it is per-interface
realization rather than topology: the first addressed loopback pins the
node's netlab loopback, management-VRF interfaces are quarantined (the lab
brings its own mgmt plane), and an addressed interface in no wire becomes a
STUB — the twin's boundary; its address and config must still land
somewhere. An unwired unnumbered interface is a warning: nothing to pin it
to, and the caller is the one who knows whether that matters.

Contradictions are ERRORS here (asserted wiring makes them broken intent,
not findings): unknown nodes/interfaces, an interface wired twice,
loopback/mgmt endpoints, and endpoints whose addresses disagree.
"""

import ipaddress
import re
from dataclasses import dataclass
from typing import Literal

from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.configimport.model import Note, ParsedSource

# Management-VRF detection: the strong, false-positive-free signal. An OOB
# interface without a VRF is just an interface — the caller either wires it
# or leaves it a stub, which is exactly the point of explicit wiring.
_MGMT_VRF = re.compile(r"mgmt|management|oob", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NodeSource:
    """One source config bound to its final (sanitized) node name."""

    node: str
    device: str
    parsed: ParsedSource
    # The hostname the config stated, when it stated one: wiring entries may
    # name a node either way (the caller reads hostnames in config files, the
    # suggestion emits final names).
    hostname: str | None = None


@dataclass(frozen=True, slots=True)
class WiredEndpoint:
    node: str  # FINAL node name
    interface: str  # SOURCE interface name (the map's left-hand side)
    ipv4: str | None  # pinned CIDR; None = unaddressed (emits `ipv4: false`)


@dataclass(frozen=True, slots=True)
class WiredLink:
    """One link the caller declared (or a stub the boundary rule produced).
    `network` is None for an all-unaddressed wire — a `prefix: false` L2
    link."""

    network: str | None
    endpoints: tuple[WiredEndpoint, ...]


@dataclass(frozen=True, slots=True)
class LoopbackPin:
    """The node's netlab loopback: the source's FIRST addressed loopback."""

    interface: str  # SOURCE interface name (e.g. "Loopback0", "lo")
    ipv4: str


@dataclass(frozen=True, slots=True)
class Wiring:
    links: tuple[WiredLink, ...]
    loopbacks: dict[str, LoopbackPin]
    mgmt_interfaces: dict[str, frozenset[str]]
    mgmt_vrfs: dict[str, frozenset[str]]
    notes: tuple[Note, ...]


type WiringProblemCode = Literal["wiring_invalid", "wiring_conflict"]


@dataclass(frozen=True, slots=True)
class WiringProblem:
    code: WiringProblemCode
    message: str
    entry: int | None  # index of the offending wiring entry, when it has one


def is_mgmt_vrf(vrf: str | None) -> bool:
    return vrf is not None and _MGMT_VRF.search(vrf) is not None


def network_of(cidr: str) -> str | None:
    try:
        return str(ipaddress.IPv4Interface(cidr).network)
    except ValueError:
        return None


def _node_lookup(sources: list[NodeSource]) -> dict[str, NodeSource | None]:
    """Node names a wiring endpoint may use: the final node name and the
    source hostname both resolve. A token that would resolve to two DIFFERENT
    sources maps to None — ambiguous, and rejected on use rather than
    silently picking one."""
    lookup: dict[str, NodeSource | None] = {}
    for source in sources:
        for key in (source.node, source.hostname):
            if key is None:
                continue
            if key not in lookup:
                lookup[key] = source
            elif lookup[key] is not source:
                lookup[key] = None
    return lookup


def _split_endpoint(token: str) -> tuple[str, str] | None:
    """`node:interface` — split on the FIRST colon so channelized interface
    names (`Serial0/1/0:0`) keep theirs."""
    node, separator, interface = token.partition(":")
    if separator == "" or node.strip() == "" or interface.strip() == "":
        return None
    return node.strip(), interface.strip()


def wire(sources: list[NodeSource], entries: list[list[str]]) -> Result[Wiring, WiringProblem]:
    """Build the topology from the caller's wiring plus per-interface
    realization. Every validation failure is a typed problem."""
    lookup = _node_lookup(sources)
    notes: list[Note] = []

    # Per-interface facts that are not adjacency: loopback pins, mgmt.
    loopbacks: dict[str, LoopbackPin] = {}
    mgmt_interfaces: dict[str, frozenset[str]] = {}
    mgmt_vrfs: dict[str, frozenset[str]] = {}
    for source in sources:
        mgmt: set[str] = set()
        vrfs: set[str] = set()
        for interface in source.parsed.interfaces:
            if interface.loopback:
                if interface.ipv4 is None:
                    continue
                if source.node not in loopbacks:
                    loopbacks[source.node] = LoopbackPin(interface.name, interface.ipv4)
                else:
                    notes.append(
                        Note(
                            source.node,
                            f"extra loopback {interface.name} ({interface.ipv4}) is not "
                            "pinned; its config rides the carry",
                        )
                    )
                continue
            if is_mgmt_vrf(interface.vrf):
                mgmt.add(interface.name)
                if interface.vrf is not None:
                    vrfs.add(interface.vrf)
        mgmt_interfaces[source.node] = frozenset(mgmt)
        mgmt_vrfs[source.node] = frozenset(vrfs)

    links: list[WiredLink] = []
    wired: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        if len(entry) < 2:
            return Err(
                WiringProblem(
                    "wiring_invalid",
                    f"wiring entry {index} has {len(entry)} endpoint(s); a link needs at "
                    "least two (an unconnected interface becomes a stub on its own)",
                    index,
                )
            )
        endpoints: list[WiredEndpoint] = []
        seen_nodes: set[str] = set()
        for token in entry:
            split = _split_endpoint(token)
            if split is None:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: {token!r} is not a 'node:interface' endpoint",
                        index,
                    )
                )
            node_token, interface_name = split
            if node_token not in lookup:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: no imported source named {node_token!r}",
                        index,
                    )
                )
            resolved = lookup[node_token]
            if resolved is None:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: {node_token!r} names more than one source; "
                        "use the node name the import assigns",
                        index,
                    )
                )
            source = resolved
            if source.node in seen_nodes:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: node {source.node!r} appears twice on one "
                        "link (netlab rejects self-links)",
                        index,
                    )
                )
            seen_nodes.add(source.node)

            interface = next(
                (i for i in source.parsed.interfaces if i.name == interface_name), None
            )
            if interface is None:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: {source.node} has no wireable interface "
                        f"{interface_name!r} (bundles and subinterfaces are not wireable — "
                        "wire the member ports instead)",
                        index,
                    )
                )
            if interface.loopback:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: {source.node}:{interface_name} is a loopback, "
                        "which is pinned on the node rather than wired",
                        index,
                    )
                )
            if interface_name in mgmt_interfaces[source.node]:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: {source.node}:{interface_name} is a "
                        "management-VRF interface; the lab brings its own management plane",
                        index,
                    )
                )
            key = (source.node, interface_name)
            if key in wired:
                return Err(
                    WiringProblem(
                        "wiring_invalid",
                        f"wiring entry {index}: {source.node}:{interface_name} is wired more "
                        "than once",
                        index,
                    )
                )
            wired.add(key)
            endpoints.append(
                WiredEndpoint(node=source.node, interface=interface_name, ipv4=interface.ipv4)
            )

        networks = {
            network
            for endpoint in endpoints
            if endpoint.ipv4 is not None and (network := network_of(endpoint.ipv4)) is not None
        }
        bad = [
            endpoint
            for endpoint in endpoints
            if endpoint.ipv4 is not None and network_of(endpoint.ipv4) is None
        ]
        if bad:
            return Err(
                WiringProblem(
                    "wiring_invalid",
                    f"wiring entry {index}: {bad[0].node}:{bad[0].interface} has an "
                    f"unparseable address {bad[0].ipv4!r}",
                    index,
                )
            )
        if len(networks) > 1:
            listed = ", ".join(
                f"{e.node}:{e.interface} {e.ipv4}" for e in endpoints if e.ipv4 is not None
            )
            return Err(
                WiringProblem(
                    "wiring_conflict",
                    f"wiring entry {index}: the wired interfaces sit in different subnets "
                    f"({listed}) — check the wiring or the source masks",
                    index,
                )
            )
        links.append(
            WiredLink(
                network=next(iter(networks)) if networks else None,
                endpoints=tuple(endpoints),
            )
        )

    # Per-interface realization for everything the wiring left out.
    for source in sources:
        for interface in source.parsed.interfaces:
            if interface.loopback or interface.name in mgmt_interfaces[source.node]:
                continue
            if (source.node, interface.name) in wired:
                continue
            if interface.ipv4 is None:
                if not interface.shutdown:
                    notes.append(
                        Note(
                            source.node,
                            f"interface {interface.name} is unnumbered and unwired; no link "
                            "was created (wire it to realize it — its config rides the carry)",
                        )
                    )
                continue
            network = network_of(interface.ipv4)
            if network is None:
                notes.append(
                    Note(source.node, f"interface {interface.name}: bad address {interface.ipv4}")
                )
                continue
            notes.append(
                Note(
                    source.node,
                    f"interface {interface.name} ({interface.ipv4}) is not wired to a peer; "
                    "realized as a stub — the twin's boundary",
                )
            )
            links.append(
                WiredLink(
                    network=network,
                    endpoints=(
                        WiredEndpoint(
                            node=source.node, interface=interface.name, ipv4=interface.ipv4
                        ),
                    ),
                )
            )

    return Ok(
        Wiring(
            links=tuple(links),
            loopbacks=loopbacks,
            mgmt_interfaces=mgmt_interfaces,
            mgmt_vrfs=mgmt_vrfs,
            notes=tuple(notes),
        )
    )
