"""Deploy-time host policy on the generated topology: cgroup placement and the
staggered boot (docs/resource-limits.md)."""

from typing import cast

from twinlab_backend.services.clab_topology import BootStagger, place_in_cgroup, stagger_boot


def _topology(*names: str, **extra: dict[str, object]) -> dict[str, object]:
    nodes: dict[str, object] = {name: {"kind": "linux", **extra.get(name, {})} for name in names}
    return {"name": "lab", "topology": {"nodes": nodes}}


def _nodes(topology: dict[str, object]) -> dict[str, dict[str, object]]:
    inner = cast("dict[str, object]", topology["topology"])
    return cast("dict[str, dict[str, object]]", inner["nodes"])


def test_place_in_cgroup_wins_at_every_level_and_keeps_the_input() -> None:
    # Host policy, so a definition must not be able to escape it: the parent
    # lands on defaults AND every node (node is containerlab's top precedence),
    # and a parent a kind or group names is dropped. The input is not mutated.
    topology: dict[str, object] = {
        "name": "lab",
        "topology": {
            "defaults": {"env": {"A": "1"}},
            "kinds": {"linux": {"image": "alpine", "cgroup-parent": "/escape"}},
            "groups": {"g": {"cgroup-parent": "/escape"}},
            "nodes": {"r1": {"kind": "linux", "cgroup-parent": "/escape"}, "r2": {"kind": "linux"}},
        },
    }
    placed = place_in_cgroup(topology, "twinlab-labs.slice")
    inner = cast("dict[str, dict[str, dict[str, object]]]", placed["topology"])
    assert inner["defaults"] == {"env": {"A": "1"}, "cgroup-parent": "twinlab-labs.slice"}
    assert inner["kinds"]["linux"] == {"image": "alpine"}
    assert inner["groups"]["g"] == {}
    assert {name: node["cgroup-parent"] for name, node in _nodes(placed).items()} == {
        "r1": "twinlab-labs.slice",
        "r2": "twinlab-labs.slice",
    }
    assert _nodes(topology)["r1"]["cgroup-parent"] == "/escape"
    assert "cgroup-parent" not in _nodes(topology)["r2"]


def test_place_in_cgroup_creates_defaults_when_absent() -> None:
    placed = place_in_cgroup(_topology("r1"), "/twinlab/labs")
    assert cast("dict[str, object]", placed["topology"])["defaults"] == {
        "cgroup-parent": "/twinlab/labs"
    }


def test_stagger_boot_delays_waves_in_definition_order() -> None:
    topology = _topology("pe1", "pe2", "p1", "p2", "ce1")
    staggered, scheduled = stagger_boot(topology, BootStagger(wave_size=2, interval_seconds=10))
    delays = {name: node.get("startup-delay") for name, node in _nodes(staggered).items()}
    # The first wave starts at once (no key at all, as netlab would emit it).
    assert delays == {"pe1": None, "pe2": None, "p1": 10, "p2": 10, "ce1": 20}
    assert scheduled == 5
    assert BootStagger(2, 10).waves(scheduled) == 3
    assert all("startup-delay" not in node for node in _nodes(topology).values())


def test_stagger_boot_keeps_an_explicit_delay_out_of_the_waves() -> None:
    # A delay the definition chose (netlab passes clab.startup-delay through)
    # wins, and that node does not take a slot in a wave.
    topology = _topology("r1", "r2", "r3", r1={"startup-delay": 45})
    staggered, scheduled = stagger_boot(topology, BootStagger(wave_size=1, interval_seconds=5))
    delays = {name: node.get("startup-delay") for name, node in _nodes(staggered).items()}
    assert delays == {"r1": 45, "r2": None, "r3": 5}
    assert scheduled == 2


def test_one_wave_needs_no_delay() -> None:
    staggered, scheduled = stagger_boot(_topology("r1", "r2"), BootStagger(2, 10))
    assert all("startup-delay" not in node for node in _nodes(staggered).values())
    assert BootStagger(2, 10).waves(scheduled) == 1
