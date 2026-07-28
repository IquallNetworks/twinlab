"""Deploy-heavy contract tests: real containerlab deploys (marker: deploy).

Each test deploys its own tiny two-linux-node lab (LINUX_LAB_DEFINITION), so
the slice needs the node image pullable on the host. Deselect with
`-m "not deploy"` for the cheap contract run.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import aclosing

import pytest
from twinlab_client import (
    DeployResponse,
    Duration,
    LabDetail,
    LabEvent,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    TwinlabClient,
    ValidationTest,
)

from _config import LINUX_LAB_DEFINITION, LabFactory, UserClientFactory

pytestmark = pytest.mark.deploy


async def _deployed_lab(admin: TwinlabClient, make_lab: LabFactory) -> LabDetail:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    result = await admin.deploy_lab(lab.name)
    assert result.status == "deployed"
    assert result.configuration is None and result.validation is None
    return await admin.get_lab(lab.name)


async def _first_event_for(stream: AsyncGenerator[LabEvent], lab: str) -> LabEvent:
    async for event in stream:
        if event.lab == lab:
            return event
    raise AssertionError("event stream ended without a matching event")


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

    # A destroyed (not-running) lab refuses a plain destroy: 409, not the
    # existence-hiding 404 (contract delta 11).
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.destroy_lab(detail.name)
    assert excinfo.value.status_code == 409

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
    # (Assumes the two requests overlap — safe while a real containerlab
    # deploy takes seconds; revisit if deploys ever get a fast path.)
    successes = [o for o in outcomes if isinstance(o, DeployResponse)]
    errors = [o for o in outcomes if isinstance(o, TwinlabApiError)]
    assert len(successes) == 1, outcomes
    assert len(errors) == 1, outcomes
    assert errors[0].status_code == 409


async def test_netem_set_show_clear(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)
    inventory = {entry.node: entry.interfaces for entry in await admin.interfaces(detail.name)}
    # eth0 is containerlab's management interface; the n1-n2 link is the
    # first non-mgmt ethN.
    link_interfaces = sorted(
        iface.name
        for iface in inventory["n1"]
        if iface.name.startswith("eth") and iface.name != "eth0"
    )
    assert link_interfaces, "expected a non-mgmt link interface on n1"
    interface = link_interfaces[0]

    _ = await admin.set_netem(detail.name, "n1", interface, delay=Duration(50.0, "ms"), loss=1.0)
    shaped = {imp.interface: imp for imp in await admin.show_netem(detail.name, "n1")}
    impairment = shaped[interface]
    assert impairment.delay == Duration(50.0, "ms")
    assert impairment.loss == 1.0
    assert impairment.jitter is None

    # REPLACE semantics: a call with no impairments clears the interface —
    # and show lists only ACTIVELY impaired interfaces, so it disappears.
    _ = await admin.set_netem(detail.name, "n1", interface)
    cleared = {imp.interface: imp for imp in await admin.show_netem(detail.name, "n1")}
    assert interface not in cleared


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

    async with aclosing(admin.events()) as stream:
        listener = asyncio.create_task(_first_event_for(stream, detail.name))
        try:
            # The stream carries no subscription signal; give the SSE
            # connection a moment to establish before acting.
            await asyncio.sleep(1.0)

            async with admin.terminal(detail.name, "n1", protocol="shell") as term:
                await term.send(b"echo bb-hello\n")
                output = b""
                while b"bb-hello" not in output:
                    output += await term.recv(timeout=15)

            # A node action must surface on the events stream for this lab.
            _ = await admin.node_power(detail.name, "n1", "stop")
            event = await asyncio.wait_for(asyncio.shield(listener), timeout=30)
            assert event.lab == detail.name
        finally:
            _ = listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                _ = await listener


async def test_events_filtered_to_readable_labs(
    admin: TwinlabClient, make_lab: LabFactory, make_user_client: UserClientFactory
) -> None:
    # Security-relevant: the stream is filtered to labs the subscriber can
    # read — an outsider must never receive this lab's events.
    detail = await _deployed_lab(admin, make_lab)
    _, outsider = await make_user_client(None)

    async with aclosing(outsider.events()) as stream:
        listener = asyncio.create_task(_first_event_for(stream, detail.name))
        try:
            await asyncio.sleep(1.0)
            _ = await admin.node_power(detail.name, "n1", "stop")
            with pytest.raises(TimeoutError):
                _ = await asyncio.wait_for(asyncio.shield(listener), timeout=8)
        finally:
            _ = listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                _ = await listener


async def test_configure_and_validation_pipeline(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    passing_gate = {
        "gate": TestSuite(
            tests={
                "ok": ValidationTest(
                    nodes=["n1", "n2"],
                    command="echo bb-ready",
                    expect=TestExpectation(contains="bb-ready"),
                )
            },
            stage="config-time",
        )
    }
    _ = await admin.put_test_suites(lab.name, passing_gate)

    result = await admin.deploy_lab(lab.name, configure=True)
    assert result.status == "configured"
    assert result.configuration is not None
    assert all(node.status == "configured" for node in result.configuration)
    assert result.validation is not None and result.validation[0].failed == 0
    assert (await admin.get_lab(lab.name)).config_time_status == "passed"

    # A failing config-time gate is DATA: 2xx validation_failed, lab still
    # deployed, gate red and unambiguous in the record.
    red_gate = {
        "gate": TestSuite(
            tests={
                "never": ValidationTest(
                    nodes=["n1"],
                    command="echo bb-ready",
                    expect=TestExpectation(contains="bb-will-never-match"),
                )
            },
            stage="config-time",
        ),
        "manual": TestSuite(
            tests={
                "ok": ValidationTest(
                    nodes=["n1"],
                    command="echo bb-ready",
                    expect=TestExpectation(contains="bb-ready"),
                )
            },
        ),
    }
    _ = await admin.put_test_suites(lab.name, red_gate)
    outcome = await admin.configure_lab(lab.name)
    assert outcome.status == "validation_failed"
    detail = await admin.get_lab(lab.name)
    assert detail.status == "deployed"
    assert detail.config_time_status == "failed"

    # Skipping the gate RETAINS the previous (failed) result — never erases it.
    skipped = await admin.configure_lab(lab.name, skip_config_time_checks=True)
    assert skipped.status == "configured"
    assert (await admin.get_lab(lab.name)).config_time_status == "failed"

    # A manual run persists as the suite's last run but NEVER moves the gate.
    report = await admin.run_test_suite(lab.name, "manual")
    assert report.failed == 0 and report.passed >= 1
    suites_state = await admin.get_test_suites(lab.name)
    assert suites_state.last_validation["manual"].passed >= 1
    assert suites_state.config_time_status == "failed"
