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
from pathlib import Path

import pytest
from twinlab_client import (
    ConfigureResponse,
    DeployResponse,
    DestroyResponse,
    Duration,
    Job,
    JobEvent,
    LabDetail,
    LabEvent,
    NetemAction,
    PowerAction,
    SuiteReport,
    TestCase,
    TestExpectation,
    TestSuite,
    TwinlabApiError,
    TwinlabClient,
    ValidationTest,
)

from _config import (
    LAN_LAB_DEFINITION,
    LINUX_LAB_DEFINITION,
    MIXED_NOS_LAB_DEFINITION,
    LabFactory,
    UserClientFactory,
)

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


async def _first_event_for(stream: AsyncGenerator[LabEvent | JobEvent], lab: str) -> LabEvent:
    async for event in stream:
        if isinstance(event, LabEvent) and event.lab == lab:
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
    # Delta 19: the deploy snapshotted exactly what it deployed — the stored
    # definition — so the lab starts undrifted.
    assert detail.deployed_definition == detail.definition
    assert detail.definition_drifted is False
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

    # Delta 19: a SEMANTIC edit to the stored definition of a running lab
    # flags drift — a hint, never a gate. (A comment-only edit would NOT:
    # PUT normalizes the stored YAML, stripping comments/formatting, so only
    # changes that survive normalization can differ from the snapshot.)
    drifted = await admin.update_definition(
        detail.name, LINUX_LAB_DEFINITION.replace("[n1, n2]", "[n1, n2, n3]")
    )
    assert drifted.definition_drifted is True
    assert drifted.deployed_definition == detail.deployed_definition
    row = next(r for r in await admin.list_labs() if r.name == detail.name)
    assert row.definition_drifted is True

    # Deploying over a running lab is allowed (overwrite in place) — and the
    # redeploy re-snapshots, clearing the drift.
    again = await admin.deploy_lab(detail.name)
    again_done = await admin.wait_job(detail.name, again.id, timeout=JOB_WAIT)
    assert again_done.status == "succeeded", again_done.error
    assert (await admin.get_lab(detail.name)).definition_drifted is False

    # Destroy keeps the record, redeployable.
    destroy = await admin.destroy_lab(detail.name)
    destroy_done = await admin.wait_job(detail.name, destroy.id, timeout=JOB_WAIT)
    assert destroy_done.status == "succeeded", destroy_done.error
    assert isinstance(destroy_done.result, DestroyResponse)
    assert destroy_done.result.status == "destroyed"
    after = await admin.get_lab(detail.name)
    assert after.status == "destroyed"
    assert after.definition is not None  # the record survives with its definition
    # Delta 19: the snapshot describes a RUNNING environment — destroy clears
    # it, and with nothing running there is nothing to drift from.
    assert after.deployed_definition is None
    assert after.definition_drifted is None
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


async def test_nodes_resolve_each_other_by_name(admin: TwinlabClient, make_lab: LabFactory) -> None:
    """Host-shared lab files (up-parity gap 4): netlab delivers an all-nodes
    /etc/hosts as a node_files/ bind, which inline deploy used to strip —
    name-based resolution between nodes was silently absent. With the bind
    rewritten onto the materialized tree, ping BY NAME (not IP) works. The
    hosts file maps names to LINK addresses, which only exist once config
    push assigns them — so this deploys with configure."""
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name, configure=True)
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, DeployResponse)
    assert done.result.status == "configured"
    detail = await admin.get_lab(lab.name)
    ping = {
        "names": TestSuite(
            tests={
                "hosts": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(
                        # The name is the whole point — no address template here.
                        command="ping -c 2 -W 2 n2",
                        # Leading space: "50% packet loss" must not match.
                        expect=TestExpectation(contains=" 0% packet loss"),
                    ),
                )
            },
        )
    }
    _ = await admin.put_test_suites(detail.name, ping)
    run = await admin.run_test_suite(detail.name, "names")
    run_done = await admin.wait_job(detail.name, run.id, timeout=JOB_WAIT)
    assert run_done.status == "succeeded", run_done.error
    report = run_done.result
    assert isinstance(report, SuiteReport)
    assert report.failed == 0 and report.passed >= 1


async def test_lan_deploys_via_host_bridge_and_destroy_removes_it(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    """A multi-access (3-endpoint) link end-to-end: the deploy creates the host
    bridge netlab's clab provider references (`netlab up` pre-start work, done
    by the hostprep sidecar), traffic actually crosses the segment, and the
    destroy removes the bridge again.

    DEVIATION from the suite's client-only rule: the bridge is host kernel
    state invisible through the API, and leak-checking it is this test's
    point — so two asserts read the host's /sys/class/net directly. The
    deploy marker already assumes the suite runs on the stack's host (node
    images, mgmt routes); this leans on the same assumption.
    """
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LAN_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name, configure=True)
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, DeployResponse)
    assert done.result.status == "configured"

    # ONE logical link, three endpoints, live and up.
    table = await admin.links(lab.name)
    assert table.live is True
    (link,) = table.links
    assert {endpoint.node for endpoint in link.endpoints} == {"n1", "n2", "n3"}
    assert link.oper_state == "up"

    # netlab names the bridge name[0:10]_linkindex.
    bridge = Path("/sys/class/net") / f"{lab.name[:10]}_{link.index}"
    assert (bridge / "bridge").is_dir(), f"host bridge {bridge.name} missing after deploy"

    # Data-plane proof: n1 reaches n3 THROUGH the bridge. The target address
    # is a delta-17 TEMPLATE rendered server-side from the lab's facts —
    # nothing hardcoded, and the render pipeline is exercised live.
    ping = {
        "reach": TestSuite(
            tests={
                "lan": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(
                        command="ping -c 2 -W 2 {{ nodes.n3.interfaces[0].ipv4 | address }}",
                        # Leading space: "50% packet loss" must not match.
                        expect=TestExpectation(contains=" 0% packet loss"),
                    ),
                )
            },
        )
    }
    _ = await admin.put_test_suites(lab.name, ping)
    run = await admin.run_test_suite(lab.name, "reach")
    run_done = await admin.wait_job(lab.name, run.id, timeout=JOB_WAIT)
    assert run_done.status == "succeeded", run_done.error
    report = run_done.result
    assert isinstance(report, SuiteReport)
    assert report.failed == 0 and report.passed >= 1
    # The report's command is the RENDERED one: the fact's real address, and it
    # agrees with the link table's endpoint for n3.
    target = next(e.ipv4 for e in link.endpoints if e.node == "n3")
    assert target is not None
    assert report.results[0].command == f"ping -c 2 -W 2 {target.split('/')[0]}"

    destroy = await admin.destroy_lab(lab.name)
    destroy_done = await admin.wait_job(lab.name, destroy.id, timeout=JOB_WAIT)
    assert destroy_done.status == "succeeded", destroy_done.error
    assert not bridge.exists(), f"host bridge {bridge.name} leaked after destroy"


async def test_netem_set_show_clear(admin: TwinlabClient, make_lab: LabFactory) -> None:
    detail = await _deployed_lab(admin, make_lab)
    # The link table names the n1-n2 link interface authoritatively (before
    # delta 14 this test guessed "first non-mgmt ethN" off the inventory).
    (link,) = (await admin.links(detail.name)).links
    interface = next(e.interface for e in link.endpoints if e.node == "n1")

    _ = await admin.set_netem(
        detail.name,
        NetemAction(node="n1", interface=interface, delay=Duration(50.0, "ms"), loss=1.0),
    )
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
    _ = await admin.set_netem(detail.name, NetemAction(node="n1", interface=interface))
    cleared = {imp.interface: imp for imp in await admin.show_netem(detail.name, "n1")}
    assert interface not in cleared
    (cleared_link,) = (await admin.links(detail.name)).links
    assert all(endpoint.impairment is None for endpoint in cleared_link.endpoints)


async def test_batch_actions_stage_and_report(admin: TwinlabClient, make_lab: LabFactory) -> None:
    """Delta 24: many impairments + a power event in ONE request — the round
    trip the frontend's two-endpoint link fan-out used to choreograph."""
    detail = await _deployed_lab(admin, make_lab)
    (link,) = (await admin.links(detail.name)).links
    interfaces = {endpoint.node: endpoint.interface for endpoint in link.endpoints}

    # Both endpoints of the link, shaped identically, plus an item naming a node
    # that does not exist: the batch still RUNS, and only that item fails.
    report = await admin.apply_actions(
        detail.name,
        [
            NetemAction(node="n1", interface=interfaces["n1"], delay=Duration(40.0, "ms")),
            NetemAction(node="n2", interface=interfaces["n2"], delay=Duration(40.0, "ms")),
            NetemAction(node="ghost", interface="eth1", loss=1.0),
        ],
    )
    assert [result.ok for result in report.results] == [True, True, False]
    assert report.results[2].code == "node_not_found"

    # Both directions really are shaped — the batch is the whole link's write.
    (shaped,) = (await admin.links(detail.name)).links
    by_node = {endpoint.node: endpoint for endpoint in shaped.endpoints}
    for node in ("n1", "n2"):
        impairment = by_node[node].impairment
        assert impairment is not None and impairment.delay == Duration(40.0, "ms")

    # Power items ride the same batch; a stop is visible in the lab detail.
    powered = await admin.apply_actions(detail.name, [PowerAction(node="n2", action="stop")])
    assert powered.results[0].ok
    stopped = {node.name: node for node in (await admin.get_lab(detail.name)).nodes}
    assert stopped["n2"].state != "running"
    _ = await admin.apply_actions(detail.name, [PowerAction(node="n2", action="start")])

    # An impairment-less item clears (REPLACE), same as the single verb.
    cleared = await admin.apply_actions(
        detail.name, [NetemAction(node="n1", interface=interfaces["n1"])]
    )
    assert cleared.results[0].ok
    assert not [
        imp
        for imp in await admin.show_netem(detail.name, "n1")
        if imp.interface == interfaces["n1"]
    ]


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
                    run=TestCase(
                        command="echo bb-ready", expect=TestExpectation(contains="bb-ready")
                    ),
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
                    run=TestCase(
                        command="echo bb-ready",
                        expect=TestExpectation(contains="bb-will-never-match"),
                    ),
                )
            },
            stage="config-time",
        ),
        "manual": TestSuite(
            tests={
                "ok": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(
                        command="echo bb-ready", expect=TestExpectation(contains="bb-ready")
                    ),
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


async def test_mixed_nos_lab_configures_and_converges(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    """Two DIFFERENT NOSes in one topology (NOS sweep, ROADMAP 17.1): VyOS and
    bird are both admitted platforms on the docker-exec transport, and bird
    delivers its config as a node_files/ bind — the path the host-shared lab
    files fixed. Asserts the whole chain: one deploy configures both platforms,
    and a DEVICE-KEYED suite (delta 17 — one test, a case per device) sees the
    OSPF adjacency come up between them.

    Needs the vyos and bird images on the host; bird is built locally with
    `netlab clab build bird` (see blackbox/README.md)."""
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, MIXED_NOS_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name, configure=True)
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error
    assert isinstance(done.result, DeployResponse)
    assert done.result.status == "configured", done.result.configuration

    # Every link is up, across all three device kinds.
    table = await admin.links(lab.name)
    assert table.live is True
    assert {link.oper_state for link in table.links} == {"up"}

    suites = {
        "adjacency": TestSuite(
            description="FRR and bird agree the shared link's adjacency is Full.",
            tests={
                "ospf_full": ValidationTest(
                    nodes=["v1", "b1"],
                    # Neither command has a packaged TextFSM template and both
                    # platforms spell the state "Full", so contains is enough.
                    run={
                        "vyos": TestCase(
                            command='vtysh -c "show ip ospf neighbor"',
                            expect=TestExpectation(contains="Full"),
                        ),
                        "bird": TestCase(
                            command="birdc show ospf neighbors",
                            expect=TestExpectation(contains="Full"),
                        ),
                    },
                    wait=120,
                )
            },
        )
    }
    _ = await admin.put_test_suites(lab.name, suites)
    run = await admin.run_test_suite(lab.name, "adjacency")
    run_done = await admin.wait_job(lab.name, run.id, timeout=JOB_WAIT)
    assert run_done.status == "succeeded", run_done.error
    report = run_done.result
    assert isinstance(report, SuiteReport)
    # One result per node, both passing — a device-keyed case that missed
    # would report "skip" rather than fail, so assert the passes explicitly.
    assert report.failed == 0, report
    assert report.passed == 2, report


async def test_deploy_job_records_its_phases(admin: TwinlabClient, make_lab: LabFactory) -> None:
    """The step log's whole reason to exist (contract delta 29): a deploy's
    phases run inside the job and used to be invisible — the only progress a
    caller could see was container churn on the SSE stream."""
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name)

    # Steps must be readable WHILE the job runs — a log that only materializes
    # at the end would not be progress. `netlab create` is the first phase and
    # takes seconds, so poll for the first step rather than racing it.
    running_steps: list[str] = []
    for _ in range(60):
        seen = await admin.get_job(lab.name, job.id)
        if seen.steps:
            running_steps = [step.code for step in seen.steps]
            if seen.status == "running":
                break
        await asyncio.sleep(1.0)
    assert running_steps, "no step became visible while the deploy ran"
    assert running_steps[0] == "host_resources"

    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error

    codes = [step.code for step in done.steps]
    # A bare deploy's phases, in order. host_prep is absent on purpose: a
    # two-node p2p link needs no host bridge, and a "nothing to do" step
    # would be noise. host_resources leads (delta 30) because its value is
    # entirely retrospective — what the host had left when this began.
    assert codes == [
        "host_resources",
        "topology_generated",
        "image_preflight",
        "clab_deploy_started",
        "nodes_deployed",
        "nodes_ready",
    ]
    assert "2 nodes" in done.steps[1].message
    assert all(step.level == "info" for step in done.steps), [
        (s.code, s.level, s.message) for s in done.steps
    ]
    # The log only ever grows forward in time.
    assert codes == [step.code for step in sorted(done.steps, key=lambda step: step.at)]


async def test_configure_steps_report_the_push_and_the_gate(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    deploy = await admin.deploy_lab(lab.name)
    _ = await admin.wait_job(lab.name, deploy.id, timeout=JOB_WAIT)

    gate = {
        "gate": TestSuite(
            tests={
                "ok": ValidationTest(
                    nodes=["n1"],
                    run=TestCase(
                        command="echo bb-step", expect=TestExpectation(contains="bb-step")
                    ),
                )
            },
            stage="config-time",
        )
    }
    _ = await admin.put_test_suites(lab.name, gate)

    job = await admin.configure_lab(lab.name)
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error

    assert [step.code for step in done.steps] == [
        "config_push_started",
        "config_pushed",
        "validation",
    ]
    # The two phases that never streamed anywhere: what the push did, and how
    # the gate ended.
    assert "nodes ok" in done.steps[1].message
    assert "1/1 passed" in done.steps[2].message
