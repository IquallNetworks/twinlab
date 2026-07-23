from twinlab_backend.result import Err, Ok
from twinlab_backend.services.netlab import create_clab_topology, read_lab_name, set_lab_name

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
