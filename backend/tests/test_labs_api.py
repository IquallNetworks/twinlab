from datetime import UTC, datetime

from twinlab_backend.api.labs import lab_detail, lab_summary
from twinlab_backend.db.models import Lab, User
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
