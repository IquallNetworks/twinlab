"""Host resources: what the machine running the labs is spending (delta 30).

Any authenticated user may read these. They name no lab and reveal nothing
about who owns what — and every user deciding whether to deploy needs to know
whether there is room, the same reasoning that leaves `GET /catalog` ungated.

Two resources with deliberately different latency: `GET /host` serves a
snapshot the backend samples locally on a timer (instant, always available),
while `GET /host/docker` asks the runner, which walks the daemon's whole
image and cache inventory (a second or more, and gone if the sidecar is down).
"""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth.dependencies import CurrentUserDep
from twinlab_backend.deps import HostSnapshotDep, RunnerClientDep
from twinlab_backend.result import Err
from twinlab_backend.services.host_metrics import HostSnapshot

router = APIRouter(prefix="/host", tags=["host"])


class CpuOut(BaseModel):
    cores: int
    utilization_percent: float
    load1: float
    load5: float
    load15: float


class MemoryOut(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float


class SwapOut(BaseModel):
    total_bytes: int
    used_bytes: int
    percent: float


class DiskOut(BaseModel):
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class HostResourcesOut(BaseModel):
    # When the reading was taken. A snapshot older than the sample interval
    # means sampling is failing — the value is honest about its own age rather
    # than being silently refreshed.
    sampled_at: datetime
    cpu: CpuOut
    memory: MemoryOut
    swap: SwapOut
    # Only filesystems the backend can see; `LAB_FILES_DIR` when configured.
    disks: list[DiskOut]


def _resources_out(snapshot: HostSnapshot) -> HostResourcesOut:
    return HostResourcesOut(
        sampled_at=snapshot.sampled_at,
        cpu=CpuOut(
            cores=snapshot.cpu.cores,
            utilization_percent=snapshot.cpu.utilization_percent,
            load1=snapshot.cpu.load1,
            load5=snapshot.cpu.load5,
            load15=snapshot.cpu.load15,
        ),
        memory=MemoryOut(
            total_bytes=snapshot.memory.total_bytes,
            used_bytes=snapshot.memory.used_bytes,
            available_bytes=snapshot.memory.available_bytes,
            percent=snapshot.memory.percent,
        ),
        swap=SwapOut(
            total_bytes=snapshot.swap.total_bytes,
            used_bytes=snapshot.swap.used_bytes,
            percent=snapshot.swap.percent,
        ),
        disks=[
            DiskOut(
                path=disk.path,
                total_bytes=disk.total_bytes,
                used_bytes=disk.used_bytes,
                free_bytes=disk.free_bytes,
                percent=disk.percent,
            )
            for disk in snapshot.disks
        ],
    )


@router.get("")
async def host_resources(_: CurrentUserDep, snapshot: HostSnapshotDep) -> HostResourcesOut:
    if snapshot is None:
        # No sample has ever succeeded (the sampler primes one before the app
        # serves, so this means /proc itself is refusing). Nothing to serve is
        # better than zeros that read as an idle host.
        raise ApiError(503, "host_metrics_unavailable", "the host has not been sampled yet")
    return _resources_out(snapshot)


class DockerDiskOut(BaseModel):
    # "images" | "containers" | "volumes" | "build_cache"
    kind: str
    total: int
    active: int
    size_bytes: int
    # What `docker system prune` could return — an unused image only counts its
    # unshared layers, so this is smaller than size for anything shared.
    reclaimable_bytes: int


class DockerUsageOut(BaseModel):
    # The daemon's data root. Its filesystem is NOT necessarily one of the
    # `disks` in GET /host — the backend can only measure what it mounts.
    root_dir: str
    containers_running: int
    containers_paused: int
    containers_stopped: int
    containers_total: int
    images_total: int
    disk: list[DockerDiskOut]


@router.get("/docker")
async def docker_usage(_: CurrentUserDep, runner: RunnerClientDep) -> DockerUsageOut:
    usage = await runner.docker_usage()
    if isinstance(usage, Err):
        raise ApiError(
            503,
            "docker_usage_unavailable",
            f"the daemon's usage could not be read: {usage.error.message}",
        )
    return DockerUsageOut(
        root_dir=usage.value.root_dir,
        containers_running=usage.value.containers_running,
        containers_paused=usage.value.containers_paused,
        containers_stopped=usage.value.containers_stopped,
        containers_total=usage.value.containers_total,
        images_total=usage.value.images_total,
        disk=[
            DockerDiskOut(
                kind=entry.kind,
                total=entry.total,
                active=entry.active,
                size_bytes=entry.size_bytes,
                reclaimable_bytes=entry.reclaimable_bytes,
            )
            for entry in usage.value.disk
        ],
    )
