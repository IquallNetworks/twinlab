import uuid
from datetime import UTC, datetime

import pydantic
import pytest

from twinlab_backend.api.labs import lab_detail, lab_summary
from twinlab_backend.db.models import Lab, User
from twinlab_backend.models import (
    CreateLabRequest,
    Duration,
    NetemSetRequest,
    UpdateCustomConfigRequest,
)
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


def _user(username: str) -> User:
    # id fills on flush; set explicitly for the unsaved instance.
    user = User(username=username, password_hash="x")
    user.id = uuid.uuid7()
    return user


def test_summary_counts_live_nodes_and_owner() -> None:
    lab = _lab("tmp1", "deployed", _user("alice"))
    summary = lab_summary(lab, {"tmp1": (_NODE, _NODE)}, ["lab:read"])
    assert summary.name == "tmp1"
    assert summary.status == "deployed"
    assert summary.owner is not None and summary.owner.name == "alice"
    assert summary.nodes == 2
    assert summary.nodes_running == 2
    assert summary.permissions == ["lab:read"]


def test_summary_zero_nodes_when_absent_from_live() -> None:
    lab = _lab("tmp1", "destroyed", None)
    summary = lab_summary(lab, {}, [])
    assert summary.owner is None
    assert summary.nodes == 0
    assert summary.nodes_running == 0


def test_summary_counts_present_and_running_separately() -> None:
    # After a host reboot containers are present but exited: nodes counts
    # presence, nodes_running the actually-running subset.
    exited = NodeInfo(
        node_name="r2",
        container_name="clab-tmp1-r2",
        image="vyos",
        state="exited",
        ipv4_address="192.168.121.102/24",
    )
    lab = _lab("tmp1", "deployed", None)
    summary = lab_summary(lab, {"tmp1": (_NODE, exited)}, [])
    assert summary.nodes == 2
    assert summary.nodes_running == 1


def test_summary_masks_permissions_to_lab_scoped() -> None:
    # Contract delta 10: global-only perms (lab:create, user:manage) never
    # appear in the per-lab set.
    lab = _lab("tmp1", "deployed", None)
    summary = lab_summary(lab, {}, ["lab:create", "lab:read", "user:manage", "lab:edit"])
    assert summary.permissions == ["lab:read", "lab:edit"]


def test_summary_config_time_status_tristate() -> None:
    lab = _lab("tmp1", "deployed", None)
    assert lab_summary(lab, {}, []).config_time_status == "not_run"
    lab.config_time_ok = True
    assert lab_summary(lab, {}, []).config_time_status == "passed"
    lab.config_time_ok = False
    assert lab_summary(lab, {}, []).config_time_status == "failed"


def test_detail_maps_stored_definition_and_live_nodes() -> None:
    lab = _lab("tmp1", "deployed", _user("bob"))
    detail = lab_detail(lab, (_NODE,), ["lab:read"])
    assert detail.definition == "name: x\n"
    assert detail.owner is not None and detail.owner.name == "bob"
    assert len(detail.nodes) == 1
    node = detail.nodes[0]
    assert node.name == "r1"
    assert node.container == "clab-tmp1-r1"
    assert node.state == "running"
    assert node.mgmt_ip == "192.168.121.101"  # CIDR mask stripped for the ssh command


def test_detail_empty_nodes_for_destroyed_lab() -> None:
    lab = _lab("tmp1", "destroyed", None)
    detail = lab_detail(lab, (), [])
    assert detail.status == "destroyed"
    assert detail.nodes == []


def test_detail_created_record_has_no_definition() -> None:
    lab = _lab("tmp1", "created", None)
    lab.definition = None
    detail = lab_detail(lab, (), [])
    assert detail.status == "created"
    assert detail.definition is None
    assert detail.config_time_status == "not_run"


def test_netem_set_with_no_impairments_is_a_clear() -> None:
    # REPLACE semantics (contract delta 7): an empty body clears everything —
    # valid, not rejected.
    request = NetemSetRequest(interface="eth1")
    assert request.delay is None and request.loss is None


def test_netem_set_rejects_jitter_without_delay() -> None:
    with pytest.raises(pydantic.ValidationError, match="jitter requires delay"):
        _ = NetemSetRequest(interface="eth1", jitter=Duration(value=5, unit="ms"))


def test_netem_set_accepts_structured_durations() -> None:
    request = NetemSetRequest(
        interface="eth1", delay=Duration(value=50, unit="ms"), jitter=Duration(value=5, unit="ms")
    )
    assert request.delay == Duration(value=50, unit="ms")
    assert NetemSetRequest(interface="eth1", loss=1.5).loss == 1.5


def test_create_lab_request_requires_name() -> None:
    with pytest.raises(pydantic.ValidationError, match="name"):
        _ = CreateLabRequest.model_validate({})


def test_create_lab_request_rejects_unsafe_name() -> None:
    # The name is a URL segment and a clab identity, so the charset is tight.
    with pytest.raises(pydantic.ValidationError):
        _ = CreateLabRequest(name="../evil")


def test_create_lab_request_accepts_valid_name() -> None:
    assert CreateLabRequest(name="mpls-l3vpn").name == "mpls-l3vpn"


def test_custom_config_accepts_fileset() -> None:
    request = UpdateCustomConfigRequest(custom_config={"nat/ios.j2": "conf"})
    assert request.custom_config == {"nat/ios.j2": "conf"}


def test_custom_config_rejects_unsafe_template_path() -> None:
    # Template paths are relative .j2 files; a traversal or bad suffix is rejected.
    with pytest.raises(pydantic.ValidationError):
        _ = UpdateCustomConfigRequest(custom_config={"../x.j2": "c"})
    with pytest.raises(pydantic.ValidationError):
        _ = UpdateCustomConfigRequest(custom_config={"x.cfg": "c"})
