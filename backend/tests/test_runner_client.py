import json
from collections.abc import Callable

import httpx2

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.runner_client import RunnerClient


def _client(handler: Callable[[httpx2.Request], httpx2.Response]) -> RunnerClient:
    return RunnerClient(
        client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
        base_url="http://runner.test",
    )


async def test_configure_parses_per_node_results() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/configure"
        return httpx2.Response(
            200,
            json={
                "lab_name": "tl-1",
                "succeeded": True,
                "nodes": [
                    {"node": "r1", "changed": 4, "failed": 0},
                    {"node": "r2", "changed": 4, "failed": 0},
                ],
            },
        )

    result = await _client(handler).configure("name: tl-1\nnodes: [r1, r2]\n", {})
    assert isinstance(result, Ok), result
    assert result.value.succeeded
    assert result.value.nodes[0].status == "configured"


async def test_configure_sends_template_fileset() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return httpx2.Response(200, json={"lab_name": "tl-1", "succeeded": True, "nodes": []})

    templates = {"mpls_te/ios.j2": "conf", "nat.j2": "user"}
    _ = await _client(handler).configure("name: tl-1\n", templates)
    assert seen["templates"] == templates


async def test_configure_marks_failed_node() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "lab_name": "tl-1",
                "succeeded": False,
                "nodes": [{"node": "r1", "changed": 0, "failed": 2}],
            },
        )

    result = await _client(handler).configure("name: tl-1\n", {})
    assert isinstance(result, Ok), result
    assert not result.value.succeeded
    assert result.value.nodes[0].status == "failed"


async def test_configure_maps_bad_definition_to_typed_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(422, json={"detail": "netlab create failed"})

    result = await _client(handler).configure("nonsense", {})
    assert isinstance(result, Err)
    assert result.error.reason == "bad_definition"


async def test_ready_reports_ready_and_sends_templates() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/ready"
        seen.update(json.loads(request.content))
        return httpx2.Response(200, json={"ready": True})

    templates = {"mpls_te/ios.j2": "conf"}
    result = await _client(handler).ready("name: tl-1\n", templates)
    assert isinstance(result, Ok), result
    assert result.value.ready
    assert seen["templates"] == templates


async def test_ready_maps_not_ready_to_typed_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        # 504: netlab exhausted its retry budget (a node never came up).
        return httpx2.Response(504, json={"detail": "devices did not become ready"})

    result = await _client(handler).ready("name: tl-1\n", {})
    assert isinstance(result, Err)
    assert result.error.reason == "runner"


async def test_docker_usage_parses_the_daemon_footprint() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/docker/usage"
        return httpx2.Response(
            200,
            json={
                "root_dir": "/var/lib/docker",
                "containers_running": 3,
                "containers_paused": 0,
                "containers_stopped": 1,
                "containers_total": 4,
                "images_total": 45,
                "disk": [
                    {
                        "kind": "images",
                        "total": 45,
                        "active": 3,
                        "size_bytes": 24423156815,
                        "reclaimable_bytes": 22467784404,
                    }
                ],
            },
        )

    result = await _client(handler).docker_usage()
    assert isinstance(result, Ok), result
    assert result.value.root_dir == "/var/lib/docker"
    assert result.value.containers_running == 3
    assert result.value.disk[0].kind == "images"
    assert result.value.disk[0].reclaimable_bytes == 22467784404


async def test_container_stats_are_keyed_by_container_name() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/docker/stats"
        # One repeated query parameter per container, so the runner samples
        # them concurrently in a single round trip.
        assert request.url.params.get_list("container") == ["clab-l-r1", "clab-l-r2"]
        return httpx2.Response(
            200,
            json={
                "stats": [
                    {
                        "container": "clab-l-r1",
                        "cpu_percent": 10.5,
                        "memory_bytes": 4096,
                        "memory_limit_bytes": 8192,
                        "net_rx_bytes": 1,
                        "net_tx_bytes": 2,
                        "pids": 3,
                    }
                ]
            },
        )

    result = await _client(handler).container_stats(("clab-l-r1", "clab-l-r2"))
    assert isinstance(result, Ok), result
    # r2 is simply absent — a name the daemon does not know is not an error for
    # the whole request.
    assert sorted(result.value) == ["clab-l-r1"]
    assert result.value["clab-l-r1"].cpu_percent == 10.5


async def test_container_stats_with_no_containers_skips_the_round_trip() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("no containers means nothing to ask about")

    result = await _client(handler).container_stats(())
    assert isinstance(result, Ok), result
    assert result.value == {}
