"""TerminalSession against a local websockets server speaking the frame protocol."""

import asyncio
import base64
import json
from typing import cast

import pytest
from websockets.asyncio.server import ServerConnection, serve

from twinlab_client import TerminalClosed, TerminalSession


async def test_terminal_session_flow() -> None:
    received: list[dict[str, object]] = []
    closed = asyncio.Event()

    async def handler(connection: ServerConnection) -> None:
        await connection.send(json.dumps({"type": "ready"}))
        await connection.send(
            json.dumps({"type": "output", "data": base64.b64encode(b"hello$ ").decode()})
        )
        raw = await connection.recv()
        received.append(cast("dict[str, object]", json.loads(raw)))
        await connection.send(json.dumps({"type": "exit"}))
        # Wait for the client's close so the server doesn't tear down early.
        try:
            async for _ in connection:
                pass
        finally:
            closed.set()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with TerminalSession(f"ws://127.0.0.1:{port}/", {}) as term:
            # "ready" is consumed; the first recv is the decoded output.
            assert await term.recv(timeout=5) == b"hello$ "
            await term.send(b"ls\n")
            with pytest.raises(TerminalClosed):
                _ = await term.recv(timeout=5)
        await asyncio.wait_for(closed.wait(), timeout=5)

    assert received == [{"type": "input", "data": "ls\n"}]
