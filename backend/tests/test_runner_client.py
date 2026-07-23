import json
from collections.abc import Callable

import httpx

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.runner_client import RunnerClient


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> RunnerClient:
    return RunnerClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://runner.test",
    )


async def test_configure_parses_per_node_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/configure"
        return httpx.Response(
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

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"lab_name": "tl-1", "succeeded": True, "nodes": []})

    templates = {"mpls_te/ios.j2": "conf", "nat.j2": "user"}
    _ = await _client(handler).configure("name: tl-1\n", templates)
    assert seen["templates"] == templates


async def test_configure_marks_failed_node() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
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
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "netlab create failed"})

    result = await _client(handler).configure("nonsense", {})
    assert isinstance(result, Err)
    assert result.error.reason == "bad_definition"


async def test_ready_reports_ready_and_sends_templates() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ready"
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"ready": True})

    templates = {"mpls_te/ios.j2": "conf"}
    result = await _client(handler).ready("name: tl-1\n", templates)
    assert isinstance(result, Ok), result
    assert result.value.ready
    assert seen["templates"] == templates


async def test_ready_maps_not_ready_to_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 504: netlab exhausted its retry budget (a node never came up).
        return httpx.Response(504, json={"detail": "devices did not become ready"})

    result = await _client(handler).ready("name: tl-1\n", {})
    assert isinstance(result, Err)
    assert result.error.reason == "runner"
