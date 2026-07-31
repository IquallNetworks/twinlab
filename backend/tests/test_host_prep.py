"""HostPrepClient: request shape (token header, method, body) and the
translation of transport/HTTP/shape failures into typed results."""

import json
from collections.abc import Callable

import httpx

from twinlab_backend.result import Err, Ok
from twinlab_backend.services.host_prep import HostPrepClient


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> HostPrepClient:
    return HostPrepClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="http://hostprep:8091",
        token="secret",
    )


async def test_ensure_bridges_sends_token_and_parses_outcomes() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["token"] = request.headers.get("X-Hostprep-Token")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "bridges": [
                    {"name": "lab_1", "status": "created", "detail": ""},
                    {"name": "lab_2", "status": "existed", "detail": ""},
                ]
            },
        )

    result = await _client(handler).ensure_bridges(["lab_1", "lab_2"])
    assert isinstance(result, Ok), result
    assert seen["method"] == "PUT"
    assert seen["token"] == "secret"
    assert seen["body"] == {"names": ["lab_1", "lab_2"]}
    assert [(o.name, o.status) for o in result.value] == [
        ("lab_1", "created"),
        ("lab_2", "existed"),
    ]


async def test_delete_bridges_uses_delete_method() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return httpx.Response(
            200, json={"bridges": [{"name": "lab_1", "status": "in_use", "detail": "ports"}]}
        )

    result = await _client(handler).delete_bridges(["lab_1"])
    assert isinstance(result, Ok), result
    (outcome,) = result.value
    assert outcome.status == "in_use"
    assert outcome.detail == "ports"


async def test_load_modules_parses_per_item() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/modules"
        return httpx.Response(
            200,
            json={
                "modules": [
                    {"name": "vrf", "ok": True, "detail": ""},
                    {"name": "mpls-router", "ok": False, "detail": "not found"},
                ]
            },
        )

    result = await _client(handler).load_modules(["vrf", "mpls-router"])
    assert isinstance(result, Ok), result
    assert [(o.name, o.ok) for o in result.value] == [("vrf", True), ("mpls-router", False)]


async def test_http_error_is_a_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid token"})

    result = await _client(handler).ensure_bridges(["lab_1"])
    assert isinstance(result, Err)
    assert "invalid token" in result.error.message


async def test_transport_error_is_a_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    result = await _client(handler).load_modules(["vrf"])
    assert isinstance(result, Err)
    assert "connection refused" in result.error.message


async def test_unexpected_shape_is_a_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"bridges": [{"name": "lab_1", "status": "sideways"}]})

    result = await _client(handler).ensure_bridges(["lab_1"])
    assert isinstance(result, Err)
    assert "unexpected hostprep response" in result.error.message
