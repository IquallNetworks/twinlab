"""Long-lived lab streams: packet capture (delta 36) and log following (delta 37).

Both pass a clab-api stream through (design record docs/live-streams.md). The
caller is authorized BEFORE the response starts, in a session closed before the
stream does (`authorize_lab_stream`), and every refusal is the usual envelope,
because clab-api refuses before its first byte too. After that, a failure can
only end the stream. Closing the upstream response is what stops the work
upstream, so it is closed whichever side ends first.
"""

import re
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Annotated

import anyio
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import authorize_lab_stream
from twinlab_backend.deps import ClabClientDep, SettingsDep
from twinlab_backend.models import NodeLogLine
from twinlab_backend.result import Err
from twinlab_backend.services.clab_api import (
    ClabApiClient,
    ClabApiError,
    UpstreamStream,
    follow_log_lines,
)

router = APIRouter(prefix="/labs", tags=["labs"])

_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
LabName = Annotated[str, Path(pattern=_NAME_PATTERN)]
NodeName = Annotated[str, Path(pattern=_NAME_PATTERN)]

# `<node>:<interface>`, split at the first colon. The node follows the node-name
# charset; the interface is anything clab-api might name one (an alias such as
# `Ethernet0/1` or `ethernet-1/1` included) short of whitespace.
_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(\S{1,64})$")

# Bounds, each with its reason (docs/live-streams.md):
# - 1800s: the proxy in front cuts a response that sends nothing for an hour,
#   and a quiet link sends nothing; half that leaves a wide margin.
_MAX_CAPTURE_SECONDS = 1800
# - 16 interfaces covers every endpoint of any link a lab realistically has.
_MAX_TARGETS = 16
# - clab-api's own snap-length floor; its default (262144) is the ceiling here.
_SNAP_MIN, _SNAP_MAX = 64, 262144
# - the snapshot route's default and a ceiling that keeps the replay bounded.
_DEFAULT_TAIL, _MAX_TAIL = 200, 10000

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Disable proxy buffering (nginx) so lines flush immediately.
    "X-Accel-Buffering": "no",
}


def require_deployed(lab_name: str, status: str) -> None:
    if status != "deployed":
        raise ApiError(409, "lab_not_running", f"lab '{lab_name}' is not deployed")


def parse_targets(targets: list[str]) -> list[str]:
    if not 1 <= len(targets) <= _MAX_TARGETS:
        raise ApiError(
            422,
            "invalid_capture_target",
            f"name 1 to {_MAX_TARGETS} targets, each <node>:<interface>",
        )
    bad = [target for target in targets if _TARGET.match(target) is None]
    if bad:
        raise ApiError(
            422,
            "invalid_capture_target",
            f"not <node>:<interface>: {', '.join(bad)}",
            {"targets": bad},
        )
    return targets


async def lab_nodes(clab: ClabApiClient, lab_name: str) -> set[str]:
    """The short names of the lab's deployed nodes, which every node-named
    read checks a name against before it goes upstream. clab-api refuses a
    container of another lab (even for Twinlab's superuser account, checked),
    but for a name it does not know it falls back to a fuzzy match within the
    lab (by suffix, so "r1" finds "core-r1"), so only this check is exact."""
    inspected = await clab.inspect(lab_name)
    if isinstance(inspected, Err):
        if inspected.error.status_code == HTTPStatus.NOT_FOUND:
            raise ApiError(404, "clab_not_found", inspected.error.message)
        raise ApiError(502, "upstream_error", inspected.error.message)
    return {node.node_name for node in inspected.value}


def require_targets_in_lab(lab_name: str, targets: list[str], nodes: set[str]) -> None:
    foreign = [target for target in targets if target.partition(":")[0] not in nodes]
    if foreign:
        raise ApiError(
            422,
            "invalid_capture_target",
            f"not a node of lab '{lab_name}': {', '.join(foreign)}",
            {"targets": foreign},
        )


def require_node_in_lab(lab_name: str, node_name: str, nodes: set[str]) -> None:
    if node_name not in nodes:
        raise ApiError(404, "node_not_found", f"node '{node_name}' not found in lab '{lab_name}'")


def capture_refused(error: ClabApiError) -> ApiError:
    match error.status_code:
        case HTTPStatus.BAD_REQUEST:
            # The shape was checked here, so clab-api refused the node or the
            # interface itself (unknown, or the management interface).
            return ApiError(422, "invalid_capture_target", error.message)
        case HTTPStatus.CONFLICT:
            return ApiError(409, "node_not_running", error.message)
        case HTTPStatus.NOT_FOUND:
            return ApiError(404, "clab_not_found", error.message)
        case _:
            return ApiError(502, "upstream_error", error.message)


class UpstreamResponse(StreamingResponse):
    """A streaming response that closes its upstream however it ends.

    The body generators close it in their own `finally`, but a client gone
    before the first byte fails the response start, so the body never starts
    and that `finally` never runs; Starlette runs no background task on that
    path either. Left open, a log follow would run upstream for 12 hours.
    Closing twice is harmless."""

    def __init__(
        self,
        upstream: UpstreamStream,
        content: AsyncGenerator[bytes] | AsyncGenerator[str],
        *,
        media_type: str,
        headers: dict[str, str],
    ) -> None:
        super().__init__(content, media_type=media_type, headers=headers)
        self.upstream = upstream

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self.upstream.aclose()


async def relay_bytes(upstream: UpstreamStream) -> AsyncGenerator[bytes]:
    try:
        async for chunk in upstream.chunks():
            yield chunk
    finally:
        await upstream.aclose()


@router.get("/{lab_name}/capture")
async def capture(
    request: Request,
    lab_name: LabName,
    settings: SettingsDep,
    clab: ClabClientDep,
    target: Annotated[list[str], Query()],
    duration_seconds: Annotated[int, Query(ge=1, le=_MAX_CAPTURE_SECONDS)],
    packet_limit: Annotated[int | None, Query(ge=1)] = None,
    snap_length: Annotated[int | None, Query(ge=_SNAP_MIN, le=_SNAP_MAX)] = None,
) -> StreamingResponse:
    """Capture lab link interfaces as one pcapng stream (delta 36), lab:read."""
    status = await authorize_lab_stream(request, settings, lab_name, perms.LAB_READ)
    targets = parse_targets(target)
    require_deployed(lab_name, status)
    require_targets_in_lab(lab_name, targets, await lab_nodes(clab, lab_name))
    opened = await clab.open_capture(
        lab_name,
        targets,
        duration_seconds=duration_seconds,
        packet_limit=packet_limit,
        snap_length=snap_length,
    )
    if isinstance(opened, Err):
        raise capture_refused(opened.error)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return UpstreamResponse(
        opened.value,
        relay_bytes(opened.value),
        media_type="application/x-pcapng",
        headers={
            "Content-Disposition": f'attachment; filename="{lab_name}-{stamp}.pcapng"',
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def log_events(upstream: UpstreamStream) -> AsyncGenerator[str]:
    try:
        yield ": connected\n\n"  # flush headers so EventSource fires `open`
        async for line in follow_log_lines(upstream):
            if line is None:
                yield ": keepalive\n\n"
                continue
            payload = NodeLogLine(stream=line.stream, line=line.line)
            yield f"event: log\ndata: {payload.model_dump_json()}\n\n"
        # Upstream ended (container removed, or clab-api's 12h limit): say so,
        # or EventSource reconnects forever and replays the tail each time.
        yield "event: end\ndata: {}\n\n"
    finally:
        await upstream.aclose()


@router.get("/{lab_name}/nodes/{node_name}/logs/stream")
async def follow_node_logs(
    request: Request,
    lab_name: LabName,
    node_name: NodeName,
    settings: SettingsDep,
    clab: ClabClientDep,
    tail: Annotated[int, Query(ge=0, le=_MAX_TAIL)] = _DEFAULT_TAIL,
) -> StreamingResponse:
    """Follow a node's container log as Server-Sent Events (delta 37), lab:read."""
    status = await authorize_lab_stream(request, settings, lab_name, perms.LAB_READ)
    require_deployed(lab_name, status)
    require_node_in_lab(lab_name, node_name, await lab_nodes(clab, lab_name))
    opened = await clab.follow_logs(lab_name, node_name, tail=tail)
    if isinstance(opened, Err):
        # 404 unknown node, 400 a container of another lab: both are "no such
        # node here" to the caller (the check above makes either a race).
        if opened.error.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.BAD_REQUEST):
            raise ApiError(
                404, "node_not_found", f"node '{node_name}' not found in lab '{lab_name}'"
            )
        raise ApiError(502, "upstream_error", opened.error.message)
    return UpstreamResponse(
        opened.value, log_events(opened.value), media_type="text/event-stream", headers=_SSE_HEADERS
    )
