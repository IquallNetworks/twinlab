"""The subnet join, demoted to advice (delta 23).

Until delta 23 this WAS the topology: interfaces sharing an IPv4 subnet
became a link. Explicit wiring replaced it, because a guess is not intent —
but the addressing in the sources is still real information, and retyping 25
obvious wires by hand is not a virtue. So the join survives here as a
PROPOSAL: `POST /import/wiring-suggestion` returns wiring entries for a
client to prefill an editor with, the human reviews and edits them, and
`import_network` acts only on the explicit list it is then given. Nothing
here ever reaches a lab on its own.

What the join cannot see is exactly what it warns about: unnumbered
interfaces (no subnet to join on) and interfaces whose only peer sits
outside the import set. Those are the wires a human must supply.
"""

import ipaddress
from dataclasses import dataclass

from twinlab_backend.services.configimport.model import Note
from twinlab_backend.services.configimport.wiring import NodeSource, is_mgmt_vrf, network_of


@dataclass(frozen=True, slots=True)
class WiringSuggestion:
    # Entries in the wiring format the factory takes: lists of
    # "node:interface" endpoints, spelled with the FINAL node names.
    wiring: list[list[str]]
    notes: tuple[Note, ...]


def suggest_wiring(sources: list[NodeSource]) -> WiringSuggestion:
    """Propose wiring from the sources' addressing: interfaces sharing a
    subnet are probably a link (2 endpoints p2p, 3+ a LAN). Single-member
    subnets are deliberately NOT proposed — an unpeered addressed interface
    becomes a stub without any wiring entry, so proposing it would only add
    noise the user has to delete."""
    notes: list[Note] = []
    grouped: dict[str, list[tuple[str, str]]] = {}  # network -> [(node, iface)]

    for source in sources:
        for interface in source.parsed.interfaces:
            if interface.loopback or is_mgmt_vrf(interface.vrf):
                continue
            if interface.ipv4 is None:
                if not interface.shutdown:
                    notes.append(
                        Note(
                            source.node,
                            f"interface {interface.name} is unnumbered — addressing cannot "
                            "place it; wire it by hand if it carries a link",
                        )
                    )
                continue
            network = network_of(interface.ipv4)
            if network is None:
                notes.append(
                    Note(source.node, f"interface {interface.name}: bad address {interface.ipv4}")
                )
                continue
            grouped.setdefault(network, []).append((source.node, interface.name))

    wiring: list[list[str]] = []
    for network in sorted(grouped, key=ipaddress.IPv4Network):
        members = grouped[network]
        if len(members) < 2:
            continue
        # One node twice in a subnet cannot be one link (netlab rejects
        # self-links): propose the first appearance, note the rest.
        entry: list[str] = []
        seen: set[str] = set()
        for node, interface in members:
            if node in seen:
                notes.append(
                    Note(
                        node,
                        f"interface {interface} shares subnet {network} with another of its "
                        "own interfaces; left out of the proposed wire",
                    )
                )
                continue
            seen.add(node)
            entry.append(f"{node}:{interface}")
        if len(entry) >= 2:
            wiring.append(entry)

    # Mask-mismatch honesty: an addressed interface with no proposed wire may
    # be a genuine boundary — or a typo'd mask that failed to join a peer.
    proposed = {endpoint for entry in wiring for endpoint in entry}
    for network, members in grouped.items():
        if len(members) > 1:
            continue
        node, interface = members[0]
        if f"{node}:{interface}" in proposed:
            continue
        overlapping = [
            other
            for other in grouped
            if other != network
            and ipaddress.IPv4Network(other).overlaps(ipaddress.IPv4Network(network))
        ]
        if overlapping:
            notes.append(
                Note(
                    node,
                    f"interface {interface} ({network}) overlaps {', '.join(overlapping)} but "
                    "the masks differ — no wire proposed; check for a mask typo",
                )
            )
    return WiringSuggestion(wiring=wiring, notes=tuple(notes))
