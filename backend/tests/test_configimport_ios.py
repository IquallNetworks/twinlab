"""IOS config parsing (delta 22): running-config text → the normalized model."""

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.configimport.ios import parse_ios

_RUNNING_CONFIG = """\
Building configuration...

Current configuration : 1234 bytes
!
version 15.9
service timestamps debug datetime msec
!
hostname r1
!
banner motd ^C
unauthorized access prohibited
^C
!
interface Loopback0
 ip address 10.0.0.1 255.255.255.255
!
interface Ethernet0/1
 description to r2
 ip address 10.1.2.1 255.255.255.252
 ip ospf network point-to-point
!
interface Ethernet0/2
 no ip address
 shutdown
!
interface GigabitEthernet0/0
 vrf forwarding MGMT
 ip address 192.168.1.10 255.255.255.0
 ip address 192.168.2.10 255.255.255.0 secondary
!
interface Ethernet0/1.100
 encapsulation dot1Q 100
 ip address 10.100.0.1 255.255.255.0
!
interface Port-channel1
 ip address 10.9.0.1 255.255.255.0
!
router ospf 1
 network 10.1.2.0 0.0.0.3 area 0
!
ip route 0.0.0.0 0.0.0.0 192.168.1.1
!
end
"""


def test_running_config_parses_facts_and_stanzas() -> None:
    parsed = parse_ios(_RUNNING_CONFIG)
    assert isinstance(parsed, Ok)
    source = parsed.value

    assert source.hostname == "r1"
    by_name = {i.name: i for i in source.interfaces}
    # Subinterface + Port-channel are uninferable; the rest extract.
    assert set(by_name) == {"Loopback0", "Ethernet0/1", "Ethernet0/2", "GigabitEthernet0/0"}
    assert by_name["Loopback0"].loopback is True
    assert by_name["Loopback0"].ipv4 == "10.0.0.1/32"
    assert by_name["Ethernet0/1"].ipv4 == "10.1.2.1/30"  # mask converted to CIDR
    assert by_name["Ethernet0/2"].ipv4 is None
    assert by_name["Ethernet0/2"].shutdown is True
    assert by_name["GigabitEthernet0/0"].vrf == "MGMT"
    # Secondary addresses are never the primary.
    assert by_name["GigabitEthernet0/0"].ipv4 == "192.168.1.10/24"

    assert any("Ethernet0/1.100" in w for w in source.warnings)
    assert any("Port-channel1" in w for w in source.warnings)

    # Uninferable interfaces still have their stanza (for the carry).
    keys = {s.key for s in source.stanzas}
    assert ("interface", "Port-channel1") in keys
    assert ("interface", "Ethernet0/1.100") in keys
    assert ("hostname",) in keys
    assert ("ip", "route") in keys
    assert ("version", "15.9") in keys  # version is config for the SPLIT, not framing


def test_completeness_over_config_lines() -> None:
    """Every netutils config line except dump framing lands in exactly one
    stanza, verbatim — the invariant anchor for the bucket split."""
    parsed = parse_ios(_RUNNING_CONFIG)
    assert isinstance(parsed, Ok)
    stanza_lines = [line for stanza in parsed.value.stanzas for line in stanza.lines]
    assert len(stanza_lines) == len(set(stanza_lines))
    # Spot the verbatim indentation and the multiline banner child.
    assert " ip address 10.1.2.1 255.255.255.252" in stanza_lines
    assert "unauthorized access prohibited\n^C" in stanza_lines
    # Framing is gone; `end` is gone.
    assert not any(line.startswith("Building configuration") for line in stanza_lines)
    assert "end" not in stanza_lines


def test_parse_errors_are_typed() -> None:
    for content, fragment in (
        ("", "does not look like an IOS config"),
        ("set interfaces ethernet eth1 address '10.0.0.1/30'\n", "does not look like"),
    ):
        parsed = parse_ios(content)
        assert isinstance(parsed, Err), content
        assert fragment in parsed.error.message


def test_unparseable_address_warns_and_stays_unnumbered() -> None:
    content = "hostname r1\ninterface Ethernet0/1\n ip address 10.1.2.1 bogus\n"
    parsed = parse_ios(content)
    assert isinstance(parsed, Ok)
    assert parsed.value.interfaces[0].ipv4 is None
    assert any("unparseable address" in w for w in parsed.value.warnings)
