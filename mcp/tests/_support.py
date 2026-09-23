"""Test plumbing: a fake backend at the HTTP boundary, and an MCP client
driving the real ASGI app in-process.

The backend is faked with httpx2.MockTransport under the real `twinlab-client`,
so every test also exercises the client's request building and response
parsing: the fake is the wire, not the client.
"""

import json
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import anyio
import httpx2
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.types import ASGIApp, Message
from twinlab_client import TwinlabClient

from twinlab_mcp.app import build_app
from twinlab_mcp.guide import GuideError

GOOD_KEY = "tl_good"
REPO_GUIDE = Path(__file__).resolve().parents[2] / "docs" / "guide"

type Route = Callable[[httpx2.Request], httpx2.Response]

OWNER_ID = "0198c0de-0000-7000-8000-000000000001"
JOB_ID = "0198c0de-0000-7000-8000-00000000000a"


def info_wire(username: str = "ada") -> dict[str, object]:
    return {
        "username": username,
        "email": f"{username}@example.test",
        "display_name": username.title(),
        "roles": ["global_viewer"],
        "permissions": [],
    }


def lab_wire(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "lab1",
        "status": "deployed",
        "definition": "provider: clab\n",
        "deployed_definition": "provider: clab\n",
        "definition_drifted": False,
        "owner": {"id": OWNER_ID, "name": "ada"},
        "created_at": "2026-09-23T10:00:00+00:00",
        "updated_at": "2026-09-23T11:00:00+00:00",
        "nodes": [],
        "config_time_status": "not_run",
        "permissions": ["lab:read"],
        "template_published": False,
        "message": None,
    }
    return base | overrides


def job_wire(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": JOB_ID,
        "lab_name": "lab1",
        "kind": "deploy",
        "status": "running",
        "request": {"configure": True, "skip_config_time_checks": False},
        "result": None,
        "error": None,
        "created_at": "2026-09-23T10:00:00+00:00",
        "finished_at": None,
        "steps": [],
    }
    return base | overrides


def action_wire() -> dict[str, object]:
    return {"message": "ok"}


@dataclass
class FakeBackend:
    """Routes keyed by (method, path under /api/v1). `/auth/me` accepts
    GOOD_KEY and 401s anything else, as the backend does."""

    routes: dict[tuple[str, str], Route] = field(default_factory=dict[tuple[str, str], Route])
    requests: list[httpx2.Request] = field(default_factory=list[httpx2.Request])

    def json(self, method: str, path: str, body: object, status: int = 200) -> None:
        self.routes[method, path] = lambda _: httpx2.Response(status, json=body)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/api/v1")
        if path == "/auth/me":
            if request.headers.get("authorization") != f"Bearer {GOOD_KEY}":
                return httpx2.Response(
                    401, json={"code": "not_authenticated", "message": "no", "extras": {}}
                )
            return httpx2.Response(200, json=info_wire())
        route = self.routes.get((request.method, path))
        if route is None:
            return httpx2.Response(
                404, json={"code": "not_found", "message": f"no fake for {path}", "extras": {}}
            )
        return route(request)

    def client_for(self, key: str) -> TwinlabClient:
        return TwinlabClient(
            "http://backend.test", api_key=key, transport=httpx2.MockTransport(self.handle)
        )

    def sent(self, method: str, path: str) -> httpx2.Request:
        for request in self.requests:
            if request.method == method and request.url.path == "/api/v1" + path:
                return request
        raise AssertionError(f"no {method} {path} was sent")

    def sent_json(self, method: str, path: str) -> dict[str, object]:
        return cast("dict[str, object]", json.loads(self.sent(method, path).content))


def app_for(backend: FakeBackend, guide_dir: Path = REPO_GUIDE) -> ASGIApp:
    app = build_app(backend.client_for, guide_dir)
    assert not isinstance(app, GuideError), app
    return app


@asynccontextmanager
async def lifespan(app: ASGIApp) -> AsyncGenerator[None]:
    """Run the ASGI lifespan, which starts the SDK's session manager.
    httpx2's ASGITransport sends only HTTP scopes."""
    to_app, app_inbox = anyio.create_memory_object_stream[Message](4)
    app_outbox, from_app = anyio.create_memory_object_stream[Message](4)

    async def receive() -> Message:
        return await app_inbox.receive()

    async def send(message: Message) -> None:
        await app_outbox.send(message)

    async def run() -> None:
        await app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send)

    async with anyio.create_task_group() as tg:
        tg.start_soon(run)
        await to_app.send({"type": "lifespan.startup"})
        started = await from_app.receive()
        assert started["type"] == "lifespan.startup.complete", started
        try:
            yield
        finally:
            await to_app.send({"type": "lifespan.shutdown"})
            _ = await from_app.receive()


def http_client(app: ASGIApp, key: str | None) -> httpx2.AsyncClient:
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://mcp.test", headers=headers
    )


@asynccontextmanager
async def connect(app: ASGIApp, key: str = GOOD_KEY) -> AsyncGenerator[Client]:
    async with (
        lifespan(app),
        http_client(app, key) as http,
        Client(streamable_http_client("http://mcp.test/mcp", http_client=http)) as client,
    ):
        yield client
