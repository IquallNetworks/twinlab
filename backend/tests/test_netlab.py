from twinlab_backend.result import Err, Ok
from twinlab_backend.services.netlab import (
    create_clab_topology,
    read_lab_name,
    read_mgmt_subnet,
    set_lab_name,
    set_mgmt_subnet,
    strip_generated_binds,
)

# device and provider are stated explicitly — Twinlab never defaults them.
_VALID_DEFINITION = """\
provider: clab
defaults.device: vyos
nodes: [r1, r2]
links: [r1-r2]
"""


def test_create_generates_clab_topology() -> None:
    result = create_clab_topology(_VALID_DEFINITION)
    assert isinstance(result, Ok), result
    # A containerlab topology is a mapping with a `topology` section.
    assert "topology" in result.value


def test_create_reports_error_on_invalid_definition() -> None:
    result = create_clab_topology("nodes: [r1]\nlinks: [r1-nonexistent]\n")
    assert isinstance(result, Err)


def test_read_lab_name_returns_none_when_absent() -> None:
    assert read_lab_name(_VALID_DEFINITION) is None
    assert read_lab_name("name: lab-7\nnodes: [r1]\n") == "lab-7"


def test_set_lab_name_injects_and_overrides() -> None:
    injected = set_lab_name(_VALID_DEFINITION, "tl-abc123")
    assert isinstance(injected, Ok), injected
    assert read_lab_name(injected.value) == "tl-abc123"
    # dotted-key shorthand and the other keys survive the round-trip
    assert "defaults.device" in injected.value

    overridden = set_lab_name("name: old\nnodes: [r1]\n", "new")
    assert isinstance(overridden, Ok), overridden
    assert read_lab_name(overridden.value) == "new"


def test_set_lab_name_rejects_non_mapping() -> None:
    assert isinstance(set_lab_name("- just\n- a\n- list\n", "x"), Err)


def test_read_mgmt_subnet_returns_none_when_absent() -> None:
    assert read_mgmt_subnet(_VALID_DEFINITION) is None
    explicit = "addressing:\n  mgmt:\n    ipv4: 10.9.0.0/24\nnodes: [r1]\n"
    assert read_mgmt_subnet(explicit) == "10.9.0.0/24"


def test_set_mgmt_subnet_injects_ipv4_and_network() -> None:
    injected = set_mgmt_subnet(_VALID_DEFINITION, "10.77.3.0/24", "tl-abc_mgmt")
    assert isinstance(injected, Ok), injected
    assert read_mgmt_subnet(injected.value) == "10.77.3.0/24"
    assert "tl-abc_mgmt" in injected.value
    # the original keys survive the round-trip
    assert "defaults.device" in injected.value


def test_set_mgmt_subnet_preserves_explicit_network() -> None:
    definition = "addressing:\n  mgmt:\n    _network: custom_net\nnodes: [r1]\n"
    injected = set_mgmt_subnet(definition, "10.77.4.0/24", "tl-def_mgmt")
    assert isinstance(injected, Ok), injected
    # an explicitly-set _network is honored; only ipv4 is (re)assigned
    assert "custom_net" in injected.value
    assert "tl-def_mgmt" not in injected.value
    assert read_mgmt_subnet(injected.value) == "10.77.4.0/24"


def test_set_mgmt_subnet_rejects_non_mapping_addressing() -> None:
    assert isinstance(set_mgmt_subnet("addressing: not-a-map\n", "10.0.0.0/24", "n"), Err)


def test_strip_generated_binds_drops_node_files_binds() -> None:
    # A cisco_iol-style topology: pe1 binds only its generated ifstate; p1 also
    # has a genuine host bind (which must survive); r1 has none.
    topology: dict[str, object] = {
        "name": "lab",
        "topology": {
            "nodes": {
                "pe1": {"kind": "cisco_iol", "binds": ["node_files/pe1/ifstate:/iol/ifstate.cfg"]},
                "p1": {
                    "kind": "cisco_iol",
                    "binds": ["node_files/p1/ifstate:/iol/ifstate.cfg", "/etc/hosts:/etc/hosts:ro"],
                },
                "r1": {"kind": "vyos"},
            }
        },
    }
    expected: dict[str, object] = {
        "name": "lab",
        "topology": {
            "nodes": {
                # pe1's only bind was generated -> the key is dropped entirely.
                "pe1": {"kind": "cisco_iol"},
                # p1 keeps the genuine host bind, loses the generated one.
                "p1": {"kind": "cisco_iol", "binds": ["/etc/hosts:/etc/hosts:ro"]},
                "r1": {"kind": "vyos"},
            }
        },
    }
    assert strip_generated_binds(topology) == expected
    # The input is not mutated (pe1 still carries its original bind).
    assert topology["topology"] == {
        "nodes": {
            "pe1": {"kind": "cisco_iol", "binds": ["node_files/pe1/ifstate:/iol/ifstate.cfg"]},
            "p1": {
                "kind": "cisco_iol",
                "binds": ["node_files/p1/ifstate:/iol/ifstate.cfg", "/etc/hosts:/etc/hosts:ro"],
            },
            "r1": {"kind": "vyos"},
        }
    }


def test_strip_generated_binds_tolerates_missing_sections() -> None:
    # No topology/nodes sections -> returned unchanged, no error.
    assert strip_generated_binds({"name": "lab"}) == {"name": "lab"}
