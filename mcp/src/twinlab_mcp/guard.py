"""Bearer authentication in front of the MCP transport.

Every HTTP request must carry `Authorization: Bearer <twinlab-api-key>`, and
the key must be one the backend accepts: one `GET /auth/me` per request, so a
revoked key or a deactivated owner stops working on the next call. A request
that fails either check never reaches the MCP layer.

This is deliberately not the SDK's OAuth resource-server support: that
advertises RFC 9728 metadata pointing clients at an authorization server,
which Twinlab does not run.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

import httpx2
from starlette.types import ASGIApp, Receive, Scope, Send
from twinlab_client import TwinlabApiError, TwinlabClient, TwinlabProtocolError

# Answered without a key: the compose healthcheck.
HEALTH_PATH = "/health"


def bearer_token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


@dataclass(frozen=True, slots=True)
class Rejection:
    status: int
    code: str
    message: str


async def check_key(client_for: Callable[[str], TwinlabClient], key: str) -> Rejection | None:
    """None when the backend accepts the key."""
    try:
        async with client_for(key) as client:
            _ = await client.me()
    except TwinlabApiError as exc:
        if exc.status_code == 401:
            return Rejection(401, "invalid_api_key", "the API key was not accepted")
        return Rejection(502, "backend_error", f"the backend refused the key check: {exc}")
    except (httpx2.HTTPError, TwinlabProtocolError) as exc:
        return Rejection(502, "backend_unreachable", f"the backend could not be reached: {exc}")
    return None


class BearerGuard:
    def __init__(self, app: ASGIApp, client_for: Callable[[str], TwinlabClient]) -> None:
        self._app = app
        self._client_for = client_for

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Lifespan passes straight through: the SDK's session manager starts
        # its task group there.
        if scope["type"] != "http" or scope["path"] == HEALTH_PATH:
            await self._app(scope, receive, send)
            return
        authorization: str | None = None
        for name, value in scope["headers"]:
            if name == b"authorization":
                authorization = value.decode("latin-1")
                break
        key = bearer_token(authorization)
        if key is None:
            await _reject(
                send, Rejection(401, "missing_api_key", "send Authorization: Bearer <api-key>")
            )
            return
        rejection = await check_key(self._client_for, key)
        if rejection is not None:
            await _reject(send, rejection)
            return
        await self._app(scope, receive, send)


async def _reject(send: Send, rejection: Rejection) -> None:
    body = json.dumps({"code": rejection.code, "message": rejection.message}).encode()
    headers = [(b"content-type", b"application/json")]
    if rejection.status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="twinlab"'))
    await send({"type": "http.response.start", "status": rejection.status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
