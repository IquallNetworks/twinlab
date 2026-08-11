"""Read-only Docker Engine API access over the mounted socket.

The runner already owns the Docker socket (config push execs into node
containers through it), so it is also the only component that can answer what
the host is spending on labs — the backend deliberately has no socket.

Why the Engine API rather than the `docker` CLI the rest of the runner shells
out to: `docker stats` and `docker system df` emit only HUMAN-formatted sizes
("41.2MiB / 62.7GiB", "24.42GB"), so a byte count parsed back out of them
would be invented precision. The API serves raw integers. The cost is a tiny
unix-socket HTTP client, which the stdlib covers.

Paths are UNVERSIONED (`/info`, not `/v1.43/info`): the daemon then answers
with its own current API version, which is what a host-coupled component
wants. The socket and JSON handling are the boundary — the one place
`try`/`except` lives; every outcome is returned as a typed value.
"""

import socket
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException
from typing import override

from pydantic import BaseModel, Field, ValidationError

from netlab_runner.runner import RunnerError

DOCKER_SOCKET_PATH = "/var/run/docker.sock"

# A local daemon query, but `/system/df` walks every image, volume and build
# cache record (measured at ~1.2s on a host with 45 images and 463 cache
# entries), so it needs real headroom.
_DF_TIMEOUT_SECONDS = 60.0
# `stats?stream=false` makes the daemon take two samples ~1s apart so it can
# report a CPU delta; the timeout only guards a wedged daemon.
_STATS_TIMEOUT_SECONDS = 15.0
_INFO_TIMEOUT_SECONDS = 15.0


class _UnixHTTPConnection(HTTPConnection):
    """HTTPConnection over an AF_UNIX socket. The host part of the URL is
    meaningless here but http.client insists on one, so it is a placeholder."""

    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    @override
    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


def _get(path: str, timeout: float, socket_path: str) -> bytes | RunnerError:
    """One GET against the daemon. Blocking: callers run it in a threadpool."""
    conn = _UnixHTTPConnection(socket_path, timeout)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        status = response.status
    except (OSError, HTTPException) as exc:
        return RunnerError(stage="docker-api", message=f"GET {path} failed: {exc}")
    finally:
        conn.close()

    if status != 200:
        return RunnerError(
            stage="docker-api",
            message=f"GET {path} returned {status}",
            output=body.decode("utf-8", errors="replace")[-2000:],
        )
    return body


# --- /info ------------------------------------------------------------------


class _Info(BaseModel):
    containers: int = Field(alias="Containers")
    containers_running: int = Field(alias="ContainersRunning")
    containers_paused: int = Field(alias="ContainersPaused")
    containers_stopped: int = Field(alias="ContainersStopped")
    images: int = Field(alias="Images")
    docker_root_dir: str = Field(alias="DockerRootDir")


# --- /system/df -------------------------------------------------------------


class _DfImage(BaseModel):
    size: int = Field(alias="Size")
    shared_size: int = Field(alias="SharedSize")
    # How many containers use this image. Docker's own `system df` calls an
    # image with none of them reclaimable, and that is the number an operator
    # is looking for when the disk fills.
    containers: int = Field(alias="Containers")


class _DfContainer(BaseModel):
    # The writable layer. Absent (null) unless the daemon computed sizes.
    size_rw: int | None = Field(default=None, alias="SizeRw")
    state: str = Field(default="", alias="State")


class _DfVolumeUsage(BaseModel):
    size: int = Field(default=0, alias="Size")
    ref_count: int = Field(default=0, alias="RefCount")


class _DfVolume(BaseModel):
    usage_data: _DfVolumeUsage | None = Field(default=None, alias="UsageData")


class _DfBuildCache(BaseModel):
    size: int = Field(default=0, alias="Size")
    # Shared records are counted in the total but are NOT reclaimable — this is
    # exactly how `docker system df` splits the build cache's two numbers.
    shared: bool = Field(default=False, alias="Shared")
    in_use: bool = Field(default=False, alias="InUse")


class _Df(BaseModel):
    # The deduplicated on-disk size of all image layers — what `docker system
    # df` prints as the images row's SIZE. Summing per-image `Size` would
    # double-count shared layers.
    layers_size: int = Field(alias="LayersSize")
    # Go marshals a nil slice as `null`, so every collection here is genuinely
    # nullable on the wire and is normalized once, at this boundary.
    images: list[_DfImage] | None = Field(default=None, alias="Images")
    containers: list[_DfContainer] | None = Field(default=None, alias="Containers")
    volumes: list[_DfVolume] | None = Field(default=None, alias="Volumes")
    build_cache: list[_DfBuildCache] | None = Field(default=None, alias="BuildCache")


@dataclass(frozen=True, slots=True)
class DiskEntry:
    """One row of `docker system df`: what a kind of object costs on disk, and
    how much of that could be freed."""

    kind: str  # "images" | "containers" | "volumes" | "build_cache"
    total: int
    active: int
    size_bytes: int
    reclaimable_bytes: int


@dataclass(frozen=True, slots=True)
class DockerUsage:
    root_dir: str
    containers_running: int
    containers_paused: int
    containers_stopped: int
    containers_total: int
    images_total: int
    disk: list[DiskEntry]


def _disk_entries(df: _Df) -> list[DiskEntry]:
    images = df.images or []
    containers = df.containers or []
    volumes = df.volumes or []
    build_cache = df.build_cache or []

    active_images = [image for image in images if image.containers > 0]
    # Docker charges an unused image only its UNSHARED bytes as reclaimable:
    # its shared layers survive with whatever else references them.
    images_reclaimable = sum(
        image.size - image.shared_size for image in images if image.containers == 0
    )

    running = [c for c in containers if c.state == "running"]
    containers_size = sum(c.size_rw or 0 for c in containers)
    containers_reclaimable = sum(c.size_rw or 0 for c in containers if c.state != "running")

    volume_usage = [(v.usage_data.size, v.usage_data.ref_count) for v in volumes if v.usage_data]
    volumes_size = sum(size for size, _ in volume_usage)
    volumes_reclaimable = sum(size for size, refs in volume_usage if refs == 0)

    return [
        DiskEntry(
            kind="images",
            total=len(images),
            active=len(active_images),
            size_bytes=df.layers_size,
            reclaimable_bytes=images_reclaimable,
        ),
        DiskEntry(
            kind="containers",
            total=len(containers),
            active=len(running),
            size_bytes=containers_size,
            reclaimable_bytes=containers_reclaimable,
        ),
        DiskEntry(
            kind="volumes",
            total=len(volumes),
            active=sum(1 for _, refs in volume_usage if refs > 0),
            size_bytes=volumes_size,
            reclaimable_bytes=volumes_reclaimable,
        ),
        DiskEntry(
            kind="build_cache",
            total=len(build_cache),
            active=sum(1 for c in build_cache if c.in_use),
            size_bytes=sum(c.size for c in build_cache),
            reclaimable_bytes=sum(c.size for c in build_cache if not c.shared),
        ),
    ]


def parse_disk_entries(body: bytes) -> list[DiskEntry] | RunnerError:
    """`/system/df` → the four rows `docker system df` prints."""
    try:
        df = _Df.model_validate_json(body)
    except ValidationError as exc:
        return RunnerError(stage="docker-api", message=f"unexpected system/df response: {exc}")
    return _disk_entries(df)


def docker_usage(socket_path: str = DOCKER_SOCKET_PATH) -> DockerUsage | RunnerError:
    """The daemon's own counts plus its disk footprint by kind."""
    info_body = _get("/info", _INFO_TIMEOUT_SECONDS, socket_path)
    if isinstance(info_body, RunnerError):
        return info_body
    df_body = _get("/system/df", _DF_TIMEOUT_SECONDS, socket_path)
    if isinstance(df_body, RunnerError):
        return df_body

    try:
        info = _Info.model_validate_json(info_body)
    except ValidationError as exc:
        return RunnerError(stage="docker-api", message=f"unexpected info response: {exc}")
    disk = parse_disk_entries(df_body)
    if isinstance(disk, RunnerError):
        return disk

    return DockerUsage(
        root_dir=info.docker_root_dir,
        containers_running=info.containers_running,
        containers_paused=info.containers_paused,
        containers_stopped=info.containers_stopped,
        containers_total=info.containers,
        images_total=info.images,
        disk=disk,
    )


# --- /containers/{id}/stats -------------------------------------------------


class _CpuUsage(BaseModel):
    total_usage: int = 0


class _CpuStats(BaseModel):
    cpu_usage: _CpuUsage = Field(default_factory=_CpuUsage)
    # Both absent for a container that is not running — the tell that there is
    # no sample to compute a percentage from.
    system_cpu_usage: int | None = None
    online_cpus: int | None = None


class _MemoryStats(BaseModel):
    usage: int | None = None
    limit: int | None = None
    # cgroup v2 detail counters; `inactive_file` is the page cache Docker's own
    # MemUsage subtracts, so a node's number matches what `docker stats` shows.
    stats: dict[str, int] | None = None


class _NetworkStats(BaseModel):
    rx_bytes: int = 0
    tx_bytes: int = 0


class _PidsStats(BaseModel):
    current: int | None = None


class _Stats(BaseModel):
    cpu_stats: _CpuStats = Field(default_factory=_CpuStats)
    precpu_stats: _CpuStats = Field(default_factory=_CpuStats)
    memory_stats: _MemoryStats = Field(default_factory=_MemoryStats)
    networks: dict[str, _NetworkStats] | None = None
    pids_stats: _PidsStats = Field(default_factory=_PidsStats)


@dataclass(frozen=True, slots=True)
class ContainerStats:
    """One container's instantaneous cost. Every measure is nullable because a
    STOPPED container still answers 200 with an empty payload — reporting that
    as 0% would claim an idle container where there is no container running."""

    container: str
    cpu_percent: float | None
    memory_bytes: int | None
    memory_limit_bytes: int | None
    net_rx_bytes: int | None
    net_tx_bytes: int | None
    pids: int | None


def _cpu_percent(stats: _Stats) -> float | None:
    """Docker's own formula: the container's share of total system CPU time
    over the sample window, scaled by the core count — so a container pinning
    two cores reads 200%."""
    system = stats.cpu_stats.system_cpu_usage
    pre_system = stats.precpu_stats.system_cpu_usage
    cores = stats.cpu_stats.online_cpus
    if system is None or pre_system is None or cores is None:
        return None
    system_delta = system - pre_system
    cpu_delta = stats.cpu_stats.cpu_usage.total_usage - stats.precpu_stats.cpu_usage.total_usage
    if system_delta <= 0 or cpu_delta < 0:
        return None
    return (cpu_delta / system_delta) * cores * 100.0


def _memory_bytes(stats: _Stats) -> int | None:
    usage = stats.memory_stats.usage
    if usage is None:
        return None
    inactive_file = (stats.memory_stats.stats or {}).get("inactive_file", 0)
    return max(usage - inactive_file, 0)


def parse_stats(container: str, body: bytes) -> ContainerStats | RunnerError:
    try:
        stats = _Stats.model_validate_json(body)
    except ValidationError as exc:
        return RunnerError(stage="docker-api", message=f"unexpected stats response: {exc}")

    networks = stats.networks
    return ContainerStats(
        container=container,
        cpu_percent=_cpu_percent(stats),
        memory_bytes=_memory_bytes(stats),
        memory_limit_bytes=stats.memory_stats.limit,
        net_rx_bytes=sum(n.rx_bytes for n in networks.values()) if networks else None,
        net_tx_bytes=sum(n.tx_bytes for n in networks.values()) if networks else None,
        pids=stats.pids_stats.current,
    )


def container_stats(
    container: str, socket_path: str = DOCKER_SOCKET_PATH
) -> ContainerStats | RunnerError:
    """One container's stats. `stream=false` makes the daemon do the two-sample
    work itself, so a CPU percentage comes back from a single request."""
    body = _get(f"/containers/{container}/stats?stream=false", _STATS_TIMEOUT_SECONDS, socket_path)
    if isinstance(body, RunnerError):
        return body
    return parse_stats(container, body)
