"""Host resource snapshot (delta 30).

What the machine running the labs is spending, so an operator can answer "is
there room for this lab" and, afterwards, "was the host already loaded when
that deploy went wrong".

The readings come from `/proc` through psutil. The backend runs in a
container, but `/proc/stat`, `/proc/meminfo` and `/proc/loadavg` are NOT
namespaced by Docker — a container reads the HOST's values there, which is
exactly what is wanted here (and why no privilege or extra mount is needed).
Disk is different: `statvfs` needs the filesystem in this mount namespace, so
only paths the backend actually has can be reported — today the host-shared
`LAB_FILES_DIR`, which is bind-mounted same-path.

Per-container attribution is NOT here: it needs the Docker socket, which the
backend deliberately does not have. That lives in the netlab-runner.
"""

from dataclasses import dataclass
from datetime import datetime

import psutil

from twinlab_backend.result import Err, Ok, Result

# The CPU sampler's window. Short enough that the dashboard reflects a spike
# while an operator is watching, long enough that the reading is not noise.
SAMPLE_INTERVAL_SECONDS = 5.0
# One blocking sample at startup so the first reading is a real measurement
# rather than psutil's since-boot 0.0. Paid once, before the app serves.
_PRIME_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class HostMetricsError:
    message: str


@dataclass(frozen=True, slots=True)
class CpuSnapshot:
    cores: int
    # Host-wide, averaged over the window since the previous sample.
    utilization_percent: float
    load1: float
    load5: float
    load15: float


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    total_bytes: int
    used_bytes: int
    # What a new workload could actually claim — NOT total minus used, which
    # counts reclaimable page cache as spent.
    available_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class SwapSnapshot:
    total_bytes: int
    used_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class DiskSnapshot:
    # The path asked about; the figures are for the filesystem holding it.
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


@dataclass(frozen=True, slots=True)
class HostSnapshot:
    sampled_at: datetime
    cpu: CpuSnapshot
    memory: MemorySnapshot
    swap: SwapSnapshot
    disks: tuple[DiskSnapshot, ...]


def _gib(value: int) -> str:
    return f"{value / 1024**3:.1f} GiB"


def summary_line(snapshot: HostSnapshot) -> str:
    """One line for a job's step log. A deploy that went wrong is often a
    deploy that started on a host with nothing left, and that is only
    answerable afterwards if the reading was written down at the time."""
    parts = [
        f"cpu {snapshot.cpu.utilization_percent:.0f}% of {snapshot.cpu.cores} cores",
        f"load {snapshot.cpu.load1:.2f}",
        f"memory {_gib(snapshot.memory.used_bytes)} used, "
        f"{_gib(snapshot.memory.available_bytes)} available",
    ]
    parts.extend(f"{_gib(disk.free_bytes)} free on {disk.path}" for disk in snapshot.disks)
    return "; ".join(parts)


def prime_cpu_sampling() -> None:
    """Establish the baseline `collect` measures against.

    psutil's `cpu_percent(interval=None)` reports utilization since ITS OWN
    previous call, so the very first call would return a since-boot average
    (0.0 in practice). Calling it once with a real interval at startup makes
    every later sample a true window."""
    _ = psutil.cpu_percent(interval=_PRIME_INTERVAL_SECONDS)


def collect(disk_paths: tuple[str, ...], now: datetime) -> Result[HostSnapshot, HostMetricsError]:
    """One reading. Blocking (a handful of /proc reads and statvfs calls), so
    callers run it in a threadpool."""
    cores = psutil.cpu_count(logical=True)
    if cores is None:
        # Documented as possible by psutil; unreachable on Linux, and a made-up
        # core count would silently distort every percentage derived from it.
        return Err(HostMetricsError("the host CPU count could not be determined"))

    try:
        utilization = psutil.cpu_percent(interval=None)
        load1, load5, load15 = psutil.getloadavg()
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disks = tuple(
            DiskSnapshot(
                path=path,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                percent=usage.percent,
            )
            for path, usage in ((path, psutil.disk_usage(path)) for path in disk_paths)
        )
    except (OSError, psutil.Error) as exc:
        # The boundary: /proc or statvfs refused. Reported as a value so the
        # sampler can keep serving the previous (visibly older) snapshot.
        # psutil.Error is NOT an OSError subclass, and missing it here would
        # kill the sampler task silently — sampling would stop forever with
        # only a stale `sampled_at` as the tell.
        return Err(HostMetricsError(f"host metrics unavailable: {exc}"))

    return Ok(
        HostSnapshot(
            sampled_at=now,
            cpu=CpuSnapshot(
                cores=cores,
                utilization_percent=utilization,
                load1=load1,
                load5=load5,
                load15=load15,
            ),
            memory=MemorySnapshot(
                total_bytes=memory.total,
                used_bytes=memory.used,
                available_bytes=memory.available,
                percent=memory.percent,
            ),
            swap=SwapSnapshot(
                total_bytes=swap.total,
                used_bytes=swap.used,
                percent=swap.percent,
            ),
            disks=disks,
        )
    )
