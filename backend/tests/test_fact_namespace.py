"""The fact namespace partition (contract delta 26).

Two kinds of test here: the partition RULES (pure, on hand-built input) and the
DRIFT GUARD, which runs the installed netlab over the repo examples and asserts
every pinned path still exists with its pinned shape. The guard is the teeth of
the promise — if a netlab upgrade moves a source key, this fails loudly in CI
instead of silently breaking every suite that renders it.
"""

from pathlib import Path
from typing import cast

import pytest

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.fact_namespace import (
    EXTRAS_KEY,
    partition_node_facts,
    reassemble_node_facts,
)
from twinlab_backend.services.netlab import create_clab_topology
from twinlab_backend.services.validation import render_template

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def test_partition_splits_core_from_extras() -> None:
    raw: dict[str, dict[str, object]] = {
        "r1": {
            "name": "r1",
            "id": 1,
            "device": "vyos",
            "hostname": "clab-x-r1",
            "af": {"ipv4": True},
            "module": ["ospf"],
            "box": "ghcr.io/sysoleg/vyos-container",
            "mtu": 1500,
            "netlab_ansible_skip_module": ["ospf"],
            "_node_config": ["x"],
        }
    }
    (node,) = partition_node_facts(raw).values()
    assert node["device"] == "vyos"
    assert node["af"] == {"ipv4": True}
    # `module` is pinned in place but never descended into (a list of scalars).
    assert node["module"] == ["ospf"]
    # Unpinned top-level keys — including netlab's internal ones — ride extras.
    assert node[EXTRAS_KEY] == {
        "box": "ghcr.io/sysoleg/vyos-container",
        "mtu": 1500,
        "netlab_ansible_skip_module": ["ospf"],
        "_node_config": ["x"],
    }


def test_partition_is_per_object_not_top_level_only() -> None:
    # The decided rule: an unpinned member INSIDE a pinned subtree is marked
    # too, so `ospf.areas` is visibly unstable rather than sitting unmarked
    # beside the pinned `router_id`.
    raw: dict[str, dict[str, object]] = {
        "r1": {
            "ospf": {
                "router_id": "10.0.0.1",
                "area": "0.0.0.0",
                "af": {"ipv4": True},
                "areas": [{"area": "0.0.0.0", "_area_int": 0}],
            }
        }
    }
    ospf = cast("dict[str, object]", partition_node_facts(raw)["r1"]["ospf"])
    assert ospf["router_id"] == "10.0.0.1"
    assert ospf["area"] == "0.0.0.0"
    assert ospf[EXTRAS_KEY] == {
        "af": {"ipv4": True},
        "areas": [{"area": "0.0.0.0", "_area_int": 0}],
    }


def test_partition_descends_into_list_entries() -> None:
    # Lists are never index-mirrored: each entry is an object carrying its own
    # `_extras`, so `interfaces[0]._extras.bridge` is the spelling.
    raw: dict[str, dict[str, object]] = {
        "h1": {
            "interfaces": [
                {
                    "ifname": "eth1",
                    "ifindex": 1,
                    "type": "lan",
                    "ipv4": "172.16.3.6/24",
                    "neighbors": [
                        {"node": "vyos1", "ifname": "eth4", "ipv4": "172.16.3.1/24", "vlan": 7}
                    ],
                    "bridge": "mixed-nos_7",
                    "gateway": {"ipv4": "172.16.3.1/24"},
                }
            ]
        }
    }
    interfaces = cast("list[object]", partition_node_facts(raw)["h1"]["interfaces"])
    entry = cast("dict[str, object]", interfaces[0])
    assert entry["ifname"] == "eth1"
    assert entry[EXTRAS_KEY] == {"bridge": "mixed-nos_7", "gateway": {"ipv4": "172.16.3.1/24"}}
    neighbor = cast("dict[str, object]", cast("list[object]", entry["neighbors"])[0])
    assert neighbor["node"] == "vyos1"
    assert neighbor[EXTRAS_KEY] == {"vlan": 7}


def test_partition_descends_into_map_values() -> None:
    raw: dict[str, dict[str, object]] = {
        "pe1": {
            "vrfs": {
                "vpn_a": {
                    "rd": "65000:1",
                    "import": ["65000:1"],
                    "export": ["65000:1"],
                    "loopback_address": {"ipv4": "10.2.0.1/32", "unnumbered": False},
                    "vrfidx": 100,
                }
            }
        }
    }
    vrfs = cast("dict[str, object]", partition_node_facts(raw)["pe1"]["vrfs"])
    vpn_a = cast("dict[str, object]", vrfs["vpn_a"])
    assert vpn_a["rd"] == "65000:1"
    assert vpn_a[EXTRAS_KEY] == {"vrfidx": 100}
    loopback_address = cast("dict[str, object]", vpn_a["loopback_address"])
    assert loopback_address["ipv4"] == "10.2.0.1/32"
    assert loopback_address[EXTRAS_KEY] == {"unnumbered": False}


def test_partition_omits_extras_when_everything_is_pinned() -> None:
    raw: dict[str, dict[str, object]] = {
        "r1": {"name": "r1", "mgmt": {"ifname": "eth0", "ipv4": "10.0.0.1"}}
    }
    node = partition_node_facts(raw)["r1"]
    assert EXTRAS_KEY not in node
    assert EXTRAS_KEY not in cast("dict[str, object]", node["mgmt"])


def test_partition_never_descends_below_an_unpinned_key() -> None:
    # Extras content is verbatim: a nested dict under an unpinned key keeps its
    # own shape, `_extras` included, because it was never ours to interpret.
    raw: dict[str, dict[str, object]] = {
        "r1": {"routing": {"static": [{"ipv4": "10.0.0.0/24", "nexthop": {"idx": 0}}]}}
    }
    node = partition_node_facts(raw)["r1"]
    assert cast("dict[str, object]", node[EXTRAS_KEY])["routing"] == raw["r1"]["routing"]


def test_partition_does_not_shadow_a_netlab_supplied_extras_key() -> None:
    # A literal `_extras` from netlab is itself unpinned, so it lands INSIDE
    # ours — the position is always Twinlab's.
    raw: dict[str, dict[str, object]] = {"r1": {"name": "r1", EXTRAS_KEY: {"netlab": "own"}}}
    node = partition_node_facts(raw)["r1"]
    assert node[EXTRAS_KEY] == {EXTRAS_KEY: {"netlab": "own"}}


def test_partition_keeps_a_pinned_member_in_place_on_shape_drift() -> None:
    # If netlab ever turned `mgmt` into a scalar, the key stays where consumers
    # address it (a relocation would make every `node.mgmt.…` template raise
    # StrictUndefined). The drift guard below is what fails, loudly.
    raw: dict[str, dict[str, object]] = {
        "r1": {"mgmt": "10.0.0.1", "interfaces": "not-a-list", "vrfs": []}
    }
    node = partition_node_facts(raw)["r1"]
    assert node["mgmt"] == "10.0.0.1"
    assert node["interfaces"] == "not-a-list"
    assert node["vrfs"] == []


def test_reassemble_recovers_the_raw_namespace() -> None:
    # The partition invariant: every raw key lands in EXACTLY one place, so
    # merging the extras back reproduces netlab's dict (key order excepted —
    # deliberately not part of the promise).
    raw: dict[str, dict[str, object]] = {
        "pe1": {
            "name": "pe1",
            "device": "vyos",
            "box": "img",
            "_node_config": ["x"],
            "mgmt": {"ifname": "eth0", "ipv4": "10.0.0.1", "mac": "ca:fe::"},
            "loopback": {"ifname": "dum0", "ipv4": "10.0.0.1/32", "type": "loopback"},
            "interfaces": [
                {
                    "ifname": "eth1",
                    "ifindex": 1,
                    "type": "p2p",
                    "mtu": 1500,
                    "neighbors": [{"node": "pe2", "ifname": "eth1", "ipv4": "10.1.0.2/30"}],
                    "ospf": {"area": "0.0.0.0", "passive": False},
                }
            ],
            "ospf": {"router_id": "10.0.0.1", "areas": [{"_area_int": 0}]},
            "bgp": {
                "as": 65000,
                "router_id": "10.0.0.1",
                "neighbors": [
                    {"name": "pe2", "as": 65000, "type": "ibgp", "_source_intf": {"ifname": "dum0"}}
                ],
                "community": {"ibgp": ["standard"]},
            },
            "ldp": {"router_id": "10.0.0.1", "af": {"ipv4": True}},
            "vrfs": {"vpn_a": {"rd": "65000:1", "vrfidx": 100}},
        }
    }
    assert reassemble_node_facts(partition_node_facts(raw)) == raw


def test_partition_of_an_empty_namespace_is_empty() -> None:
    assert partition_node_facts({}) == {}


def test_templates_render_both_tiers_and_only_at_their_real_path() -> None:
    """Unpromised is not unavailable: an `_extras` path RENDERS (jinja2's
    sandbox resolves it as a dict key, not a blocked attribute). But the same
    key addressed as if it were core does NOT resolve — under StrictUndefined
    that is a hard render failure, which is the partition being real rather
    than cosmetic. Verified live too (PUT's dry render 422s on `node.box`)."""
    raw: dict[str, dict[str, object]] = {
        "r1": {"mgmt": {"ifname": "eth0"}, "box": "ghcr.io/sysoleg/vyos-container"}
    }
    facts = partition_node_facts(raw)

    assert render_template("{{ node.mgmt.ifname }}", "r1", facts) == Ok("eth0")
    assert render_template("{{ node._extras.box }}", "r1", facts) == Ok(
        "ghcr.io/sysoleg/vyos-container"
    )
    stale = render_template("{{ node.box }}", "r1", facts)
    assert isinstance(stale, Err), stale


# --------------------------------------------------------------------------- #
# Drift guard — the promise's teeth, against the netlab actually installed.
# --------------------------------------------------------------------------- #


def _facts_for(example: str) -> dict[str, dict[str, object]]:
    definition = (_EXAMPLES / example).read_text()
    result = create_clab_topology(definition)
    assert isinstance(result, Ok), result
    return partition_node_facts(result.value.node_facts)


def _assert_str(container: dict[str, object], key: str, where: str) -> None:
    assert isinstance(container.get(key), str), (
        f"{where}.{key} is not a str: {container.get(key)!r}"
    )


@pytest.mark.parametrize("example", ["mpls-l3vpn.yml", "campus-lan.yml", "mixed-nos.yml"])
def test_pinned_paths_survive_installed_netlab(example: str) -> None:
    """Every pinned path present in these definitions still exists, with its
    pinned shape, in what the installed netlab expands. A netlab upgrade that
    renames or reshapes a source key fails HERE — which is the whole promise:
    Twinlab absorbs the change (shim or contract errata), suite authors don't."""
    facts = _facts_for(example)
    assert facts, f"{example} expanded to no nodes"
    for node_name, node in facts.items():
        where = f"{example}:{node_name}"
        # Node identity — pinned as ALWAYS present.
        _assert_str(node, "name", where)
        _assert_str(node, "device", where)
        _assert_str(node, "hostname", where)
        assert isinstance(node.get("id"), int), f"{where}.id"
        assert isinstance(node.get("af"), dict), f"{where}.af"
        assert isinstance(node.get("module"), list), f"{where}.module"

        mgmt = node.get("mgmt")
        assert isinstance(mgmt, dict), f"{where}.mgmt"
        _assert_str(cast("dict[str, object]", mgmt), "ifname", f"{where}.mgmt")

        # Conditional members: absence is a FACT (a role:host node has no
        # loopback interface), so each is asserted only where netlab produced it.
        if (loopback := node.get("loopback")) is not None:
            assert isinstance(loopback, dict), f"{where}.loopback"
            _assert_str(cast("dict[str, object]", loopback), "ifname", f"{where}.loopback")

        interfaces = node.get("interfaces")
        assert isinstance(interfaces, list), f"{where}.interfaces"
        for index, raw_entry in enumerate(cast("list[object]", interfaces)):
            at = f"{where}.interfaces[{index}]"
            assert isinstance(raw_entry, dict), at
            entry = cast("dict[str, object]", raw_entry)
            _assert_str(entry, "ifname", at)
            _assert_str(entry, "type", at)
            assert isinstance(entry.get("ifindex"), int), f"{at}.ifindex"
            neighbors = entry.get("neighbors")
            assert isinstance(neighbors, list), f"{at}.neighbors"
            for n_index, raw_neighbor in enumerate(cast("list[object]", neighbors)):
                neighbor = cast("dict[str, object]", raw_neighbor)
                _assert_str(neighbor, "node", f"{at}.neighbors[{n_index}]")
                _assert_str(neighbor, "ifname", f"{at}.neighbors[{n_index}]")

        for protocol in ("ospf", "ldp"):
            if (subtree := node.get(protocol)) is not None:
                assert isinstance(subtree, dict), f"{where}.{protocol}"
                _assert_str(cast("dict[str, object]", subtree), "router_id", f"{where}.{protocol}")

        if (bgp := node.get("bgp")) is not None:
            assert isinstance(bgp, dict), f"{where}.bgp"
            bgp_dict = cast("dict[str, object]", bgp)
            _assert_str(bgp_dict, "router_id", f"{where}.bgp")
            assert isinstance(bgp_dict.get("as"), int), f"{where}.bgp.as"
            for b_index, raw_peer in enumerate(cast("list[object]", bgp_dict.get("neighbors", []))):
                peer = cast("dict[str, object]", raw_peer)
                at = f"{where}.bgp.neighbors[{b_index}]"
                _assert_str(peer, "name", at)
                _assert_str(peer, "type", at)
                assert isinstance(peer.get("as"), int), f"{at}.as"

        if (vrfs := node.get("vrfs")) is not None:
            assert isinstance(vrfs, dict), f"{where}.vrfs"
            for vrf_name, raw_vrf in cast("dict[str, object]", vrfs).items():
                at = f"{where}.vrfs.{vrf_name}"
                assert isinstance(raw_vrf, dict), at
                vrf = cast("dict[str, object]", raw_vrf)
                _assert_str(vrf, "rd", at)
                for direction in ("import", "export"):
                    assert isinstance(vrf.get(direction), list), f"{at}.{direction}"


def test_drift_guard_covers_the_paths_the_example_suites_render() -> None:
    """The consumption side of the guard: the exact paths `examples/*.test-
    suites.json` render must resolve on the partitioned namespace. These are the
    only fact paths Twinlab itself ships, so a break here is a broken example."""
    mixed = _facts_for("mixed-nos.yml")
    for node_name in ("vyos1", "frr1", "chr1", "bird1"):
        ospf = cast("dict[str, object]", mixed[node_name]["ospf"])
        assert isinstance(ospf["router_id"], str)
    for node_name in ("vyos1", "chr1"):
        loopback = cast("dict[str, object]", mixed[node_name]["loopback"])
        assert isinstance(loopback["ipv4"], str)
    # bird is role:host — a router_id WITHOUT a loopback interface. Pinning
    # made this explicit: `loopback` is simply absent, never an empty stand-in.
    assert "loopback" not in mixed["bird1"]

    mpls = _facts_for("mpls-l3vpn.yml")
    for node_name in ("pe1", "pe2", "pe3", "pe4"):
        vrf = cast("dict[str, object]", cast("dict[str, object]", mpls[node_name]["vrfs"])["vpn_a"])
        address = cast("dict[str, object]", vrf["loopback_address"])
        assert isinstance(address["ipv4"], str)
        loopback = cast("dict[str, object]", mpls[node_name]["loopback"])
        assert isinstance(loopback["ipv4"], str)
