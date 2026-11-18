"""Live streams (deltas 36, 37): the route's own decisions, driven directly.

Authorization and the upstream relay are exercised live by the blackbox suite;
these pin the target grammar, the refusal mapping and the SSE framing."""

from collections.abc import AsyncIterator
from typing import cast

import anyio
import httpx2
import pytest
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope

from twinlab_backend.api import lab_streams
from twinlab_backend.api.labs import node_logs
from twinlab_backend.api_errors import ApiError
from twinlab_backend.app import create_app
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.clab_api import (
    ClabApiClient,
    ClabApiError,
    NodeInfo,
    NodeLogs,
    UpstreamStream,
)


def test_routes_are_mounted_under_the_api_prefix() -> None:
    app = create_app()
    assert app.url_path_for("capture", lab_name="lab1") == "/api/v1/labs/lab1/capture"
    assert (
        app.url_path_for("follow_node_logs", lab_name="lab1", node_name="r1")
        == "/api/v1/labs/lab1/nodes/r1/logs/stream"
    )


def test_targets_split_at_the_first_colon_and_keep_aliases() -> None:
    targets = ["r1:eth1", "r2:Ethernet0/1", "srl:ethernet-1/1", "n_1:e1:2"]
    assert lab_streams.parse_targets(targets) == targets


@pytest.mark.parametrize(
    "targets",
    [
        [],
        ["r1"],
        ["r1:"],
        [":eth1"],
        ["r1:eth 1"],
        ["-r1:eth1"],
        [f"r{i}:eth1" for i in range(17)],
    ],
)
def test_malformed_targets_are_refused_before_clab_api(targets: list[str]) -> None:
    with pytest.raises(ApiError) as raised:
        _ = lab_streams.parse_targets(targets)
    assert raised.value.status_code == 422
    assert raised.value.code == "invalid_capture_target"


@pytest.mark.parametrize(
    ("upstream", "status", "code"),
    [
        (400, 422, "invalid_capture_target"),
        (409, 409, "node_not_running"),
        (404, 404, "clab_not_found"),
        (500, 502, "upstream_error"),
        (None, 502, "upstream_error"),
    ],
)
def test_capture_refusals_map_to_the_envelope(upstream: int | None, status: int, code: str) -> None:
    error = lab_streams.capture_refused(ClabApiError("no", upstream))
    assert (error.status_code, error.code) == (status, code)


def test_only_a_deployed_lab_streams() -> None:
    lab_streams.require_deployed("lab1", "deployed")
    for status in ("created", "deploying", "destroyed"):
        with pytest.raises(ApiError) as raised:
            lab_streams.require_deployed("lab1", status)
        assert raised.value.code == "lab_not_running"


class _Closing(httpx2.AsyncByteStream):
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.body

    async def aclose(self) -> None:
        self.closed = True


async def test_log_events_frame_lines_keepalives_and_the_end() -> None:
    body = (
        b'{"containerName":"c","line":"boot \\"ok\\"","stream":"stdout"}\n'
        b"\n"
        b'{"containerName":"c","line":"bad","stream":"stderr"}\n'
    )
    raw = _Closing(body)
    upstream = UpstreamStream(httpx2.Response(200, stream=raw))
    frames = [frame async for frame in lab_streams.log_events(upstream)]
    assert frames == [
        ": connected\n\n",
        'event: log\ndata: {"stream":"stdout","line":"boot \\"ok\\""}\n\n',
        ": keepalive\n\n",
        'event: log\ndata: {"stream":"stderr","line":"bad"}\n\n',
        "event: end\ndata: {}\n\n",
    ]
    assert raw.closed


async def test_an_abandoned_capture_closes_upstream() -> None:
    raw = _Closing(b"pcapng")
    upstream = UpstreamStream(httpx2.Response(200, stream=raw))
    relay = lab_streams.relay_bytes(upstream)
    assert await anext(relay) == b"pcapng"
    await relay.aclose()  # the browser went away mid-capture
    assert raw.closed


async def test_a_client_gone_before_the_first_byte_still_closes_upstream() -> None:
    raw = _Closing(b"pcapng")
    upstream = UpstreamStream(httpx2.Response(200, stream=raw))
    response = lab_streams.UpstreamResponse(
        upstream,
        lab_streams.relay_bytes(upstream),
        media_type="application/x-pcapng",
        headers={},
    )

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        raise OSError("client went away")  # the response start itself fails

    scope: Scope = {"type": "http", "asgi": {"spec_version": "2.4"}}
    with pytest.raises(ClientDisconnect):
        await response(scope, receive, send)
    assert raw.closed


async def test_a_disconnect_before_the_first_byte_closes_upstream_under_asgi_2_3() -> None:
    # uvicorn reports spec 2.3, where Starlette cancels the body on the
    # disconnect message instead of failing a send.
    raw = _Closing(b"pcapng")
    upstream = UpstreamStream(httpx2.Response(200, stream=raw))
    response = lab_streams.UpstreamResponse(
        upstream,
        lab_streams.relay_bytes(upstream),
        media_type="application/x-pcapng",
        headers={},
    )

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        await anyio.sleep_forever()  # the response start never completes

    scope: Scope = {"type": "http", "asgi": {"spec_version": "2.3"}}
    await response(scope, receive, send)
    assert raw.closed


def test_targets_and_nodes_must_belong_to_the_lab() -> None:
    nodes = {"r1", "r2"}
    lab_streams.require_targets_in_lab("lab1", ["r1:eth1", "r2:Ethernet0/1"], nodes)
    lab_streams.require_node_in_lab("lab1", "r1", nodes)
    # A full container name, even one of this lab, is not a node name.
    for foreign in (["clab-lab2-r1:eth1"], ["r1:eth1", "zz:eth1"], ["clab-lab1-r1:eth1"]):
        with pytest.raises(ApiError) as raised:
            lab_streams.require_targets_in_lab("lab1", foreign, nodes)
        assert (raised.value.status_code, raised.value.code) == (422, "invalid_capture_target")
    with pytest.raises(ApiError) as raised:
        lab_streams.require_node_in_lab("lab1", "clab-lab2-r1", nodes)
    assert (raised.value.status_code, raised.value.code) == (404, "node_not_found")


class _FakeClab:
    def __init__(self, result: Result[tuple[NodeInfo, ...], ClabApiError]) -> None:
        self.result = result

    async def inspect(self, lab_name: str) -> Result[tuple[NodeInfo, ...], ClabApiError]:
        return self.result


async def test_lab_nodes_are_the_short_names_and_failures_map() -> None:
    node = NodeInfo(
        node_name="r1", container_name="clab-lab1-r1", image="i", state="running", ipv4_address=""
    )
    fake = _FakeClab(Ok((node,)))
    assert await lab_streams.lab_nodes(cast("ClabApiClient", fake), "lab1") == {"r1"}
    for status, code in ((404, "clab_not_found"), (500, "upstream_error")):
        failing = _FakeClab(Err(ClabApiError("no", status)))
        with pytest.raises(ApiError) as raised:
            _ = await lab_streams.lab_nodes(cast("ClabApiClient", failing), "lab1")
        assert raised.value.code == code


class _LogsClab(_FakeClab):
    def __init__(self, result: Result[tuple[NodeInfo, ...], ClabApiError]) -> None:
        super().__init__(result)
        self.asked: list[str] = []

    async def node_logs(
        self, lab_name: str, container_name: str, tail: str = "all"
    ) -> Result[NodeLogs, ClabApiError]:
        self.asked.append(container_name)
        # clab-api echoes the name it was sent as containerName.
        return Ok(NodeLogs(container_name=container_name, logs="boot ok\n"))


async def test_snapshot_logs_ask_for_the_exact_container_of_the_lab() -> None:
    node = NodeInfo(
        node_name="core-r1",
        container_name="clab-lab1-core-r1",
        image="i",
        state="running",
        ipv4_address="",
    )
    fake = _LogsClab(Ok((node,)))
    clab = cast("ClabApiClient", fake)
    logs = await node_logs("lab1", "core-r1", clab, tail=50)
    assert (logs.node, logs.container) == ("core-r1", "clab-lab1-core-r1")
    # clab-api answers all of these with 200 (measured): "r1" by its fuzzy
    # suffix match, serving core-r1's log under the name "r1".
    for name in ("r1", "clab-lab1-core-r1", "clab-lab2-r1"):
        with pytest.raises(ApiError) as raised:
            _ = await node_logs("lab1", name, clab, tail=50)
        assert (raised.value.status_code, raised.value.code) == (404, "node_not_found")
    assert fake.asked == ["clab-lab1-core-r1"]
