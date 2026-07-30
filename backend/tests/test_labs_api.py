import uuid
from datetime import UTC, datetime

import pydantic
import pytest

from twinlab_backend.api.labs import lab_detail, lab_summary, link_oper_state, merge_links
from twinlab_backend.db.models import Lab, User
from twinlab_backend.models import (
    CreateLabRequest,
    Duration,
    NetemImpairment,
    NetemSetRequest,
    NodeInterface,
    UpdateCustomConfigRequest,
)
from twinlab_backend.services.clab_api import NodeInfo
from twinlab_backend.services.netlab import TopologyLink, TopologyLinkEndpoint

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


def _endpoint(node: str, clab_name: str = "eth1") -> TopologyLinkEndpoint:
    return TopologyLinkEndpoint(
        node=node, ifname=clab_name, ifindex=1, clab_name=clab_name, ipv4="10.0.0.1/30", ipv6=None
    )


def _stored_link(*endpoints: TopologyLinkEndpoint) -> TopologyLink:
    return TopologyLink(
        index=1,
        name=None,
        type="p2p",
        prefix_ipv4="10.0.0.0/30",
        prefix_ipv6=None,
        bandwidth=None,
        mtu=None,
        endpoints=list(endpoints),
    )


def _iface(name: str, alias: str = "", state: str = "up") -> NodeInterface:
    return NodeInterface(
        name=name,
        alias=alias,
        ifindex=2,
        mac="aa:bb:cc:dd:ee:01",
        mtu=1500,
        state=state,
        kind="veth",
    )


def test_link_oper_state_rollup() -> None:
    table: list[tuple[list[str | None], str]] = [
        (["up", "up"], "up"),
        (["up", "down"], "degraded"),
        (["down", "lowerlayerdown"], "down"),
        (["up", None], "unknown"),
        ([None, None], "unknown"),
        ([], "unknown"),
    ]
    for states, expected in table:
        assert link_oper_state(states) == expected, states


def test_merge_links_undeployed_is_unknown() -> None:
    merged = merge_links([_stored_link(_endpoint("n1"), _endpoint("n2"))], None, {})
    assert merged.live is False
    (link,) = merged.links
    assert link.oper_state == "unknown"
    # Without live state the generated clab-side name is served as-is.
    assert [e.interface for e in link.endpoints] == ["eth1", "eth1"]
    assert all(e.state is None and e.impairment is None for e in link.endpoints)


def test_merge_links_live_states_roll_up() -> None:
    inventory = {"n1": [_iface("eth1")], "n2": [_iface("eth1", state="down")]}
    merged = merge_links([_stored_link(_endpoint("n1"), _endpoint("n2"))], inventory, {})
    assert merged.live is True
    (link,) = merged.links
    assert link.oper_state == "degraded"
    assert [e.state for e in link.endpoints] == ["up", "down"]


def test_merge_links_matches_alias_and_reports_live_name() -> None:
    # A renaming kind (cisco_iol): the generated name is the NOS name; the
    # container inventory advertises it as the alias of the netns name.
    stored = _stored_link(_endpoint("r1", clab_name="Ethernet0/1"))
    merged = merge_links([stored], {"r1": [_iface("eth1", alias="Ethernet0/1")]}, {})
    ((endpoint,),) = [link.endpoints for link in merged.links]
    assert endpoint.interface == "eth1"
    assert endpoint.state == "up"


def test_merge_links_attaches_impairment_by_resolved_name() -> None:
    impairment = NetemImpairment(
        interface="eth1",
        delay=Duration(value=50, unit="ms"),
        jitter=None,
        loss=0,
        rate=0,
        corruption=0,
    )
    merged = merge_links(
        [_stored_link(_endpoint("n1"), _endpoint("n2"))],
        {"n1": [_iface("eth1")], "n2": [_iface("eth1")]},
        {"n1": [impairment]},
    )
    (link,) = merged.links
    # Impairment rides the endpoint it was set on; the peer stays clean, and
    # an impaired-but-up link still reads "up" (impairment != degraded).
    assert link.endpoints[0].impairment == impairment
    assert link.endpoints[1].impairment is None
    assert link.oper_state == "up"
