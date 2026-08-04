import importlib.util
from pathlib import Path
from typing import cast

import yaml

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.netlab import (
    DEVICE_KMODS,
    PROVIDER_KMODS,
    create_clab_topology,
    find_unsupported_directives,
    read_lab_name,
    read_message,
    read_mgmt_subnet,
    rewrite_generated_binds,
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


def test_create_generates_clab_topology_and_links() -> None:
    result = create_clab_topology(_VALID_DEFINITION)
    assert isinstance(result, Ok), result
    # A containerlab topology is a mapping with a `topology` section.
    assert "topology" in result.value.topology
    # The logical link table: one p2p link, both endpoints resolved. Endpoint
    # facts are asserted, never `type` — netlab's vocabulary is a passthrough.
    (link,) = result.value.links
    assert link.index == 1
    assert {(e.node, e.ifname, e.clab_name) for e in link.endpoints} == {
        ("r1", "eth1", "eth1"),
        ("r2", "eth1", "eth1"),
    }
    assert link.prefix_ipv4 is not None
    assert all(e.ipv4 is not None for e in link.endpoints)


def test_create_links_lan_is_one_logical_link() -> None:
    # A multi-access link is ONE logical link with N endpoints — not the
    # per-member bridge fan-out clab.yml renders it as.
    definition = (
        "provider: clab\ndefaults.device: linux\nnodes: [n1, n2, n3]\nlinks:\n- [n1, n2, n3]\n"
    )
    result = create_clab_topology(definition)
    assert isinstance(result, Ok), result
    (link,) = result.value.links
    assert {e.node for e in link.endpoints} == {"n1", "n2", "n3"}


def test_create_links_join_uses_clab_interface_name() -> None:
    # cisco_iol renames interfaces: netlab's ifname IS the clab-side name here
    # ("Ethernet0/1"), carried via the node interface table's `clab.name` —
    # this proves the (node, ifindex) join path, not the ifname fallback.
    definition = "provider: clab\ndefaults.device: iol\nnodes: [r1, r2]\nlinks: [r1-r2]\n"
    result = create_clab_topology(definition)
    assert isinstance(result, Ok), result
    (link,) = result.value.links
    assert {(e.node, e.ifname, e.clab_name) for e in link.endpoints} == {
        ("r1", "Ethernet0/1", "Ethernet0/1"),
        ("r2", "Ethernet0/1", "Ethernet0/1"),
    }


def test_create_extracts_node_facts() -> None:
    # The fact namespace (delta 17): raw netlab node dicts, keyed by short
    # name. Only the outer shape and a few load-bearing keys are asserted —
    # the values are deliberately netlab's (provisional/unpinned).
    result = create_clab_topology(_VALID_DEFINITION)
    assert isinstance(result, Ok), result
    facts = result.value.node_facts
    assert set(facts) == {"r1", "r2"}
    r1 = facts["r1"]
    assert r1["device"] == "vyos"
    # The keys suites will actually render: loopback address, interface IPs.
    loopback = r1["loopback"]
    assert isinstance(loopback, dict) and isinstance(loopback["ipv4"], str)
    interfaces = r1["interfaces"]
    assert isinstance(interfaces, list) and len(cast("list[object]", interfaces)) == 1


def test_create_reports_error_on_invalid_definition() -> None:
    result = create_clab_topology("nodes: [r1]\nlinks: [r1-nonexistent]\n")
    assert isinstance(result, Err)


def test_host_bridges_only_for_multi_access_links() -> None:
    # netlab references a host bridge (name[0:10]_linkindex) only for links
    # with 3+ endpoints. It ASSIGNS a bridge to a 2-endpoint host-to-host link
    # too, but renders that as a plain veth pair — the exact trap: filter on
    # endpoint count, not on the bridge attribute alone.
    definition = (
        "name: brlab\n"
        "provider: clab\n"
        "defaults.device: linux\n"
        "nodes: [n1, n2, n3]\n"
        "links:\n"
        "- [n1, n2, n3]\n"  # linkindex 1: LAN -> bridge brlab_1
        "- [n1, n2]\n"  # linkindex 2: two hosts, typed lan, NO host bridge
    )
    result = create_clab_topology(definition)
    assert isinstance(result, Ok), result
    assert result.value.host_bridges == ("brlab_1",)


def test_host_bridges_empty_for_p2p_topology() -> None:
    result = create_clab_topology(_VALID_DEFINITION)
    assert isinstance(result, Ok), result
    assert result.value.host_bridges == ()


def test_kernel_modules_from_device_and_modules() -> None:
    # vyos participates (its device data has a kmods key), so the provider map
    # applies: the mpls module needs mpls-router + mpls-iptunnel, required.
    definition = (
        "provider: clab\n"
        "defaults.device: vyos\n"
        "module: [ospf, mpls]\n"
        "nodes: [r1, r2]\n"
        "links: [r1-r2]\n"
    )
    result = create_clab_topology(definition)
    assert isinstance(result, Ok), result
    assert {(m.name, m.required) for m in result.value.kernel_modules} == {
        ("mpls-router", True),
        ("mpls-iptunnel", True),
    }


def test_kernel_modules_empty_without_kmod_needing_modules() -> None:
    # Plain linux hosts: participating device, but no module asks for kmods.
    result = create_clab_topology(_VALID_DEFINITION)
    assert isinstance(result, Ok), result
    assert result.value.kernel_modules == ()


def test_kernel_modules_optional_marker() -> None:
    # frr's device extras mark vrf as optional at initial ('vrf?').
    definition = "provider: clab\ndefaults.device: frr\nnodes: [r1, r2]\nlinks: [r1-r2]\n"
    result = create_clab_topology(definition)
    assert isinstance(result, Ok), result
    assert {(m.name, m.required) for m in result.value.kernel_modules} == {("vrf", False)}


def test_kmods_mirror_matches_installed_netlab() -> None:
    # The drift guard: PROVIDER_KMODS / DEVICE_KMODS are mirrored from netlab's
    # defaults so deploys don't pay a per-run lookup. A netlab upgrade that
    # changes the map (or adds a participating device) must fail HERE, not
    # silently skip a module on some future host.
    spec = importlib.util.find_spec("netsim")
    assert spec is not None and spec.submodule_search_locations is not None
    root = Path(next(iter(spec.submodule_search_locations)))

    provider = yaml.safe_load((root / "providers" / "clab.yml").read_text())
    assert {module: tuple(mods) for module, mods in provider["kmods"].items()} == PROVIDER_KMODS

    mirrored_devices: set[str] = set()
    for path in [*(root / "devices").glob("*.yml"), *(root / "daemons").glob("*.yml")]:
        device_data = yaml.safe_load(path.read_text())
        clab = device_data.get("clab")
        if not isinstance(clab, dict) or "kmods" not in clab:
            continue  # non-participating device
        mirrored_devices.add(path.stem)
        extras = cast("dict[str, list[str]]", clab["kmods"] or {})
        assert path.stem in DEVICE_KMODS, f"unmirrored participating device: {path.stem}"
        assert {module: tuple(mods) for module, mods in extras.items()} == DEVICE_KMODS[
            path.stem
        ], path.stem
    assert mirrored_devices == set(DEVICE_KMODS)


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


def test_rewrite_generated_binds_points_at_lab_files_dir() -> None:
    # Generated binds gain the absolute lab-files prefix (mount flags intact),
    # genuine host binds and everything else stay untouched, and a relative
    # startup-config is rewritten the same way — inline deploy would otherwise
    # ship it unsatisfiable.
    topology: dict[str, object] = {
        "name": "lab",
        "topology": {
            "nodes": {
                "n1": {
                    "kind": "linux",
                    "binds": [
                        "node_files/n1/hosts:/etc/hosts:ro",
                        "/lib/modules:/lib/modules:ro",
                    ],
                },
                "r1": {"kind": "ios", "startup-config": "node_files/r1/startup.partial.config"},
            }
        },
    }
    rewritten = rewrite_generated_binds(topology, "/var/lib/twinlab/lab-files/lab")
    nodes = cast(
        "dict[str, dict[str, object]]", cast("dict[str, object]", rewritten["topology"])["nodes"]
    )
    assert nodes["n1"]["binds"] == [
        "/var/lib/twinlab/lab-files/lab/node_files/n1/hosts:/etc/hosts:ro",
        "/lib/modules:/lib/modules:ro",
    ]
    assert nodes["r1"]["startup-config"] == (
        "/var/lib/twinlab/lab-files/lab/node_files/r1/startup.partial.config"
    )
    # The input is not mutated.
    original = cast(
        "dict[str, dict[str, object]]", cast("dict[str, object]", topology["topology"])["nodes"]
    )
    assert original["n1"]["binds"] == [
        "node_files/n1/hosts:/etc/hosts:ro",
        "/lib/modules:/lib/modules:ro",
    ]


def test_rewrite_generated_binds_tolerates_missing_sections() -> None:
    assert rewrite_generated_binds({"name": "lab"}, "/data/lab") == {"name": "lab"}


def test_find_unsupported_directives_clean_definition() -> None:
    assert find_unsupported_directives(_VALID_DEFINITION) == []
    # Unparseable / non-mapping input is not this check's business — the dry
    # `netlab create` stays the syntax authority.
    assert find_unsupported_directives(": not yaml [") == []
    assert find_unsupported_directives("- a list\n") == []


def test_find_unsupported_directives_rejected_keys() -> None:
    # All three rejected features at once, spelled NESTED; each is reported
    # once with its dotted key.
    definition = """\
provider: clab
defaults:
  device: vyos
  netlab:
    up:
      pre_transform: echo hi
  providers:
    clab:
      bridge_type: ovs-bridge
tools:
  graphite:
nodes: [r1]
"""
    keys = [d.key for d in find_unsupported_directives(definition)]
    assert keys == ["defaults.netlab.up", "defaults.providers.clab.bridge_type", "tools"]


def test_find_unsupported_directives_dotted_spellings() -> None:
    # netlab expands dotted keys identically to nested ones — the check must too.
    definition = """\
provider: clab
defaults.device: vyos
defaults.netlab.down.post_stop: echo bye
defaults.providers.clab.bridge_type: ovs-bridge
nodes: [r1]
"""
    keys = [d.key for d in find_unsupported_directives(definition)]
    assert keys == ["defaults.netlab.down", "defaults.providers.clab.bridge_type"]


def test_read_message() -> None:
    assert read_message("name: x\nmessage: Use ssh to reach r1.\n") == "Use ssh to reach r1."
    assert read_message("name: x\n") is None
    assert read_message("message: [not, a, string]\n") is None
    assert read_message(": broken [") is None


def test_find_unsupported_directives_allows_default_bridge_type() -> None:
    # Only the OVS value is rejected — an explicit (redundant) linux bridge
    # selection is what hostprep does anyway.
    definition = "provider: clab\ndefaults.providers.clab.bridge_type: bridge\nnodes: [r1]\n"
    assert find_unsupported_directives(definition) == []


def test_create_materializes_node_files(tmp_path: Path) -> None:
    # The deploy path materializes the generated node_files/ tree so the
    # rewritten binds resolve: every relative bind source in the produced
    # topology must exist under the target, and a stale tree from a previous
    # deploy is fully replaced.
    target = tmp_path / "lab1" / "node_files"
    target.mkdir(parents=True)
    stale = target / "stale.txt"
    _ = stale.write_text("leftover")
    definition = "provider: clab\ndefaults.device: linux\nnodes: [n1, n2]\nlinks: [n1-n2]\n"
    result = create_clab_topology(definition, node_files_target=target)
    assert isinstance(result, Ok), result
    assert not stale.exists()
    nodes = cast(
        "dict[str, dict[str, object]]",
        cast("dict[str, object]", result.value.topology["topology"])["nodes"],
    )
    sources = [
        bind.split(":", 1)[0]
        for node in nodes.values()
        for bind in cast("list[object]", node.get("binds", []))
        if isinstance(bind, str) and bind.startswith("node_files/")
    ]
    # linux nodes DO carry generated binds (the shared /etc/hosts) — an empty
    # list would mean this test proves nothing.
    assert sources
    for source in sources:
        assert (tmp_path / "lab1" / source).is_file(), source
