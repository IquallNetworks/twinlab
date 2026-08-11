"""Explicit wiring, suggestion, and skeleton emission (delta 23).

Adjacency comes from the caller now; what remains automatic is per-interface
realization (loopback pins, mgmt quarantine, stubs for unwired addressed
interfaces). The integration test at the bottom is the anchor: an emitted
skeleton — mixed and L2 wires included — must pass the same dry `netlab
create` a PUT runs, with every pinned address surviving and no address
invented for the unaddressed endpoints.
"""

import yaml

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.configimport.emit import emit_definition, sanitize_node_name
from twinlab_backend.services.configimport.ios import parse_ios
from twinlab_backend.services.configimport.suggestion import suggest_wiring
from twinlab_backend.services.configimport.vyos import parse_vyos
from twinlab_backend.services.configimport.wiring import NodeSource, wire
from twinlab_backend.services.netlab import create_clab_topology

_R1 = """\
hostname r1
interface Loopback0
 ip address 10.0.0.1 255.255.255.255
interface Loopback1
 ip address 10.0.99.1 255.255.255.255
interface Ethernet0/1
 ip address 10.1.2.1 255.255.255.252
interface Ethernet0/2
 ip address 10.7.0.1 255.255.255.0
interface Ethernet0/3
 ip address 10.9.0.1 255.255.255.0
interface Ethernet0/4
 no ip address
 ip router isis CORE
interface GigabitEthernet0/0
 vrf forwarding MGMT
 ip address 192.168.1.10 255.255.255.0
"""

_R2 = """\
hostname r2
interface Loopback0
 ip address 10.0.0.2 255.255.255.255
interface Ethernet0/1
 ip address 10.1.2.2 255.255.255.252
interface Ethernet0/2
 ip address 10.7.0.2 255.255.255.0
interface Ethernet0/4
 no ip address
 ip router isis CORE
"""

_R3 = """\
set interfaces ethernet eth1 address '10.7.0.3/24'
set interfaces loopback lo address '10.0.0.3/32'
set system host-name 'r3'
"""

# The caller's wiring: the addressed p2p, the three-node LAN, and — the case
# addressing can never see — the unnumbered ISIS core link.
_WIRING = [
    ["r1:Ethernet0/1", "r2:Ethernet0/1"],
    ["r1:Ethernet0/2", "r2:Ethernet0/2", "r3:eth1"],
    ["r1:Ethernet0/4", "r2:Ethernet0/4"],
]


def _sources() -> list[NodeSource]:
    r1 = parse_ios(_R1)
    r2 = parse_ios(_R2)
    r3 = parse_vyos(_R3)
    assert isinstance(r1, Ok) and isinstance(r2, Ok) and isinstance(r3, Ok)
    return [
        NodeSource(node="r1", device="iol", parsed=r1.value, hostname="r1"),
        NodeSource(node="r2", device="iol", parsed=r2.value, hostname="r2"),
        NodeSource(node="r3", device="vyos", parsed=r3.value, hostname="r3"),
    ]


def test_wiring_builds_p2p_lan_l2_and_stubs() -> None:
    wired = wire(_sources(), _WIRING)
    assert isinstance(wired, Ok)
    topology = wired.value

    p2p, lan, l2, *rest = topology.links
    assert p2p.network == "10.1.2.0/30"
    assert {(e.node, e.interface) for e in p2p.endpoints} == {
        ("r1", "Ethernet0/1"),
        ("r2", "Ethernet0/1"),
    }
    assert lan.network == "10.7.0.0/24"
    assert {e.node for e in lan.endpoints} == {"r1", "r2", "r3"}
    # The unnumbered wire: no network at all -> an L2 link.
    assert l2.network is None
    assert all(e.ipv4 is None for e in l2.endpoints)

    # Per-interface realization, NOT adjacency: the unwired addressed
    # interface becomes a stub (with a note), loopbacks pin, mgmt quarantines.
    assert [(e.node, e.interface) for link in rest for e in link.endpoints] == [
        ("r1", "Ethernet0/3")
    ]
    assert rest[0].network == "10.9.0.0/24"
    assert any("realized as a stub" in note.message for note in topology.notes)
    assert topology.mgmt_interfaces["r1"] == frozenset({"GigabitEthernet0/0"})
    assert topology.mgmt_vrfs["r1"] == frozenset({"MGMT"})
    pins = {node: (pin.interface, pin.ipv4) for node, pin in topology.loopbacks.items()}
    assert pins == {
        "r1": ("Loopback0", "10.0.0.1/32"),
        "r2": ("Loopback0", "10.0.0.2/32"),
        "r3": ("lo", "10.0.0.3/32"),
    }
    assert any("Loopback1" in note.message for note in topology.notes)


def test_wiring_accepts_source_hostnames_and_empty_lists() -> None:
    r1 = parse_ios("hostname prod-r1\ninterface Ethernet0/1\n ip address 10.1.2.1 255.255.255.0\n")
    r2 = parse_ios("hostname prod-r2\ninterface Ethernet0/1\n ip address 10.1.2.2 255.255.255.0\n")
    assert isinstance(r1, Ok) and isinstance(r2, Ok)
    sources = [
        NodeSource(node="prod_r1", device="iol", parsed=r1.value, hostname="prod-r1"),
        NodeSource(node="prod_r2", device="iol", parsed=r2.value, hostname="prod-r2"),
    ]
    # The SOURCE hostname resolves, so a wiring list written against the
    # config files works without knowing the sanitized names.
    wired = wire(sources, [["prod-r1:Ethernet0/1", "prod_r2:Ethernet0/1"]])
    assert isinstance(wired, Ok)
    assert len(wired.value.links) == 1
    assert {e.node for e in wired.value.links[0].endpoints} == {"prod_r1", "prod_r2"}

    # No wiring at all is legal: every addressed interface is then a stub.
    empty = wire(sources, [])
    assert isinstance(empty, Ok)
    assert all(len(link.endpoints) == 1 for link in empty.value.links)
    assert len(empty.value.links) == 2


def test_wiring_validation_errors() -> None:
    sources = _sources()
    cases: list[tuple[list[list[str]], str, str]] = [
        ([["r1:Ethernet0/1"]], "wiring_invalid", "at least two"),
        ([["r1Ethernet0/1", "r2:Ethernet0/1"]], "wiring_invalid", "not a 'node:interface'"),
        ([["ghost:Ethernet0/1", "r2:Ethernet0/1"]], "wiring_invalid", "no imported source"),
        ([["r1:Ethernet9/9", "r2:Ethernet0/1"]], "wiring_invalid", "no wireable interface"),
        ([["r1:Loopback0", "r2:Ethernet0/1"]], "wiring_invalid", "is a loopback"),
        (
            [["r1:GigabitEthernet0/0", "r2:Ethernet0/1"]],
            "wiring_invalid",
            "management-VRF interface",
        ),
        ([["r1:Ethernet0/1", "r1:Ethernet0/2"]], "wiring_invalid", "appears twice on one link"),
        (
            [["r1:Ethernet0/1", "r2:Ethernet0/1"], ["r1:Ethernet0/1", "r2:Ethernet0/4"]],
            "wiring_invalid",
            "wired more than once",
        ),
        # The mask-typo case: asserted wiring turns it into an error.
        ([["r1:Ethernet0/1", "r2:Ethernet0/2"]], "wiring_conflict", "different subnets"),
    ]
    for entries, code, fragment in cases:
        wired = wire(sources, entries)
        assert isinstance(wired, Err), entries
        assert wired.error.code == code, entries
        assert fragment in wired.error.message, wired.error.message
        assert wired.error.entry is not None


def test_suggestion_proposes_the_subnet_join_and_warns_about_the_rest() -> None:
    suggestion = suggest_wiring(_sources())
    # Proposals are spelled in the wiring format, final node names.
    assert ["r1:Ethernet0/1", "r2:Ethernet0/1"] in suggestion.wiring
    lan = next(entry for entry in suggestion.wiring if len(entry) == 3)
    assert set(lan) == {"r1:Ethernet0/2", "r2:Ethernet0/2", "r3:eth1"}
    # Single-member subnets are NOT proposed (they become stubs by default).
    assert not any("Ethernet0/3" in endpoint for entry in suggestion.wiring for endpoint in entry)
    # What the join cannot see is exactly what it warns about.
    assert any(
        "unnumbered" in note.message and "Ethernet0/4" in note.message for note in suggestion.notes
    )
    # Feeding the suggestion straight back is accepted by the wiring rules.
    accepted = wire(_sources(), suggestion.wiring)
    assert isinstance(accepted, Ok)


def test_sanitize_node_name() -> None:
    assert sanitize_node_name("r1") == "r1"
    # Hyphens are legal netlab identifiers, so a hyphenated hostname is NOT a
    # rename; only the dots have to go.
    assert sanitize_node_name("core-rtr-01") == "core-rtr-01"
    assert sanitize_node_name("edge.example") == "edge_example"
    assert sanitize_node_name("_edge") == "n_edge"  # `_Name` starts alphanumeric
    assert sanitize_node_name("9leading") == "n9leading"  # netlab ids start with a letter
    assert sanitize_node_name("prefix") == "n_prefix"  # reserved link-attr word
    # netlab's id cap, not an arbitrary bound: a longer name fails the dry
    # `netlab create` the import runs.
    assert sanitize_node_name("x" * 100) == "x" * 16


def test_emitted_skeleton_shape() -> None:
    sources = _sources()
    wired = wire(sources, _WIRING)
    assert isinstance(wired, Ok)
    definition = emit_definition(sources, wired.value, carry_nodes=frozenset({"r1", "r3"}))
    doc = yaml.safe_load(definition)

    assert doc["provider"] == "clab"
    assert doc["nodes"]["r1"] == {
        "device": "iol",
        "loopback": {"ipv4": "10.0.0.1/32"},
        # The NAME form (delta 27): netlab resolves it per node to
        # imported/<node>.j2 at push AND create-time validation.
        "config": ["imported"],
    }
    assert "config" not in doc["nodes"]["r2"]  # empty carry -> no reference
    p2p = next(link for link in doc["links"] if link.get("prefix") == "10.1.2.0/30")
    assert p2p["r1"] == {"ipv4": "10.1.2.1/30"}
    # The L2 wire: prefix false AND every endpoint ipv4 false — bare would
    # make netlab INVENT addresses (live-proven).
    l2 = next(link for link in doc["links"] if link.get("prefix") is False)
    assert l2["r1"] == {"ipv4": False}
    assert l2["r2"] == {"ipv4": False}
    # No modules, no name, no mgmt addressing — the thin skeleton.
    assert "module" not in definition
    assert "name" not in doc
    assert "addressing" not in doc


def test_emitted_skeleton_passes_netlab_create() -> None:
    """The anchor: the emitted skeleton — mixed and L2 wires included —
    survives the same dry create a PUT runs, every pinned address holds, and
    nothing is invented for the unaddressed endpoints."""
    sources = _sources()
    # A MIXED wire: r1's addressed Ethernet0/3 against r2's unnumbered one.
    mixed = [_WIRING[0], _WIRING[1], ["r1:Ethernet0/3", "r2:Ethernet0/4"]]
    wired = wire(sources, mixed)
    assert isinstance(wired, Ok)
    definition = emit_definition(sources, wired.value, carry_nodes=frozenset({"r1"}))
    created = create_clab_topology(definition, {"imported/r1.j2": "! placeholder\n"})
    assert isinstance(created, Ok), getattr(created, "error", None)

    addressed = {
        (endpoint.node, endpoint.ipv4)
        for link in created.value.links
        for endpoint in link.endpoints
        if endpoint.ipv4 is not None
    }
    assert ("r1", "10.1.2.1/30") in addressed
    assert ("r3", "10.7.0.3/24") in addressed
    assert ("r1", "10.9.0.1/24") in addressed  # the mixed wire keeps its pin
    # r2's unnumbered endpoint on that mixed wire got NO invented address.
    assert not any(node == "r2" and address.startswith("10.9.") for node, address in addressed)
