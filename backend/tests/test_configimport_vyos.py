"""VyOS config parsing (delta 22): both dump formats normalize to one model.

The completeness anchor for the three-bucket split lives here: every input
set-line must land in exactly one stanza, verbatim.
"""

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.configimport.vyos import parse_vyos

# `show configuration commands` style — values single-quoted, flat.
_SET_FORM = """\
set interfaces ethernet eth1 address '10.1.2.1/30'
set interfaces ethernet eth1 description 'to r2'
set interfaces ethernet eth2 address '10.1.3.1/24'
set interfaces ethernet eth2 disable
set interfaces ethernet eth3 vrf 'MGMT'
set interfaces ethernet eth3 address '172.16.0.9/24'
set interfaces loopback lo address '10.0.0.1/32'
set protocols ospf area 0 network '10.1.2.0/30'
set system host-name 'r1'
set system login user vyos authentication encrypted-password '$6$abc'
set system ntp server 'ntp.example.com'
set service snmp community 'public'
"""

# The same config as `show configuration` would print it.
_BRACE_FORM = """\
interfaces {
    ethernet eth1 {
        address 10.1.2.1/30
        description "to r2"
    }
    ethernet eth2 {
        address 10.1.3.1/24
        disable
    }
    ethernet eth3 {
        vrf MGMT
        address 172.16.0.9/24
    }
    loopback lo {
        address 10.0.0.1/32
    }
}
protocols {
    ospf {
        area 0 {
            network 10.1.2.0/30
        }
    }
}
system {
    host-name r1
    login {
        user vyos {
            authentication {
                encrypted-password "$6$abc"
            }
        }
    }
    ntp {
        server ntp.example.com
    }
}
service {
    snmp {
        community public
    }
}
"""


def test_set_form_parses_facts_and_stanzas() -> None:
    parsed = parse_vyos(_SET_FORM)
    assert isinstance(parsed, Ok)
    source = parsed.value

    assert source.hostname == "r1"
    by_name = {i.name: i for i in source.interfaces}
    assert set(by_name) == {"eth1", "eth2", "eth3", "lo"}
    assert by_name["eth1"].ipv4 == "10.1.2.1/30"
    assert by_name["eth1"].shutdown is False
    assert by_name["eth2"].shutdown is True
    assert by_name["eth3"].vrf == "MGMT"
    assert by_name["lo"].loopback is True
    assert by_name["lo"].ipv4 == "10.0.0.1/32"

    # Every input line lands in exactly one stanza, verbatim.
    input_lines = [line for line in _SET_FORM.splitlines() if line]
    stanza_lines = [line for stanza in source.stanzas for line in stanza.lines]
    assert sorted(stanza_lines) == sorted(input_lines)
    assert len(stanza_lines) == len(set(stanza_lines))

    # Grouping: per-interface stanzas; system splits one level deeper.
    keys = {stanza.key for stanza in source.stanzas}
    assert ("interfaces", "ethernet", "eth1") in keys
    assert ("system", "host-name") in keys
    assert ("system", "login") in keys
    assert ("system", "ntp") in keys
    assert ("service", "snmp") in keys
    assert ("protocols",) in keys
    hostname_stanzas = [s for s in source.stanzas if s.kind == "hostname"]
    assert len(hostname_stanzas) == 1
    eth1 = next(s for s in source.stanzas if s.key == ("interfaces", "ethernet", "eth1"))
    assert eth1.kind == "interface"
    assert eth1.interface == "eth1"


def test_brace_form_extracts_the_same_facts() -> None:
    parsed = parse_vyos(_BRACE_FORM)
    assert isinstance(parsed, Ok)
    source = parsed.value

    assert source.hostname == "r1"
    by_name = {i.name: i for i in source.interfaces}
    assert set(by_name) == {"eth1", "eth2", "eth3", "lo"}
    assert by_name["eth1"].ipv4 == "10.1.2.1/30"
    assert by_name["eth2"].shutdown is True
    assert by_name["eth3"].vrf == "MGMT"
    assert by_name["lo"].loopback is True

    # Same stanza keys as the set form — the normalization is one model.
    set_parsed = parse_vyos(_SET_FORM)
    assert isinstance(set_parsed, Ok)
    assert {s.key for s in source.stanzas} == {s.key for s in set_parsed.value.stanzas}

    # Normalized lines are set commands (quotes preserved as written).
    login = next(s for s in source.stanzas if s.key == ("system", "login"))
    assert login.lines == ('set system login user vyos authentication encrypted-password "$6$abc"',)


def test_empty_brace_section_is_kept() -> None:
    parsed = parse_vyos("interfaces {\n    loopback lo {\n    }\n}\n")
    assert isinstance(parsed, Ok)
    lo = next(s for s in parsed.value.stanzas if s.kind == "interface")
    assert lo.lines == ("set interfaces loopback lo",)
    assert parsed.value.interfaces[0].name == "lo"
    assert parsed.value.interfaces[0].ipv4 is None


def test_uninferable_types_and_vifs_warn_but_stay() -> None:
    content = (
        "set interfaces bonding bond0 address '10.9.0.1/24'\n"
        "set interfaces ethernet eth1 vif 100 address '10.8.0.1/24'\n"
        "set interfaces ethernet eth1 address '10.1.2.1/30'\n"
    )
    parsed = parse_vyos(content)
    assert isinstance(parsed, Ok)
    source = parsed.value
    # bond0 is not inferable; eth1 is — and its vif address is NOT its address.
    assert [i.name for i in source.interfaces] == ["eth1"]
    assert source.interfaces[0].ipv4 == "10.1.2.1/30"
    assert any("bonding" in w for w in source.warnings)
    assert any("vif 100" in w for w in source.warnings)
    # The uninferable stanza is still present for the carry.
    assert any(s.key == ("interfaces", "bonding", "bond0") for s in source.stanzas)


def test_dhcp_and_ipv6_addresses_are_not_the_primary_ipv4() -> None:
    content = (
        "set interfaces ethernet eth1 address 'dhcp'\n"
        "set interfaces ethernet eth2 address '2001:db8::1/64'\n"
        "set interfaces ethernet eth2 address '10.1.2.1/30'\n"
    )
    parsed = parse_vyos(content)
    assert isinstance(parsed, Ok)
    by_name = {i.name: i for i in parsed.value.interfaces}
    assert by_name["eth1"].ipv4 is None
    assert by_name["eth2"].ipv4 == "10.1.2.1/30"


def test_parse_errors_are_typed() -> None:
    for content, fragment in (
        ("", "no configuration lines"),
        ("hostname r1\nno ip domain lookup\n", "not a VyOS config"),
        ("set\n", "bare `set` with no path"),
        ("interfaces {\n    ethernet eth1 {\n", "unbalanced '{'"),
        ("interfaces {\n}\n}\n", "unbalanced '}'"),
    ):
        parsed = parse_vyos(content)
        assert isinstance(parsed, Err), content
        assert fragment in parsed.error.message
