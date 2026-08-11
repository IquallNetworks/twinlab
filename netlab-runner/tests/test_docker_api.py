"""Parser tests over payloads captured from a real daemon (Docker 29.7.1,
cgroup v2). The disk figures mirror what `docker system df` printed for the
same host, so a change that drifts from the operator's own view fails here."""

import json

from netlab_runner.docker_api import DiskEntry, parse_disk_entries, parse_stats
from netlab_runner.runner import RunnerError

# Trimmed to the fields the parser reads.
_DF = {
    "LayersSize": 24423156815,
    "Images": [
        {"Size": 95983819, "SharedSize": 92548197, "Containers": 0},
        {"Size": 500000000, "SharedSize": 100000000, "Containers": 2},
        {"Size": 300000000, "SharedSize": 0, "Containers": 0},
    ],
    "Containers": [
        {"SizeRw": 1024, "State": "running"},
        {"SizeRw": 2048, "State": "exited"},
        {"SizeRw": None, "State": "running"},
    ],
    "Volumes": [
        {"UsageData": {"Size": 3000, "RefCount": 1}},
        {"UsageData": {"Size": 500, "RefCount": 0}},
        {"UsageData": None},
    ],
    "BuildCache": [
        {"Size": 900, "Shared": False, "InUse": True},
        {"Size": 100, "Shared": True, "InUse": False},
    ],
}


def _entries(payload: object) -> dict[str, DiskEntry]:
    parsed = parse_disk_entries(json.dumps(payload).encode())
    assert not isinstance(parsed, RunnerError)
    return {entry.kind: entry for entry in parsed}


def test_images_size_is_the_deduplicated_layer_total() -> None:
    images = _entries(_DF)["images"]
    # NOT the sum of per-image Size, which double-counts shared layers.
    assert images.size_bytes == 24423156815
    assert images.total == 3
    assert images.active == 1


def test_unused_images_reclaim_only_their_unshared_bytes() -> None:
    images = _entries(_DF)["images"]
    # (95983819 - 92548197) + (300000000 - 0); the in-use image contributes none.
    assert images.reclaimable_bytes == 3435622 + 300000000


def test_stopped_containers_and_unreferenced_volumes_are_reclaimable() -> None:
    entries = _entries(_DF)
    containers = entries["containers"]
    assert containers.size_bytes == 3072
    assert containers.reclaimable_bytes == 2048
    assert containers.active == 2

    volumes = entries["volumes"]
    assert volumes.size_bytes == 3500
    assert volumes.reclaimable_bytes == 500
    assert volumes.active == 1


def test_shared_build_cache_counts_toward_size_but_not_reclaim() -> None:
    cache = _entries(_DF)["build_cache"]
    assert cache.size_bytes == 1000
    assert cache.reclaimable_bytes == 900


def test_null_collections_parse_as_empty() -> None:
    # A daemon with nothing to report marshals nil slices as JSON null.
    entries = _entries(
        {
            "LayersSize": 0,
            "Images": None,
            "Containers": None,
            "Volumes": None,
            "BuildCache": None,
        }
    )
    assert sorted(entries) == ["build_cache", "containers", "images", "volumes"]
    assert all(entry.total == 0 and entry.size_bytes == 0 for entry in entries.values())


def test_malformed_df_is_an_error_value() -> None:
    assert isinstance(parse_disk_entries(b"{not json"), RunnerError)


# --- stats ------------------------------------------------------------------

_RUNNING = {
    "cpu_stats": {
        "cpu_usage": {"total_usage": 126310000},
        "system_cpu_usage": 900568520000000,
        "online_cpus": 8,
    },
    "precpu_stats": {
        "cpu_usage": {"total_usage": 26310000},
        "system_cpu_usage": 900560590000000,
    },
    "memory_stats": {
        "usage": 368640,
        "limit": 33563410432,
        "stats": {"inactive_file": 65536, "anon": 49152},
    },
    "networks": {
        "eth0": {"rx_bytes": 2026, "tx_bytes": 126},
        "eth1": {"rx_bytes": 1000, "tx_bytes": 2000},
    },
    "pids_stats": {"current": 7},
}

# What a STOPPED container actually answers: HTTP 200 with an empty payload.
_STOPPED = {
    "cpu_stats": {"cpu_usage": {"total_usage": 0}},
    "precpu_stats": {"cpu_usage": {"total_usage": 0}},
    "memory_stats": {},
    "pids_stats": {},
}


def test_running_container_stats() -> None:
    stats = parse_stats("clab-lab-r1", json.dumps(_RUNNING).encode())
    assert not isinstance(stats, RunnerError)
    # (100000000 / 7930000000) * 8 * 100 — a share of the WHOLE host, so a
    # container pinning two cores reads 200%.
    assert stats.cpu_percent is not None
    assert round(stats.cpu_percent, 3) == 10.088
    # Page cache is subtracted, matching what `docker stats` reports.
    assert stats.memory_bytes == 368640 - 65536
    assert stats.memory_limit_bytes == 33563410432
    # Summed across interfaces.
    assert stats.net_rx_bytes == 3026
    assert stats.net_tx_bytes == 2126
    assert stats.pids == 7


def test_stopped_container_reports_unknown_not_zero() -> None:
    stats = parse_stats("clab-lab-r1", json.dumps(_STOPPED).encode())
    assert not isinstance(stats, RunnerError)
    # Every measure absent: a stopped container is not an idle one.
    assert stats.cpu_percent is None
    assert stats.memory_bytes is None
    assert stats.memory_limit_bytes is None
    assert stats.net_rx_bytes is None
    assert stats.net_tx_bytes is None


def test_malformed_stats_are_an_error_value() -> None:
    assert isinstance(parse_stats("x", b"{not json"), RunnerError)
