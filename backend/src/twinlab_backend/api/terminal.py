"""WebSocket proxy for a node's interactive terminal.

clab-api exposes a node terminal as a WebSocket: create a session (HTTP), then
open its stream (WS) and exchange JSON frames — client `{type: input|resize|
close}`, server `{type: ready|output|exit}` (output base64-encoded). We proxy
that stream through FastAPI so the browser reaches it via the same origin and
auth as the rest of the API.

The proxy is deliberately transparent: it relays JSON text frames verbatim in
both directions (the browser speaks clab-api's terminal protocol directly and
does its own base64 decode), and owns only auth, session lifecycle, and
teardown. Auth is resolved from the handshake cookie before the socket is
accepted and its DB session released before the relay, so a long-lived terminal
doesn't pin a DB connection — the same discipline the events stream follows.

Node identity: terminal-sessions accepts the short node name (verified against
clab-api v0.5.0), like the node lifecycle actions — so no container resolution
is needed here, unlike logs/netem.
"""

import asyncio
import contextlib
from typing import Annotated, Literal

from fastapi import APIRouter, Query, WebSocket
from starlette.websockets import WebSocketDisconnect
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.service import effective_permissions_for
from twinlab_backend.auth.sessions import resolve_session
from twinlab_backend.config import Settings
from twinlab_backend.result import Err
from twinlab_backend.services import lab_store
from twinlab_backend.services.clab_api import ClabApiClient

router = APIRouter(tags=["terminal"])

# WebSocket close codes: 1008 policy violation (auth/permission), 1011 internal
# error (upstream session/stream failure).
_WS_POLICY_VIOLATION = 1008
_WS_INTERNAL_ERROR = 1011

# The WS close reason is capped at 123 UTF-8 bytes by RFC 6455; stay under it.
_MAX_REASON_LEN = 120


async def _fail(websocket: WebSocket, message: str) -> None:
    """Close an accepted socket with an internal-error code, surfacing the reason
    (truncated to the protocol's limit) so the browser can show it."""
    await websocket.close(code=_WS_INTERNAL_ERROR, reason=message[:_MAX_REASON_LEN])


async def _authorize(websocket: WebSocket, settings: Settings, lab_name: str) -> bool:
    """Resolve the session cookie in a short-lived DB session and check the caller
    holds `lab:terminal` on *this* lab. The session is closed before the relay so a
    long-lived terminal doesn't hold a DB connection."""
    token = websocket.cookies.get(settings.session_cookie_name)
    if not token:
        return False
    async with websocket.app.state.session_factory() as session:
        resolved = await resolve_session(session, token)
        if isinstance(resolved, Err):
            return False
        lab = await lab_store.get_lab(session, lab_name)
        if lab is None:
            return False
        granted = await effective_permissions_for(session, resolved.value, lab)
        return perms.LAB_TERMINAL in granted


async def _relay(browser: WebSocket, upstream: ClientConnection) -> None:
    """Pump JSON text frames both directions until either side closes. The first
    task to finish cancels the other; frames are forwarded verbatim."""

    async def browser_to_upstream() -> None:
        try:
            while True:
                await upstream.send(await browser.receive_text())
        except (WebSocketDisconnect, ConnectionClosed):
            return

    async def upstream_to_browser() -> None:
        try:
            async for frame in upstream:
                text = frame.decode() if isinstance(frame, bytes) else frame
                await browser.send_text(text)
        except (WebSocketDisconnect, ConnectionClosed):
            return

    tasks = {asyncio.create_task(browser_to_upstream()), asyncio.create_task(upstream_to_browser())}
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        _ = task.cancel()
    for task in pending:
        with contextlib.suppress(asyncio.CancelledError):
            await task


@router.websocket("/labs/{name}/nodes/{node}/terminal")
async def node_terminal(
    websocket: WebSocket,
    name: str,
    node: str,
    protocol: Literal["ssh", "shell"] = "ssh",
    cols: Annotated[int, Query(ge=1, le=1000)] = 80,
    rows: Annotated[int, Query(ge=1, le=1000)] = 24,
    # Optional ssh login user; clab-api defaults to `admin` (wrong for e.g. vyos).
    # Empty/absent leaves that default in place; ignored for protocol=shell.
    ssh_username: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> None:
    settings: Settings = websocket.app.state.settings
    clab: ClabApiClient = websocket.app.state.clab_client

    # Auth before accept — a rejected handshake closes with 1008, no socket opened.
    if not await _authorize(websocket, settings, name):
        await websocket.close(code=_WS_POLICY_VIOLATION)
        return

    await websocket.accept()

    created = await clab.create_terminal_session(
        name, node, protocol=protocol, cols=cols, rows=rows, ssh_username=ssh_username
    )
    if isinstance(created, Err):
        await _fail(websocket, created.error.message)
        return
    session_id = created.value

    opened = await clab.open_terminal_stream(session_id)
    if isinstance(opened, Err):
        _ = await clab.delete_terminal_session(session_id)
        await _fail(websocket, opened.error.message)
        return
    upstream = opened.value

    try:
        await _relay(websocket, upstream)
    finally:
        await upstream.close()
        # Best-effort teardown; the session also expires server-side on its own.
        _ = await clab.delete_terminal_session(session_id)
