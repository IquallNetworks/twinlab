"""Bucket split, interface rewrite, and the full import pipeline (delta 22).

The completeness invariant — modeled, carried and quarantined partition the
source — is asserted here at the classify layer, and the pipeline test runs
the real dry `netlab create` (the same one a PUT runs).
"""

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.configimport.classify import (
    IOS_CLASSIFY,
    VYOS_CLASSIFY,
    split_buckets,
)
from twinlab_backend.services.configimport.ios import parse_ios
from twinlab_backend.services.configimport.pipeline import (
    ImportSourceSpec,
    import_network,
    import_node,
)
from twinlab_backend.services.configimport.rewrite import rewrite_ios, rewrite_vyos
from twinlab_backend.services.configimport.vyos import parse_vyos

_IOS = """\
hostname r1
version 15.9
aaa new-model
ntp server 192.0.2.1
interface Loopback0
 ip address 10.0.0.1 255.255.255.255
interface Ethernet0/1
 description to r2
 ip address 10.1.2.1 255.255.255.252
 ip ospf network point-to-point
interface Ethernet0/2
 ip address 10.9.0.1 255.255.255.0
interface GigabitEthernet0/0
 vrf forwarding MGMT
 ip address 192.168.1.10 255.255.255.0
vrf definition MGMT
 address-family ipv4
ip route vrf MGMT 0.0.0.0 0.0.0.0 192.168.1.1
ip route 10.99.0.0 255.255.0.0 10.1.2.2
router ospf 1
 network 10.1.2.0 0.0.0.3 area 0
"""


def _ios_split():
    parsed = parse_ios(_IOS)
    assert isinstance(parsed, Ok)
    return parsed.value, split_buckets(
        parsed.value,
        spec=IOS_CLASSIFY,
        modeled_addresses={
            "Loopback0": "10.0.0.1/32",
            "Ethernet0/1": "10.1.2.1/30",
            "Ethernet0/2": "10.9.0.1/24",
        },
        mgmt_interfaces=frozenset({"GigabitEthernet0/0"}),
        mgmt_vrfs=frozenset({"MGMT"}),
    )


def test_ios_bucket_split() -> None:
    _, split = _ios_split()

    assert "hostname r1" in split.modeled
    assert " ip address 10.1.2.1 255.255.255.252" in split.modeled
    # An interface fully consumed by the skeleton takes its header along.
    assert "interface Loopback0" in split.modeled
    assert "interface Ethernet0/2" in split.modeled

    carried_lines = [line for block in split.carried for line in block.lines]
    assert "interface Ethernet0/1" in carried_lines  # header follows its content
    assert " ip ospf network point-to-point" in carried_lines
    assert "router ospf 1" in carried_lines
    assert "ip route 10.99.0.0 255.255.0.0 10.1.2.2" in carried_lines  # non-mgmt route

    reasons = {block.reason for block in split.quarantined}
    assert reasons == {"auth", "telemetry", "hardware", "mgmt"}
    quarantined_lines = [line for block in split.quarantined for line in block.lines]
    assert "interface GigabitEthernet0/0" in quarantined_lines
    assert "vrf definition MGMT" in quarantined_lines
    assert "ip route vrf MGMT 0.0.0.0 0.0.0.0 192.168.1.1" in quarantined_lines
    assert "version 15.9" in quarantined_lines


def test_bucket_split_is_a_partition() -> None:
    parsed, split = _ios_split()
    everything = sorted(line for stanza in parsed.stanzas for line in stanza.lines)
    bucketed = sorted(
        [
            *split.modeled,
            *(line for block in split.carried for line in block.lines),
            *(line for block in split.quarantined for line in block.lines),
        ]
    )
    assert bucketed == everything


def test_vyos_bucket_split() -> None:
    content = (
        "set interfaces ethernet eth1 address '10.1.2.1/30'\n"
        "set interfaces ethernet eth1 description 'to r2'\n"
        "set system host-name 'r3'\n"
        "set system login user vyos authentication encrypted-password '$6$x'\n"
        "set system ntp server 'ntp.example.com'\n"
        "set protocols ospf area 0 network '10.1.2.0/30'\n"
    )
    parsed = parse_vyos(content)
    assert isinstance(parsed, Ok)
    split = split_buckets(
        parsed.value,
        spec=VYOS_CLASSIFY,
        modeled_addresses={"eth1": "10.1.2.1/30"},
        mgmt_interfaces=frozenset(),
        mgmt_vrfs=frozenset(),
    )
    assert "set interfaces ethernet eth1 address '10.1.2.1/30'" in split.modeled
    assert "set system host-name 'r3'" in split.modeled
    carried = [line for block in split.carried for line in block.lines]
    assert "set interfaces ethernet eth1 description 'to r2'" in carried
    assert "set protocols ospf area 0 network '10.1.2.0/30'" in carried
    assert {block.reason for block in split.quarantined} == {"auth", "telemetry"}


def test_rewrite_ios_variants_and_no_cascade() -> None:
    lines = (
        "interface Ethernet0/2",
        " ip ospf cost 10",
        "router ospf 1",
        " passive-interface Gi0/0/1",
        "ip route 10.0.0.0 255.0.0.0 Ethernet0/1",
    )
    # A shifted map: Ethernet0/2 -> Ethernet0/1 AND Ethernet0/1 -> Ethernet0/3.
    mapping = {
        "Ethernet0/2": "Ethernet0/1",
        "Ethernet0/1": "Ethernet0/3",
        "GigabitEthernet0/0/1": "Ethernet0/2",
    }
    rewritten, notes = rewrite_ios(lines, mapping, "r1")
    assert rewritten[0] == "interface Ethernet0/1"  # not re-replaced to 0/3
    assert rewritten[3] == " passive-interface Ethernet0/2"  # abbreviation resolved
    assert rewritten[4] == "ip route 10.0.0.0 255.0.0.0 Ethernet0/3"
    assert notes == []


def test_rewrite_ios_leftover_notes() -> None:
    rewritten, notes = rewrite_ios((" passive-interface Serial0/1/0",), {}, "r1")
    assert rewritten == (" passive-interface Serial0/1/0",)
    assert len(notes) == 1
    assert "Serial0/1/0" in notes[0].message


def test_rewrite_vyos_types_and_quotes() -> None:
    lines = (
        "set interfaces ethernet eth2 description 'stub side'",
        "set interfaces ethernet eth1 mtu '1400'",
        "set protocols ospf interface 'eth1' passive",
        "set protocols ospf interface eth7 cost '5'",
    )
    mapping = {"eth1": "eth1", "eth2": "dum1", "lo": "dum0"}
    rewritten, notes = rewrite_vyos(lines, mapping, "r3")
    assert rewritten[0] == "set interfaces dummy dum1 description 'stub side'"
    assert rewritten[1] == "set interfaces ethernet eth1 mtu '1400'"
    assert rewritten[2] == "set protocols ospf interface 'eth1' passive"
    assert rewritten[3] == "set protocols ospf interface eth7 cost '5'"
    assert len(notes) == 1 and "eth7" in notes[0].message


_R2_IOS = """\
hostname r2
interface Loopback0
 ip address 10.0.0.2 255.255.255.255
interface Ethernet0/1
 ip address 10.1.2.2 255.255.255.252
 ip ospf cost 20
"""

_R3_VYOS = """\
set interfaces ethernet eth1 address '10.7.0.3/24'
set interfaces ethernet eth1 description 'lan leg'
set interfaces loopback lo address '10.0.0.3/32'
set system host-name 'r3-vyos'
set system login user vyos authentication encrypted-password '$6$x'
"""


# The caller's wiring (delta 23): only the p2p between the two IOL routers.
# r1's Ethernet0/2 and r3's eth1 are deliberately left out — an addressed
# interface in no wire is per-interface realization, not adjacency, so each
# must come out a stub (r3's realizing as a VyOS dummy).
_WIRING = [["r1:Ethernet0/1", "r2:Ethernet0/1"]]


def test_import_network_end_to_end() -> None:
    """The whole factory against the real dry netlab create."""
    outcome = import_network(
        [
            ImportSourceSpec(device="iol", content=_IOS),
            ImportSourceSpec(device="iol", content=_R2_IOS),
            ImportSourceSpec(device="vyos", content=_R3_VYOS),
        ],
        _WIRING,
    )
    assert isinstance(outcome, Ok), getattr(outcome, "error", None)
    result = outcome.value

    # Node names, recorded. A hyphenated hostname is a legal netlab identifier,
    # so it survives the whole factory unrenamed — through the dry create, the
    # interface map and the carry rewrite below.
    assert result.name_map == {"r1": "r1", "r2": "r2", "r3-vyos": "r3-vyos"}
    assert "r3-vyos:" in result.definition

    # Identity maps for same-platform interfaces; loopbacks resolve to the
    # netlab realization (VyOS loopback pin lands on dum0 — probed live).
    assert result.interface_map["r1"]["Ethernet0/1"] == "Ethernet0/1"
    assert result.interface_map["r1"]["Loopback0"] == "Loopback0"
    assert result.interface_map["r3-vyos"]["lo"] == "dum0"
    assert "GigabitEthernet0/0" not in result.interface_map["r1"]  # mgmt never maps

    # Carry: rewritten, raw-wrapped node variants of ONE `imported` record
    # (delta 27), referenced by name from the definition.
    records = {record.name: record for record in result.custom_config}
    carries = {v.node: v.source for v in records["imported"].variants}
    r1_carry = carries["r1"]
    assert r1_carry is not None and r1_carry.startswith("{% raw %}")
    assert " ip ospf network point-to-point" in r1_carry
    assert "ip address 10.1.2.1" not in r1_carry  # modeled, not carried
    assert "- imported" in result.definition
    # r3's eth1 has no subnet peer -> stub -> netlab realizes it as a dummy;
    # the carry followed the map, type segment included.
    assert result.interface_map["r3-vyos"]["eth1"] == "dum1"
    vyos_carry = carries["r3-vyos"]
    assert vyos_carry is not None
    assert "set interfaces dummy dum1 description 'lan leg'" in vyos_carry

    # Quarantine: classified AND kept as unattached node variants.
    assert {q.reason for q in result.quarantine["r1"]} >= {"mgmt", "auth", "telemetry"}
    quarantines = {v.node for v in records["imported_quarantine"].variants}
    assert "r1" in quarantines
    assert "imported_quarantine" not in result.definition
    assert any(q.reason == "auth" for q in result.quarantine["r3-vyos"])


def test_import_network_problems() -> None:
    bad_device = import_network([ImportSourceSpec(device="linux", content="hostname x\n")], [])
    assert isinstance(bad_device, Err) and bad_device.error.code == "unsupported_device"

    unparseable = import_network([ImportSourceSpec(device="vyos", content="garbage here\n")], [])
    assert isinstance(unparseable, Err) and unparseable.error.code == "config_unparseable"

    no_name = import_network(
        [
            ImportSourceSpec(
                device="iol", content="interface Ethernet0/1\n ip address 10.0.0.1 255.255.255.0\n"
            )
        ],
        [],
    )
    assert isinstance(no_name, Err) and no_name.error.code == "config_unparseable"

    # Wiring problems surface through the same factory result (delta 23).
    conflicting = import_network(
        [
            ImportSourceSpec(device="iol", content=_IOS),
            ImportSourceSpec(device="iol", content=_R2_IOS),
        ],
        [["r1:Ethernet0/2", "r2:Ethernet0/1"]],
    )
    assert isinstance(conflicting, Err)
    assert conflicting.error.code == "wiring_conflict"
    assert conflicting.error.entry == 0

    duplicate = import_network(
        [
            ImportSourceSpec(device="iol", content="hostname r.1\ninterface Ethernet0/1\n"),
            ImportSourceSpec(device="iol", content="hostname r_1\ninterface Ethernet0/1\n"),
        ],
        [],
    )
    assert isinstance(duplicate, Err) and duplicate.error.code == "duplicate_node"

    # The collision a caller never typed: two hostnames past netlab's
    # 16-character id cap that truncate onto each other. The message has to
    # name the cap and the way out.
    truncated = import_network(
        [
            ImportSourceSpec(
                device="iol", content="hostname datacenter-core-rtr-1\ninterface Ethernet0/1\n"
            ),
            ImportSourceSpec(
                device="iol", content="hostname datacenter-core-rtr-2\ninterface Ethernet0/1\n"
            ),
        ],
        [],
    )
    assert isinstance(truncated, Err) and truncated.error.code == "duplicate_node"
    assert "16 characters" in truncated.error.message


def test_import_node() -> None:
    outcome = import_node("iol", _IOS)
    assert isinstance(outcome, Ok)
    result = outcome.value

    assert "device: iol" in result.fragment
    assert "ipv4: 10.0.0.1/32" in result.fragment  # loopback pin modeled
    # Non-loopback, non-mgmt interfaces listed for wiring.
    assert result.interfaces == {"Ethernet0/1": "10.1.2.1/30", "Ethernet0/2": "10.9.0.1/24"}
    # Carry keeps SOURCE names (no inference), flagged by the QUIRK note.
    assert "interface Ethernet0/1" in result.config
    assert any("SOURCE interface names" in n.message for n in result.warnings)
    assert any(q.reason == "mgmt" for q in result.quarantine)
