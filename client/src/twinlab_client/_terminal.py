"""Interactive node terminal over the Twinlab WebSocket proxy.

The server relays clab-api's terminal protocol verbatim as JSON text frames:

    client -> {"type": "input", "data": "<text>"}
            | {"type": "resize", "cols": <int>, "rows": <int>}
            | {"type": "close"}
    server -> {"type": "ready"} | {"type": "output", "data": "<base64>"}
            | {"type": "exit", ...}

This session owns the framing and the base64 decode, exposing bytes.
"""

import asyncio
import base64
import contextlib
import json
from contextlib import AbstractAsyncContextManager
from typing import cast

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from twinlab_client.errors import TwinlabApiError, TwinlabProtocolError


class TerminalClosed(Exception):
    """The terminal ended: the server sent an "exit" frame or closed the
    socket (close code 1011 carries the upstream failure as its reason)."""


class TerminalSession(AbstractAsyncContextManager["TerminalSession"]):
    """One node terminal. Constructed by `TwinlabClient.terminal(...)`; the
    connection opens on `async with` entry. A rejected handshake (no session /
    no lab:terminal — the server hides both behind one refusal) raises
    `TwinlabApiError` on entry."""

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self._url = url
        self._headers = headers
        self._ws: ClientConnection | None = None

    async def __aenter__(self) -> "TerminalSession":
        try:
            self._ws = await connect(self._url, additional_headers=self._headers)
        except InvalidStatus as exc:
            status = exc.response.status_code
            raise TwinlabApiError(
                status,
                "permission_denied" if status == 403 else "unknown",
                "terminal handshake rejected",
                {},
            ) from exc
        return self

    def _connection(self) -> ClientConnection:
        if self._ws is None:
            raise RuntimeError("terminal not connected — enter the session with 'async with'")
        return self._ws

    async def send(self, data: bytes) -> None:
        """Send terminal input (UTF-8 text bytes, e.g. keystrokes)."""
        frame = json.dumps({"type": "input", "data": data.decode()})
        await self._connection().send(frame)

    async def recv(self, timeout: float | None = None) -> bytes:
        """Next chunk of decoded terminal output ("ready" frames are consumed).

        Raises `TerminalClosed` on the "exit" frame or socket close, and
        `TimeoutError` if `timeout` elapses first.
        """
        ws = self._connection()
        while True:
            try:
                raw = await (
                    asyncio.wait_for(ws.recv(), timeout) if timeout is not None else ws.recv()
                )
            except ConnectionClosed as exc:
                raise TerminalClosed(exc.reason or "connection closed") from exc
            frame = _parse_frame(raw if isinstance(raw, str) else raw.decode())
            kind = frame.get("type")
            if kind == "output":
                data = frame.get("data")
                if not isinstance(data, str):
                    raise TwinlabProtocolError("terminal", "output frame without string data")
                return base64.b64decode(data)
            if kind == "ready":
                continue
            if kind == "exit":
                raise TerminalClosed("terminal exited")
            raise TwinlabProtocolError("terminal", f"unexpected frame type {kind!r}")

    async def resize(self, cols: int, rows: int) -> None:
        await self._connection().send(json.dumps({"type": "resize", "cols": cols, "rows": rows}))

    async def close(self) -> None:
        """Close the terminal (idempotent): best-effort "close" frame, then
        the socket."""
        if self._ws is None:
            return
        ws = self._ws
        self._ws = None
        with contextlib.suppress(ConnectionClosed):
            await ws.send(json.dumps({"type": "close"}))
        await ws.close()

    async def __aexit__(self, *exc: object) -> None:
        await self.close()


def _parse_frame(text: str) -> dict[str, object]:
    try:
        decoded: object = json.loads(text)
    except ValueError as exc:
        raise TwinlabProtocolError("terminal", f"non-JSON frame: {text[:80]!r}") from exc
    if not isinstance(decoded, dict):
        raise TwinlabProtocolError("terminal", "frame is not a JSON object")
    return cast("dict[str, object]", decoded)
