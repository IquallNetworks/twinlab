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
