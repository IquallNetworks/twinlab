"""Link inference + skeleton emission (delta 22).

The integration test at the bottom is the anchor: an emitted skeleton must
pass the same dry `netlab create` a PUT runs, with every pinned address
surviving expansion.
"""

import yaml

from twinlab_backend.result import Ok
from twinlab_backend.services.configimport.emit import emit_definition, sanitize_node_name
from twinlab_backend.services.configimport.inference import NodeSource, infer
from twinlab_backend.services.configimport.ios import parse_ios
from twinlab_backend.services.configimport.vyos import parse_vyos
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
 ip address 10.4.0.1 255.255.255.240
"""

_R3 = """\
set interfaces ethernet eth1 address '10.7.0.3/24'
set interfaces ethernet eth2 address '10.4.0.2/28'
set interfaces loopback lo address '10.0.0.3/32'
set system host-name 'r3'
"""


def _sources() -> list[NodeSource]:
    r1 = parse_ios(_R1)
    r2 = parse_ios(_R2)
    r3 = parse_vyos(_R3)
    assert isinstance(r1, Ok) and isinstance(r2, Ok) and isinstance(r3, Ok)
    return [
        NodeSource(node="r1", device="iol", parsed=r1.value),
        NodeSource(node="r2", device="iol", parsed=r2.value),
        NodeSource(node="r3", device="vyos", parsed=r3.value),
    ]


def test_subnet_join_p2p_lan_and_stub() -> None:
    inference = infer(_sources())
    by_network = {link.network: link for link in inference.links}

    p2p = by_network["10.1.2.0/30"]
    assert {(e.node, e.interface) for e in p2p.endpoints} == {
        ("r1", "Ethernet0/1"),
        ("r2", "Ethernet0/1"),
    }
    lan = by_network["10.7.0.0/24"]
    assert {e.node for e in lan.endpoints} == {"r1", "r2", "r3"}
    cross = by_network["10.4.0.0/28"]  # IOS + VyOS join on one subnet
    assert {e.node for e in cross.endpoints} == {"r2", "r3"}
    stub = by_network["10.9.0.0/24"]
    assert [(e.node, e.interface) for e in stub.endpoints] == [("r1", "Ethernet0/3")]

    # The mgmt-VRF interface never joins; loopbacks pin (first only).
    assert inference.mgmt_interfaces["r1"] == frozenset({"GigabitEthernet0/0"})
    assert inference.mgmt_vrfs["r1"] == frozenset({"MGMT"})
    pins = {node: (pin.interface, pin.ipv4) for node, pin in inference.loopbacks.items()}
    assert pins == {
        "r1": ("Loopback0", "10.0.0.1/32"),
        "r2": ("Loopback0", "10.0.0.2/32"),
        "r3": ("lo", "10.0.0.3/32"),
    }
    assert any("Loopback1" in n.message for n in inference.notes if n.node == "r1")


def test_self_subnet_and_overlap_notes() -> None:
    content = (
        "hostname r9\n"
        "interface Ethernet0/1\n ip address 10.5.0.1 255.255.255.0\n"
        "interface Ethernet0/2\n ip address 10.5.0.2 255.255.255.0\n"
        "interface Ethernet0/3\n ip address 10.1.2.5 255.255.255.0\n"
    )
    other = "hostname r8\ninterface Ethernet0/1\n ip address 10.1.2.6 255.255.255.252\n"
    r9 = parse_ios(content)
    r8 = parse_ios(other)
    assert isinstance(r9, Ok) and isinstance(r8, Ok)
    inference = infer(
        [
            NodeSource(node="r9", device="iol", parsed=r9.value),
            NodeSource(node="r8", device="iol", parsed=r8.value),
        ]
    )
    # Same node twice in 10.5.0.0/24: second interface becomes its own stub.
    tens = [link for link in inference.links if link.network == "10.5.0.0/24"]
    assert sorted(len(link.endpoints) for link in tens) == [1, 1]
    assert any("shares subnet" in n.message for n in inference.notes)
    # Mask mismatch: /24 vs /30 overlap → note, not a join.
    assert any("masks differ" in n.message for n in inference.notes)


def test_unnumbered_up_interface_notes() -> None:
    parsed = parse_ios("hostname r1\ninterface Ethernet0/1\n no ip address\n")
    down = parse_ios("hostname r2\ninterface Ethernet0/1\n no ip address\n shutdown\n")
    assert isinstance(parsed, Ok) and isinstance(down, Ok)
    inference = infer([NodeSource(node="r1", device="iol", parsed=parsed.value)])
    assert any("unnumbered" in n.message for n in inference.notes)
    inference = infer([NodeSource(node="r2", device="iol", parsed=down.value)])
    assert not inference.notes  # a shut, unused port is not a finding


def test_sanitize_node_name() -> None:
    assert sanitize_node_name("core-rtr-01.example.com") == "core_rtr_01_example_com"
    assert sanitize_node_name("r1") == "r1"
    assert sanitize_node_name("_edge") == "n_edge"
    assert sanitize_node_name("prefix") == "n_prefix"  # reserved link-attr word
    assert len(sanitize_node_name("x" * 100)) == 64


def test_emitted_skeleton_shape() -> None:
    sources = _sources()
    inference = infer(sources)
    definition = emit_definition(sources, inference, carry_nodes=frozenset({"r1", "r3"}))
    doc = yaml.safe_load(definition)

    assert doc["provider"] == "clab"
    assert doc["nodes"]["r1"] == {
        "device": "iol",
        "loopback": {"ipv4": "10.0.0.1/32"},
        "config": ["imported/r1.j2"],
    }
    assert "config" not in doc["nodes"]["r2"]  # empty carry -> no reference
    networks = {link["prefix"] for link in doc["links"]}
    assert networks == {"10.1.2.0/30", "10.4.0.0/28", "10.7.0.0/24", "10.9.0.0/24"}
    p2p = next(link for link in doc["links"] if link["prefix"] == "10.1.2.0/30")
    assert p2p["r1"] == {"ipv4": "10.1.2.1/30"}
    # No modules, no name, no mgmt addressing — the thin skeleton.
    assert "module" not in definition
    assert "name" not in doc
    assert "addressing" not in doc


def test_emitted_skeleton_passes_netlab_create() -> None:
    """The anchor: the emitted skeleton survives the same dry create a PUT
    runs, and every pinned address survives netlab's expansion."""
    sources = _sources()
    inference = infer(sources)
    definition = emit_definition(sources, inference, carry_nodes=frozenset({"r1"}))
    created = create_clab_topology(definition, {"imported/r1.j2": "! placeholder\n"})
    assert isinstance(created, Ok), getattr(created, "error", None)

    pinned = {
        (endpoint.node, endpoint.ipv4)
        for link in created.value.links
        for endpoint in link.endpoints
        if endpoint.ipv4 is not None
    }
    assert ("r1", "10.1.2.1/30") in pinned
    assert ("r3", "10.7.0.3/24") in pinned
    assert ("r1", "10.9.0.1/24") in pinned  # the stub keeps its address
