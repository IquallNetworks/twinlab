"""Link inference: the logical (L3) topology from parsed source configs.

Configs cannot contain cabling, so a link is what addressing implies:
interfaces sharing one IPv4 subnet join one link — two members a p2p, three
or more a LAN, an unpeered interface a stub (the twin's boundary). This is
deliberately the LOGICAL topology (docs/config-import.md: physical switch
fabric collapses into the segment it implements; even Batfish derives its
config-based edges this way).

Management interfaces never join: an interface in a management VRF belongs
to the source's OOB network, which the lab replaces with Twinlab's own mgmt
plane (the `mgmt` quarantine class consumes its stanza). Loopbacks never
join either — the first one pins the node's netlab loopback, extras ride
the carry (a NOS creates loopbacks freely; no veth needed).
"""

import ipaddress
import re
from dataclasses import dataclass

from twinlab_backend.services.configimport.model import Note, ParsedSource

# Management-VRF detection: the strong, false-positive-free signal. An OOB
# interface without a VRF joins like any other — the wizard's review step is
# the backstop for that (documented limit, not a silent one: the emitted LAN
# is visible on the canvas).
_MGMT_VRF = re.compile(r"mgmt|management|oob", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NodeSource:
    """One source config bound to its final (sanitized) node name."""

    node: str
    device: str
    parsed: ParsedSource


@dataclass(frozen=True, slots=True)
class InferredEndpoint:
    node: str
    interface: str  # SOURCE interface name (the map's left-hand side)
    ipv4: str  # pinned CIDR


@dataclass(frozen=True, slots=True)
class InferredLink:
    """One inferred link: 1 endpoint = stub, 2 = p2p, 3+ = LAN."""

    network: str  # the joined subnet, e.g. "10.1.2.0/30"
    endpoints: tuple[InferredEndpoint, ...]


@dataclass(frozen=True, slots=True)
class LoopbackPin:
    """The node's netlab loopback: the source's FIRST addressed loopback."""

    interface: str  # SOURCE interface name (e.g. "Loopback0", "lo")
    ipv4: str


@dataclass(frozen=True, slots=True)
class Inference:
    links: tuple[InferredLink, ...]
    loopbacks: dict[str, LoopbackPin]  # node -> pinned loopback
    mgmt_interfaces: dict[str, frozenset[str]]  # node -> mgmt-VRF interfaces
    mgmt_vrfs: dict[str, frozenset[str]]  # node -> the mgmt VRF names seen
    notes: tuple[Note, ...]


def is_mgmt_vrf(vrf: str | None) -> bool:
    return vrf is not None and _MGMT_VRF.search(vrf) is not None


def _network_of(cidr: str) -> str | None:
    try:
        return str(ipaddress.IPv4Interface(cidr).network)
    except ValueError:
        return None


def infer(sources: list[NodeSource]) -> Inference:
    notes: list[Note] = []
    loopbacks: dict[str, LoopbackPin] = {}
    mgmt_interfaces: dict[str, frozenset[str]] = {}
    mgmt_vrfs: dict[str, frozenset[str]] = {}
    joinable: list[tuple[InferredEndpoint, str]] = []  # (endpoint, network)

    for source in sources:
        mgmt: set[str] = set()
        vrfs: set[str] = set()
        for interface in source.parsed.interfaces:
            if interface.loopback:
                if interface.ipv4 is None:
                    continue
                if source.node not in loopbacks:
                    loopbacks[source.node] = LoopbackPin(
                        interface=interface.name, ipv4=interface.ipv4
                    )
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
                continue
            if interface.ipv4 is None:
                if not interface.shutdown:
                    notes.append(
                        Note(
                            source.node,
                            f"interface {interface.name} is unnumbered; no link inferred "
                            "(its config rides the carry)",
                        )
                    )
                continue
            network = _network_of(interface.ipv4)
            if network is None:
                notes.append(
                    Note(source.node, f"interface {interface.name}: bad address {interface.ipv4}")
                )
                continue
            joinable.append(
                (
                    InferredEndpoint(
                        node=source.node, interface=interface.name, ipv4=interface.ipv4
                    ),
                    network,
                )
            )
        mgmt_interfaces[source.node] = frozenset(mgmt)
        mgmt_vrfs[source.node] = frozenset(vrfs)

    grouped: dict[str, list[InferredEndpoint]] = {}
    for endpoint, network in joinable:
        grouped.setdefault(network, []).append(endpoint)

    links: list[InferredLink] = []
    for network in sorted(grouped, key=lambda n: ipaddress.IPv4Network(n)):
        endpoints = grouped[network]
        # One node twice in a subnet would be a self-link netlab rejects:
        # keep the first appearance per node, the rest become stubs.
        kept: list[InferredEndpoint] = []
        seen_nodes: set[str] = set()
        for endpoint in endpoints:
            if endpoint.node in seen_nodes:
                notes.append(
                    Note(
                        endpoint.node,
                        f"interface {endpoint.interface} shares subnet {network} with "
                        "another interface of the same node; kept as a separate stub",
                    )
                )
                links.append(InferredLink(network=network, endpoints=(endpoint,)))
                continue
            seen_nodes.add(endpoint.node)
            kept.append(endpoint)
        links.append(InferredLink(network=network, endpoints=tuple(kept)))

    # Mask-mismatch honesty: a stub whose network CONTAINS (or sits inside)
    # another inferred network is likely a typo'd mask on a real link.
    stub_networks = [
        (link.endpoints[0], ipaddress.IPv4Network(link.network))
        for link in links
        if len(link.endpoints) == 1
    ]
    all_networks = [(link, ipaddress.IPv4Network(link.network)) for link in links]
    for endpoint, stub_net in stub_networks:
        for other, other_net in all_networks:
            if other_net == stub_net or endpoint in other.endpoints:
                continue
            if stub_net.overlaps(other_net):
                other_names = ", ".join(f"{e.node}:{e.interface}" for e in other.endpoints)
                notes.append(
                    Note(
                        endpoint.node,
                        f"interface {endpoint.interface} ({endpoint.ipv4}) overlaps "
                        f"{other.network} ({other_names}) but the masks differ; "
                        "not joined — check for a mask typo",
                    )
                )
    return Inference(
        links=tuple(links),
        loopbacks=loopbacks,
        mgmt_interfaces=mgmt_interfaces,
        mgmt_vrfs=mgmt_vrfs,
        notes=tuple(notes),
    )
