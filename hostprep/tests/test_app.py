"""The HTTP boundary: token gate, input validation, per-item outcome shape.
The primitives are monkeypatched — they have their own tests. httpx's
AsyncClient over ASGITransport, which is fully typed (unlike starlette's
TestClient)."""

from pathlib import Path

import httpx
import pytest

from hostprep import host
from hostprep.app import app

TOKEN = "test-token"
AUTH = {"X-Hostprep-Token": TOKEN}


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOSTPREP_TOKEN", TOKEN)


@pytest.fixture
def no_commands(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Stub the subprocess boundary; return the recorded argv list."""
    commands: list[list[str]] = []

    def record(argv: list[str]) -> host.CommandFailure | None:
        commands.append(argv)
        return None

    monkeypatch.setattr(host, "run_command", record)
    return commands


@pytest.mark.usefixtures("token")
async def test_health_needs_no_token() -> None:
    async with _client() as client:
        response = await client.get("/health")
    assert response.json() == {"status": "ok"}


@pytest.mark.usefixtures("token")
async def test_missing_token_is_401() -> None:
    async with _client() as client:
        response = await client.put("/bridges", json={"names": ["lab_1"]})
    assert response.status_code == 401


@pytest.mark.usefixtures("token")
async def test_wrong_token_is_401() -> None:
    async with _client() as client:
        response = await client.put(
            "/bridges", json={"names": ["lab_1"]}, headers={"X-Hostprep-Token": "nope"}
        )
    assert response.status_code == 401


async def test_unconfigured_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOSTPREP_TOKEN", raising=False)
    async with _client() as client:
        response = await client.put("/bridges", json={"names": ["lab_1"]}, headers=AUTH)
    assert response.status_code == 503


@pytest.mark.usefixtures("token")
async def test_bad_bridge_name_is_422_and_runs_nothing(no_commands: list[list[str]]) -> None:
    async with _client() as client:
        response = await client.put("/bridges", json={"names": ["eth0"]}, headers=AUTH)
    assert response.status_code == 422
    assert no_commands == []


@pytest.mark.usefixtures("token")
async def test_unlisted_module_is_422_and_runs_nothing(no_commands: list[list[str]]) -> None:
    async with _client() as client:
        response = await client.post("/modules", json={"names": ["evil_module"]}, headers=AUTH)
    assert response.status_code == 422
    assert no_commands == []


@pytest.mark.usefixtures("token")
async def test_ensure_bridges_reports_per_item(
    no_commands: list[list[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hostprep.app._SYSFS_NET", tmp_path)
    async with _client() as client:
        response = await client.put("/bridges", json={"names": ["lab_1", "lab_2"]}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert [b["status"] for b in body["bridges"]] == ["created", "created"]
    # Three commands per absent bridge: add, up, fwd-mask.
    assert len(no_commands) == 6


@pytest.mark.usefixtures("token")
async def test_delete_bridges_reports_per_item(
    no_commands: list[list[str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hostprep.app._SYSFS_NET", tmp_path)
    (tmp_path / "lab_1" / "bridge").mkdir(parents=True)
    async with _client() as client:
        response = await client.request(
            "DELETE", "/bridges", json={"names": ["lab_1", "lab_2"]}, headers=AUTH
        )
    assert response.status_code == 200
    assert [b["status"] for b in response.json()["bridges"]] == ["deleted", "absent"]
    assert no_commands == [["ip", "link", "del", "dev", "lab_1"]]


@pytest.mark.usefixtures("token")
async def test_load_modules_reports_per_item(no_commands: list[list[str]]) -> None:
    async with _client() as client:
        response = await client.post(
            "/modules", json={"names": ["vrf", "mpls-router"]}, headers=AUTH
        )
    assert response.status_code == 200
    body = response.json()
    assert all(m["ok"] for m in body["modules"])
    assert no_commands == [["modprobe", "vrf"], ["modprobe", "mpls-router"]]
