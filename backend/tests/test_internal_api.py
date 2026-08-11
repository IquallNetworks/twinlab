"""/internal/ssh/authorized-keys: token guard + response mapping.

DB-less like the rest of the suite: the service call is monkeypatched (its
DB/clab orchestration is covered live by the black-box jump slice); state
gets a dummy session factory and clab client.
"""

import os
from collections.abc import Callable, Coroutine
from typing import cast

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from twinlab_backend.api import internal as internal_api
from twinlab_backend.app import create_app
from twinlab_backend.config import Settings, load_settings
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services.clab_api import ClabApiClient, ClabApiError


class _NullSession:
    # The surface get_db uses: constructed by the factory, closed (shielded)
    # at request teardown. These routes never touch the session itself.
    async def close(self) -> None:
        return None


def _settings(token: str | None) -> Settings:
    loaded = load_settings(os.environ)
    assert isinstance(loaded, Ok)
    return loaded.value.model_copy(
        update={"ssh_jump_token": SecretStr(token) if token is not None else None}
    )


def _client(token: str | None) -> httpx.AsyncClient:
    app = create_app()
    app.state.settings = _settings(token)
    app.state.session_factory = cast("async_sessionmaker[AsyncSession]", _NullSession)
    app.state.clab_client = cast("ClabApiClient", object())
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


_LOOKUP = "/internal/ssh/authorized-keys?fingerprint=SHA256:abc"

AuthorizedKeysStub = Callable[
    [AsyncSession, ClabApiClient, str], Coroutine[None, None, Result[str, ClabApiError]]
]


def _stub(result: Result[str, ClabApiError]) -> AuthorizedKeysStub:
    async def lookup(
        session: AsyncSession, clab: ClabApiClient, fingerprint: str
    ) -> Result[str, ClabApiError]:
        return result

    return lookup


async def test_unconfigured_token_hides_the_route() -> None:
    async with _client(None) as client:
        response = await client.get(_LOOKUP, headers={"X-Jump-Token": "anything"})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_wrong_token_is_401() -> None:
    async with _client("right-token") as client:
        missing = await client.get(_LOOKUP)
        wrong = await client.get(_LOOKUP, headers={"X-Jump-Token": "wrong-token"})
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "not_authenticated"


async def test_answer_is_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    line = 'restrict,port-forwarding,permitopen="10.77.4.101:*" ssh-ed25519 AAAA twinlab:alice'
    monkeypatch.setattr(internal_api.ssh_access, "authorized_keys_for", _stub(Ok(line)))
    async with _client("t0ken") as client:
        response = await client.get(_LOOKUP, headers={"X-Jump-Token": "t0ken"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == line


async def test_denial_is_empty_body(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(internal_api.ssh_access, "authorized_keys_for", _stub(Ok("")))
    async with _client("t0ken") as client:
        response = await client.get(_LOOKUP, headers={"X-Jump-Token": "t0ken"})
    assert response.status_code == 200
    assert response.text == ""


async def test_clab_failure_is_502_so_sshd_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    error = ClabApiError(message="clab-api unreachable", status_code=None)
    monkeypatch.setattr(internal_api.ssh_access, "authorized_keys_for", _stub(Err(error)))
    async with _client("t0ken") as client:
        response = await client.get(_LOOKUP, headers={"X-Jump-Token": "t0ken"})
    assert response.status_code == 502
    assert response.json()["code"] == "clab_api_error"
