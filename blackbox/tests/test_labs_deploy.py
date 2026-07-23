"""Deploy-heavy contract tests: real containerlab deploys (marker: deploy).

Each test deploys its own tiny two-linux-node lab (LINUX_LAB_DEFINITION), so
the slice needs the node image pullable on the host. Deselect with
`-m "not deploy"` for the cheap contract run.
"""

import asyncio

import pytest
from twinlab_client import (
    DeployResponse,
    Duration,
    LabDetail,
    LabEvent,
    TwinlabApiError,
    TwinlabClient,
)

from _config import LINUX_LAB_DEFINITION, LabFactory

pytestmark = pytest.mark.deploy


async def _deployed_lab(admin: TwinlabClient, make_lab: LabFactory) -> LabDetail:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    result = await admin.deploy_lab(lab.name)
    assert result.status == "deployed"
    assert result.configuration is None and result.validation is None
    return await admin.get_lab(lab.name)


async def test_deploy_lifecycle(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)
    assert detail.status == "deployed"
    assert {node.name for node in detail.nodes} == {"n1", "n2"}
    for node in detail.nodes:
        assert node.state == "running"
        assert node.container == f"clab-{detail.name}-{node.name}"
        assert node.mgmt_ip, node.name

    # Interfaces are keyed by SHORT node name.
    inventory = await admin.interfaces(detail.name)
    assert {entry.node for entry in inventory} == {"n1", "n2"}

    logs = await admin.node_logs(detail.name, "n1", tail=50)
    assert logs.node == "n1"
    assert logs.container == f"clab-{detail.name}-n1"

    # Deploying over a running lab is allowed (overwrite in place).
    again = await admin.deploy_lab(detail.name)
    assert again.status == "deployed"

    # Destroy keeps the record, redeployable.
    destroyed = await admin.destroy_lab(detail.name)
    assert destroyed.status == "destroyed"
    after = await admin.get_lab(detail.name)
    assert after.status == "destroyed"
    assert after.definition is not None  # the record survives with its definition
    assert after.nodes == []

    # A destroyed lab deploys fresh from the stored definition.
    redeployed = await admin.deploy_lab(detail.name)
    assert redeployed.status == "deployed"


async def test_deploy_mutex_rejects_concurrent_deploys(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)

    outcomes = await asyncio.gather(
        admin.deploy_lab(lab.name), admin.deploy_lab(lab.name), return_exceptions=True
    )
    # Exactly one deploy runs; the concurrent one hits the deploying mutex.
    successes = [o for o in outcomes if isinstance(o, DeployResponse)]
    errors = [o for o in outcomes if isinstance(o, TwinlabApiError)]
    assert len(successes) == 1, outcomes
    assert len(errors) == 1, outcomes
    assert errors[0].status_code == 409


async def test_netem_set_show_clear(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)
    inventory = {entry.node: entry.interfaces for entry in await admin.interfaces(detail.name)}
    link_interfaces = [iface.name for iface in inventory["n1"] if iface.name.startswith("eth")]
    assert link_interfaces, "expected a link interface on n1"
    interface = link_interfaces[0]

    _ = await admin.set_netem(detail.name, "n1", interface, delay=Duration(50.0, "ms"), loss=1.0)
    shaped = {imp.interface: imp for imp in await admin.show_netem(detail.name, "n1")}
    impairment = shaped[interface]
    assert impairment.delay == Duration(50.0, "ms")
    assert impairment.loss == 1.0
    assert impairment.jitter is None

    # REPLACE semantics: a call with no impairments clears the interface.
    _ = await admin.set_netem(detail.name, "n1", interface)
    cleared = {imp.interface: imp for imp in await admin.show_netem(detail.name, "n1")}
    impairment = cleared[interface]
    assert impairment.delay is None
    assert impairment.loss == 0.0


async def test_node_power_cycle(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)

    _ = await admin.node_power(detail.name, "n1", "stop")
    stopped = {node.name: node for node in (await admin.get_lab(detail.name)).nodes}
    assert stopped["n1"].state != "running"
    assert stopped["n2"].state == "running"

    _ = await admin.node_power(detail.name, "n1", "start")
    started = {node.name: node for node in (await admin.get_lab(detail.name)).nodes}
    assert started["n1"].state == "running"


async def test_terminal_and_events(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)

    async def first_lab_event() -> LabEvent:
        async for event in admin.events():
            if event.lab == detail.name:
                return event
        raise AssertionError("event stream ended without a matching event")

    listener = asyncio.create_task(first_lab_event())
    await asyncio.sleep(0)  # let the stream subscribe before acting

    async with admin.terminal(detail.name, "n1", protocol="shell") as term:
        await term.send(b"echo bb-hello\n")
        output = b""
        while b"bb-hello" not in output:
            output += await term.recv(timeout=15)

    # A node action must surface on the events stream for this lab.
    _ = await admin.node_power(detail.name, "n1", "stop")
    event = await asyncio.wait_for(listener, timeout=30)
    assert event.lab == detail.name
