from datetime import UTC, datetime

import pydantic
import pytest

from twinlab_backend.api.labs import lab_detail, lab_summary
from twinlab_backend.db.models import Lab, User
from twinlab_backend.models import DeployRequest, NetemSetRequest
from twinlab_backend.services.clab_api import NodeInfo

_TS = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


def _lab(name: str, status: str, owner: User | None) -> Lab:
    lab = Lab(name=name, definition="name: x\n", status=status)
    lab.owner = owner
    # server_default only fills on flush; set explicitly for the unsaved instance.
    lab.created_at = _TS
    lab.updated_at = _TS
    return lab


_NODE = NodeInfo(
    node_name="r1",
    container_name="clab-tmp1-r1",
    image="vyos",
    state="running",
    ipv4_address="192.168.121.101/24",
)


def test_summary_counts_live_nodes_and_owner() -> None:
    lab = _lab("tmp1", "deployed", User(username="alice", password_hash="x"))
    summary = lab_summary(lab, {"tmp1": (_NODE, _NODE)})
    assert summary.name == "tmp1"
    assert summary.status == "deployed"
    assert summary.owner == "alice"
    assert summary.nodes == 2


def test_summary_zero_nodes_when_absent_from_live() -> None:
    lab = _lab("tmp1", "destroyed", None)
    summary = lab_summary(lab, {})
    assert summary.owner is None
    assert summary.nodes == 0


def test_detail_maps_stored_definition_and_live_nodes() -> None:
    lab = _lab("tmp1", "deployed", User(username="bob", password_hash="x"))
    detail = lab_detail(lab, (_NODE,))
    assert detail.definition == "name: x\n"
    assert detail.owner == "bob"
    assert len(detail.nodes) == 1
    node = detail.nodes[0]
    assert node.name == "r1"
    assert node.container == "clab-tmp1-r1"
    assert node.state == "running"
    assert node.mgmt_ip == "192.168.121.101"  # CIDR mask stripped for the ssh command


def test_detail_empty_nodes_for_destroyed_lab() -> None:
    lab = _lab("tmp1", "destroyed", None)
    detail = lab_detail(lab, ())
    assert detail.status == "destroyed"
    assert detail.nodes == []


def test_netem_set_requires_at_least_one_impairment() -> None:
    with pytest.raises(pydantic.ValidationError, match="at least one impairment"):
        _ = NetemSetRequest(interface="eth1")


def test_netem_set_rejects_jitter_without_delay() -> None:
    with pytest.raises(pydantic.ValidationError, match="jitter requires delay"):
        _ = NetemSetRequest(interface="eth1", jitter="5ms")


def test_netem_set_accepts_a_single_impairment() -> None:
    # A lone impairment is valid; delay+jitter together satisfy the dependency.
    assert NetemSetRequest(interface="eth1", loss=1.5).loss == 1.5
    assert NetemSetRequest(interface="eth1", delay="50ms", jitter="5ms").jitter == "5ms"


def test_deploy_request_requires_name() -> None:
    with pytest.raises(pydantic.ValidationError, match="name"):
        _ = DeployRequest.model_validate({"definition": "nodes: [r1]\n"})


def test_deploy_request_rejects_unsafe_name() -> None:
    # The name is a URL segment and a clab identity, so the charset is tight.
    with pytest.raises(pydantic.ValidationError):
        _ = DeployRequest(name="../evil", definition="nodes: [r1]\n")


def test_deploy_request_accepts_valid_name() -> None:
    request = DeployRequest(name="mpls-l3vpn", definition="nodes: [r1]\n")
    assert request.name == "mpls-l3vpn"


def test_deploy_request_accepts_custom_config_fileset() -> None:
    request = DeployRequest(
        name="lab", definition="nodes: [r1]\n", custom_config={"nat/ios.j2": "conf"}
    )
    assert request.custom_config == {"nat/ios.j2": "conf"}


def test_deploy_request_rejects_unsafe_template_path() -> None:
    # Template paths are relative .j2 files; a traversal or bad suffix is rejected.
    with pytest.raises(pydantic.ValidationError):
        _ = DeployRequest(name="lab", definition="nodes: [r1]\n", custom_config={"../x.j2": "c"})
    with pytest.raises(pydantic.ValidationError):
        _ = DeployRequest(name="lab", definition="nodes: [r1]\n", custom_config={"x.cfg": "c"})
