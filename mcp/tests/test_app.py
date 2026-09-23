"""The HTTP boundary (the bearer guard, health) and the guide resources."""

from pathlib import Path

import httpx2
from _support import REPO_GUIDE, FakeBackend, app_for, connect, http_client, lifespan
from mcp_types import TextResourceContents

from twinlab_mcp.app import build_app
from twinlab_mcp.guard import bearer_token
from twinlab_mcp.guide import URI_PREFIX, GuideError, load_guide
from twinlab_mcp.settings import Settings, SettingsError, load_settings

_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
_MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


async def _post(app_key: str | None, backend: FakeBackend) -> httpx2.Response:
    app = app_for(backend)
    async with lifespan(app), http_client(app, app_key) as http:
        return await http.post("/mcp", json=_INITIALIZE, headers=_MCP_HEADERS)


async def test_no_key_is_401_before_the_backend_is_asked() -> None:
    backend = FakeBackend()
    response = await _post(None, backend)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["code"] == "missing_api_key"
    assert backend.requests == []


async def test_a_key_the_backend_refuses_is_401() -> None:
    response = await _post("tl_revoked", FakeBackend())
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_api_key"


async def test_an_unreachable_backend_is_502() -> None:
    backend = FakeBackend()

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    backend.handle = refuse
    response = await _post("tl_any", backend)
    assert response.status_code == 502
    assert response.json()["code"] == "backend_unreachable"


async def test_an_accepted_key_reaches_the_mcp_layer() -> None:
    response = await _post("tl_good", FakeBackend())
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "twinlab"


async def test_health_needs_no_key() -> None:
    app = app_for(FakeBackend())
    async with lifespan(app), http_client(app, None) as http:
        response = await http.get("/health")
    assert response.json() == {"status": "ok"}


def test_bearer_token_parsing() -> None:
    assert bearer_token("Bearer tl_x") == "tl_x"
    assert bearer_token("bearer  tl_x ") == "tl_x"
    assert bearer_token("Basic dXNlcg==") is None
    assert bearer_token("Bearer ") is None
    assert bearer_token(None) is None


async def test_every_guide_page_is_a_readable_resource() -> None:
    pages = sorted(path.name for path in REPO_GUIDE.glob("*.md"))
    async with connect(app_for(FakeBackend())) as client:
        listed = (await client.list_resources()).resources
        assert sorted(str(resource.uri) for resource in listed) == [
            URI_PREFIX + page for page in pages
        ]
        first = (await client.read_resource(URI_PREFIX + "02-first-lab.md")).contents
    [content] = first
    assert isinstance(content, TextResourceContents)
    assert content.text == (REPO_GUIDE / "02-first-lab.md").read_text(encoding="utf-8")
    assert content.mime_type == "text/markdown"


def test_guide_titles_come_from_the_first_heading() -> None:
    guide = load_guide(REPO_GUIDE)
    assert not isinstance(guide, GuideError)
    titles = {page.name: page.title for page in guide}
    assert titles["01-install.md"] is not None
    assert not titles["01-install.md"].startswith("#")


def test_a_missing_guide_fails_the_build(tmp_path: Path) -> None:
    assert isinstance(load_guide(tmp_path / "absent"), GuideError)
    assert isinstance(build_app(FakeBackend().client_for, tmp_path), GuideError)


def test_settings() -> None:
    assert load_settings({"TWINLAB_API_URL": "http://backend:8000/"}) == Settings(
        api_url="http://backend:8000"
    )
    assert isinstance(load_settings({}), SettingsError)
    assert isinstance(load_settings({"TWINLAB_API_URL": "backend:8000"}), SettingsError)
