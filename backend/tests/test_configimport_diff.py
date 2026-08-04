"""The fidelity diff (delta 22): source vs running, stateless map recompute."""

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.configimport.diff import DUMP_COMMANDS, diff_node

_SOURCE = """\
hostname prod-r1
aaa new-model
interface Loopback0
 ip address 10.0.0.1 255.255.255.255
interface GigabitEthernet0/0/1
 description to r2
 ip address 10.1.2.1 255.255.255.252
 ip ospf network point-to-point
router ospf 1
 network 10.1.2.0 0.0.0.3 area 0
 passive-interface GigabitEthernet0/0/1
"""

# The lab realized Gi0/0/1 as Ethernet0/1 (address join proves it); the ospf
# stanza landed, but the passive-interface line did not.
_RUNNING = """\
hostname r1
interface Loopback0
 ip address 10.0.0.1 255.255.255.255
interface Ethernet0/1
 description to r2
 ip address 10.1.2.1 255.255.255.252
 ip ospf network point-to-point
router ospf 1
 network 10.1.2.0 0.0.0.3 area 0
username admin privilege 15 secret 5 $1$abc
"""


def test_diff_maps_by_address_and_classifies() -> None:
    outcome = diff_node("r1", "iol", _SOURCE, _RUNNING)
    assert isinstance(outcome, Ok)
    diff = outcome.value

    # The address join mapped Gi0/0/1 -> Ethernet0/1, so the interface stanza
    # and the ospf network line all match; only the passive-interface line
    # (present in source, absent in running) is missing.
    assert diff.missing == [" passive-interface Ethernet0/1"]
    assert diff.matched > 0
    # aaa was quarantined (auth), counted, not compared.
    assert diff.quarantined == 1
    # The lab's own baseline is EXTRA, informational: its hostname + user.
    assert "hostname r1" in diff.extra
    assert any(line.startswith("username admin") for line in diff.extra)


def test_diff_vyos_set_form() -> None:
    source = (
        "set interfaces ethernet eth3 address '10.1.2.1/30'\n"
        "set interfaces ethernet eth3 mtu '1400'\n"
        "set system host-name 'prod-r3'\n"
    )
    running = (
        "set interfaces ethernet eth1 address '10.1.2.1/30'\n"
        "set interfaces ethernet eth1 mtu '1400'\n"
        "set system host-name 'r3'\n"
    )
    outcome = diff_node("r3", "vyos", source, running)
    assert isinstance(outcome, Ok)
    diff = outcome.value
    assert diff.missing == []  # eth3 -> eth1 via the address join
    assert diff.matched == 2  # the hostname is excluded by construction


def test_diff_parse_errors_are_typed() -> None:
    outcome = diff_node("r1", "iol", "garbage\n", _RUNNING)
    assert isinstance(outcome, Err)
    assert "source config" in outcome.error


def test_dump_commands_cover_the_import_set() -> None:
    from twinlab_backend.services.configimport.pipeline import import_capable_devices

    assert set(DUMP_COMMANDS) == set(import_capable_devices())
