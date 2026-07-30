"""Deploy-heavy contract tests: real containerlab deploys (marker: deploy).

Each test deploys its own tiny two-linux-node lab (LINUX_LAB_DEFINITION), so
the slice needs the node image pullable on the host. Deselect with
`-m "not deploy"` for the cheap contract run.

The long operations are async jobs: tests submit, then `wait_job` to the
terminal state and assert on the job's `result`.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import aclosing

import pytest
from twinlab_client import (
    ConfigureResponse,
    DeployResponse,
    DestroyResponse,
    Duration,
    Job,
    LabDetail,
    LabEvent,
    SuiteReport,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    TwinlabClient,
    ValidationTest,
)

from _config import LINUX_LAB_DEFINITION, LabFactory, UserClientFactory

pytestmark = pytest.mark.deploy

# A linux-node deploy takes tens of seconds; leave slack for a loaded host.
JOB_WAIT = 600.0


async def _deployed_lab(admin: TwinlabClient, make_lab: LabFactory) -> LabDetail:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name)
    assert job.kind == "deploy"
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, DeployResponse)
    assert done.result.status == "deployed"
    assert done.result.configuration is None and done.result.validation is None
    return await admin.get_lab(lab.name)


async def _first_event_for(stream: AsyncGenerator[LabEvent], lab: str) -> LabEvent:
    async for event in stream:
        if event.lab == lab:
            return event
    raise AssertionError("event stream ended without a matching event")


async def test_deploy_lifecycle(admin: TwinlabClient, make_lab: LabFactory) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)

    # Submit returns the RUNNING job; a real deploy takes seconds, so an
    # immediate read must still see it running (and in the history list).
    job = await admin.deploy_lab(lab.name)
    assert job.status == "running"
    assert job.result is None and job.error is None and job.finished_at is None
    seen = await admin.get_job(lab.name, job.id)
    assert seen.status == "running"
    assert next(j.id for j in await admin.list_jobs(lab.name)) == job.id

    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, DeployResponse)
    assert done.result.status == "deployed"
    assert done.finished_at is not None

    detail = await admin.get_lab(lab.name)
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
    again_done = await admin.wait_job(detail.name, again.id, timeout=JOB_WAIT)
    assert again_done.status == "succeeded", again_done.error

    # Destroy keeps the record, redeployable.
    destroy = await admin.destroy_lab(detail.name)
    destroy_done = await admin.wait_job(detail.name, destroy.id, timeout=JOB_WAIT)
    assert destroy_done.status == "succeeded", destroy_done.error
    assert isinstance(destroy_done.result, DestroyResponse)
    assert destroy_done.result.status == "destroyed"
    after = await admin.get_lab(detail.name)
    assert after.status == "destroyed"
    assert after.definition is not None  # the record survives with its definition
    assert after.nodes == []

    # A destroyed (not-running) lab refuses a plain destroy: a SYNCHRONOUS
    # 409 at submit, not the existence-hiding 404 (contract delta 11).
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.destroy_lab(detail.name)
    assert excinfo.value.status_code == 409

    # A destroyed lab deploys fresh from the stored definition.
    redeploy = await admin.deploy_lab(detail.name)
    redeploy_done = await admin.wait_job(detail.name, redeploy.id, timeout=JOB_WAIT)
    assert redeploy_done.status == "succeeded", redeploy_done.error


async def test_deploy_mutex_rejects_concurrent_submits(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)

    outcomes = await asyncio.gather(
        admin.deploy_lab(lab.name), admin.deploy_lab(lab.name), return_exceptions=True
    )
    # ONE running job per lab: exactly one submit wins the mutex; the other
    # is rejected at submit time (deterministic — no timing assumption).
    winners = [o for o in outcomes if isinstance(o, Job)]
    errors = [o for o in outcomes if isinstance(o, TwinlabApiError)]
    assert len(winners) == 1, outcomes
    assert len(errors) == 1, outcomes
    assert errors[0].status_code == 409

    # While the winner runs, EVERY kind is locked out — destroy too.
    with pytest.raises(TwinlabApiError) as excinfo:
        _ = await admin.destroy_lab(lab.name, remove=True)
    assert excinfo.value.status_code == 409

    # Drain so teardown's destroy isn't refused by the still-running job.
    _ = await admin.wait_job(lab.name, winners[0].id, timeout=JOB_WAIT)


async def test_links_live_state(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)
    table = await admin.links(detail.name)
    assert table.live is True
    (link,) = table.links
    assert link.oper_state == "up"
    # Cross-endpoint consistency: the served interface name is exactly what
    # /interfaces reports for that node (delta 14's whole point — no guessing).
    inventory = {entry.node: entry.interfaces for entry in await admin.interfaces(detail.name)}
    for endpoint in link.endpoints:
        assert endpoint.state == "up"
        assert endpoint.interface in {iface.name for iface in inventory[endpoint.node]}


async def test_netem_set_show_clear(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)
    # The link table names the n1-n2 link interface authoritatively (before
    # delta 14 this test guessed "first non-mgmt ethN" off the inventory).
    (link,) = (await admin.links(detail.name)).links
    interface = next(e.interface for e in link.endpoints if e.node == "n1")

    _ = await admin.set_netem(detail.name, "n1", interface, delay=Duration(50.0, "ms"), loss=1.0)
    shaped = {imp.interface: imp for imp in await admin.show_netem(detail.name, "n1")}
    impairment = shaped[interface]
    assert impairment.delay == Duration(50.0, "ms")
    assert impairment.loss == 1.0
    assert impairment.jitter is None

    # The links view carries the same impairment on the endpoint it was set
    # on — and an impaired-but-up link still reads "up" (impairment is
    # requested behavior, not degraded health).
    (shaped_link,) = (await admin.links(detail.name)).links
    by_node = {endpoint.node: endpoint for endpoint in shaped_link.endpoints}
    set_impairment = by_node["n1"].impairment
    assert set_impairment is not None and set_impairment.delay == Duration(50.0, "ms")
    assert by_node["n2"].impairment is None
    assert shaped_link.oper_state == "up"

    # REPLACE semantics: a call with no impairments clears the interface —
    # and show lists only ACTIVELY impaired interfaces, so it disappears.
    _ = await admin.set_netem(detail.name, "n1", interface)
    cleared = {imp.interface: imp for imp in await admin.show_netem(detail.name, "n1")}
    assert interface not in cleared
    (cleared_link,) = (await admin.links(detail.name)).links
    assert all(endpoint.impairment is None for endpoint in cleared_link.endpoints)


async def test_node_power_cycle(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)

    _ = await admin.node_power(detail.name, "n1", "stop")
    stopped = {node.name: node for node in (await admin.get_lab(detail.name)).nodes}
    assert stopped["n1"].state != "running"
    assert stopped["n2"].state == "running"

    # The listing splits presence from liveness: both containers exist, one runs.
    row = {r.name: r for r in await admin.list_labs()}[detail.name]
    assert row.nodes == 2
    assert row.nodes_running == 1

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

    deploy = await admin.deploy_lab(lab.name, configure=True)
    deploy_done = await admin.wait_job(lab.name, deploy.id, timeout=JOB_WAIT)
    assert deploy_done.status == "succeeded", deploy_done.error
    result = deploy_done.result
    assert isinstance(result, DeployResponse)
    assert result.status == "configured"
    assert result.configuration is not None
    assert all(node.status == "configured" for node in result.configuration)
    assert result.validation is not None and result.validation[0].failed == 0
    assert (await admin.get_lab(lab.name)).config_time_status == "passed"

    # A failing config-time gate is DATA: the job SUCCEEDS with
    # result.status="validation_failed", lab still deployed, gate red and
    # unambiguous in the record.
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
    configure = await admin.configure_lab(lab.name)
    configure_done = await admin.wait_job(lab.name, configure.id, timeout=JOB_WAIT)
    assert configure_done.status == "succeeded", configure_done.error
    outcome = configure_done.result
    assert isinstance(outcome, ConfigureResponse)
    assert outcome.status == "validation_failed"
    detail = await admin.get_lab(lab.name)
    assert detail.status == "deployed"
    assert detail.config_time_status == "failed"

    # Skipping the gate RETAINS the previous (failed) result — never erases it.
    skip = await admin.configure_lab(lab.name, skip_config_time_checks=True)
    skip_done = await admin.wait_job(lab.name, skip.id, timeout=JOB_WAIT)
    assert skip_done.status == "succeeded", skip_done.error
    skipped = skip_done.result
    assert isinstance(skipped, ConfigureResponse)
    assert skipped.status == "configured"
    assert (await admin.get_lab(lab.name)).config_time_status == "failed"

    # A manual run persists as the suite's last run but NEVER moves the gate.
    run = await admin.run_test_suite(lab.name, "manual")
    assert run.kind == "suite_run"
    run_done = await admin.wait_job(lab.name, run.id, timeout=JOB_WAIT)
    assert run_done.status == "succeeded", run_done.error
    report = run_done.result
    assert isinstance(report, SuiteReport)
    assert report.failed == 0 and report.passed >= 1
    suites_state = await admin.get_test_suites(lab.name)
    assert suites_state.last_validation["manual"].passed >= 1
    assert suites_state.config_time_status == "failed"
