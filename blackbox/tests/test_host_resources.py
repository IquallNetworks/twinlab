"""Host resources: the machine's own load, the daemon's footprint, and a
lab's share of it (delta 30).

The cheap half runs against any stack; the per-lab half needs real containers
and carries the deploy marker."""

import pytest
from twinlab_client import TwinlabClient

from _config import LINUX_LAB_DEFINITION, LabFactory, UserClientFactory

JOB_WAIT = 600.0


async def test_host_resources_describe_the_machine(admin: TwinlabClient) -> None:
    host = await admin.host_resources()

    assert host.cpu.cores >= 1
    assert 0.0 <= host.cpu.utilization_percent <= 100.0
    assert host.cpu.load1 >= 0.0
    assert host.memory.total_bytes > 0
    # Available is what a new lab could claim — its own measure, not total
    # minus used, which would count reclaimable page cache as spent.
    assert 0 < host.memory.available_bytes <= host.memory.total_bytes
    assert host.swap.total_bytes >= 0
    # The compose stack requires LAB_FILES_DIR, so its filesystem is reported.
    assert host.disks, "no filesystem reported; LAB_FILES_DIR should be visible"
    for disk in host.disks:
        assert disk.path.startswith("/")
        assert disk.total_bytes > 0
        assert disk.used_bytes + disk.free_bytes <= disk.total_bytes


async def test_host_reading_is_fresh(admin: TwinlabClient) -> None:
    first = await admin.host_resources()
    second = await admin.host_resources()
    # Served from a sampler, so two reads in a row are cheap and non-decreasing
    # in time; a frozen timestamp would mean sampling died.
    assert second.sampled_at >= first.sampled_at


async def test_host_resources_visible_without_admin_roles(
    make_user_client: UserClientFactory,
) -> None:
    # Ungated on purpose: it names no lab, and anyone deciding whether to
    # deploy needs to know whether there is room.
    _, plain = await make_user_client(None)
    host = await plain.host_resources()
    assert host.cpu.cores >= 1


async def test_docker_usage_mirrors_system_df(admin: TwinlabClient) -> None:
    usage = await admin.docker_usage()

    assert usage.root_dir.startswith("/")
    # The stack itself is running, so the daemon has containers and images.
    assert usage.containers_running >= 1
    assert usage.containers_total >= usage.containers_running
    assert usage.images_total >= 1

    by_kind = {entry.kind: entry for entry in usage.disk}
    assert set(by_kind) == {"images", "containers", "volumes", "build_cache"}
    for entry in usage.disk:
        assert entry.active <= entry.total
        # Reclaimable is a subset of what is held: an in-use image, container
        # or volume is not free to delete.
        assert 0 <= entry.reclaimable_bytes <= entry.size_bytes
    assert by_kind["images"].size_bytes > 0


async def test_docker_usage_visible_without_admin_roles(
    make_user_client: UserClientFactory,
) -> None:
    _, plain = await make_user_client(None)
    usage = await plain.docker_usage()
    assert usage.images_total >= 1


async def test_usage_of_an_undeployed_lab_is_not_live(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    usage = await admin.lab_usage(lab.name)
    # A lab with no containers legitimately costs nothing — that is data, not
    # an error.
    assert usage.lab == lab.name
    assert usage.live is False
    assert usage.nodes == []


@pytest.mark.deploy
async def test_deployed_lab_reports_per_node_cost(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name)
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error

    usage = await admin.lab_usage(lab.name)
    assert usage.live is True
    assert len(usage.nodes) == 2
    for node in usage.nodes:
        assert node.state == "running"
        assert node.container.startswith(f"clab-{lab.name}-")
        # A running node always answers: an idle container still has a memory
        # footprint, a cgroup limit and at least one process.
        assert node.cpu_percent is not None and node.cpu_percent >= 0.0
        assert node.memory_bytes is not None and node.memory_bytes > 0
        assert node.memory_limit_bytes is not None and node.memory_limit_bytes > 0
        assert node.pids is not None and node.pids >= 1

    # The whole lab's memory must fit inside the host's — a sanity check that
    # both readings are in bytes and describe the same machine.
    host = await admin.host_resources()
    lab_memory = sum(node.memory_bytes or 0 for node in usage.nodes)
    assert lab_memory < host.memory.total_bytes


@pytest.mark.deploy
async def test_deploy_records_what_the_host_had_left(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name)
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error

    # First step, because its value is entirely retrospective: a deploy that
    # went wrong is often one that started on a host with nothing left.
    codes = [step.code for step in done.steps]
    assert codes[0] == "host_resources"
    message = done.steps[0].message
    assert "cpu" in message and "memory" in message
    assert done.steps[0].level == "info"


@pytest.mark.deploy
async def test_stopped_node_is_unmeasured_not_idle(
    admin: TwinlabClient, make_lab: LabFactory
) -> None:
    lab = await make_lab(None)
    _ = await admin.update_definition(lab.name, LINUX_LAB_DEFINITION)
    job = await admin.deploy_lab(lab.name)
    done = await admin.wait_job(lab.name, job.id, timeout=JOB_WAIT)
    assert done.status == "succeeded", done.error

    nodes = sorted(node.node for node in (await admin.lab_usage(lab.name)).nodes)
    _ = await admin.node_power(lab.name, nodes[0], "stop")

    usage = await admin.lab_usage(lab.name)
    by_node = {node.node: node for node in usage.nodes}
    stopped = by_node[nodes[0]]
    # The row survives with its state; the measures do not pretend to be zero.
    assert stopped.state != "running"
    assert stopped.cpu_percent is None
    assert stopped.memory_bytes is None
    # Its neighbour still reports.
    assert by_node[nodes[1]].cpu_percent is not None
