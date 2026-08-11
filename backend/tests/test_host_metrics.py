"""Host snapshot collection and its step-log line (delta 30).

These run against the real /proc — psutil is the boundary, and a snapshot that
cannot be taken on the machine running the tests is a genuine failure worth
seeing rather than a mock worth trusting."""

from datetime import UTC, datetime

from twinlab_backend.result import Ok
from twinlab_backend.services.host_metrics import (
    CpuSnapshot,
    DiskSnapshot,
    HostSnapshot,
    MemorySnapshot,
    SwapSnapshot,
    collect,
    prime_cpu_sampling,
    summary_line,
)

_NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def test_collect_reports_a_plausible_host() -> None:
    prime_cpu_sampling()
    result = collect((), _NOW)
    assert isinstance(result, Ok), result
    snapshot = result.value

    assert snapshot.sampled_at == _NOW
    assert snapshot.cpu.cores >= 1
    assert 0.0 <= snapshot.cpu.utilization_percent <= 100.0
    assert snapshot.cpu.load1 >= 0.0
    assert snapshot.memory.total_bytes > 0
    # Available is what a new lab could claim, and reclaimable cache means it is
    # NOT simply total minus used.
    assert 0 < snapshot.memory.available_bytes <= snapshot.memory.total_bytes
    assert 0.0 <= snapshot.memory.percent <= 100.0
    assert snapshot.swap.total_bytes >= 0
    assert snapshot.disks == ()


def test_collect_measures_the_requested_paths() -> None:
    prime_cpu_sampling()
    result = collect(("/",), _NOW)
    assert isinstance(result, Ok), result
    (root,) = result.value.disks
    assert root.path == "/"
    assert root.total_bytes > 0
    assert root.used_bytes + root.free_bytes <= root.total_bytes


def test_a_missing_path_is_an_error_value_not_an_exception() -> None:
    result = collect(("/no/such/path/twinlab",), _NOW)
    # Errors as values: the sampler keeps serving the previous snapshot rather
    # than the loop dying on an OSError.
    assert not isinstance(result, Ok)
    assert "unavailable" in result.error.message


def test_summary_line_reads_as_a_sentence() -> None:
    snapshot = HostSnapshot(
        sampled_at=_NOW,
        cpu=CpuSnapshot(cores=8, utilization_percent=34.2, load1=1.5, load5=1.0, load15=0.8),
        memory=MemorySnapshot(
            total_bytes=64 * 1024**3,
            used_bytes=12 * 1024**3,
            available_bytes=50 * 1024**3,
            percent=18.75,
        ),
        swap=SwapSnapshot(total_bytes=0, used_bytes=0, percent=0.0),
        disks=(
            DiskSnapshot(
                path="/var/lib/twinlab/lab-files",
                total_bytes=500 * 1024**3,
                used_bytes=290 * 1024**3,
                free_bytes=210 * 1024**3,
                percent=58.0,
            ),
        ),
    )
    assert summary_line(snapshot) == (
        "cpu 34% of 8 cores; load 1.50; memory 12.0 GiB used, 50.0 GiB available; "
        "210.0 GiB free on /var/lib/twinlab/lab-files"
    )
