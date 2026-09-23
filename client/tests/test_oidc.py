"""Delta 33 client surface: user profiles, generated passwords, OIDC providers."""

import json
from collections.abc import Callable
from typing import cast
from uuid import UUID

import httpx2

from twinlab_client import UNCHANGED, TwinlabClient, Unchanged

ClientFactory = Callable[[Callable[[httpx2.Request], httpx2.Response]], TwinlabClient]

_USER_ID = "0198c0de-0000-7000-8000-000000000101"
_IDENTITY_ID = "0198c0de-0000-7000-8000-000000000102"

_USER_WIRE: dict[str, object] = {
    "id": _USER_ID,
    "username": "alice",
    "email": "alice@example.com",
    "display_name": "Alice Liddell",
    "is_active": True,
    "roles": ["user"],
    "identities": [
        {
            "id": _IDENTITY_ID,
            "provider": "dex",
            "subject": "sub-1",
            "email_at_link": "alice@example.com",
            "created_at": "2026-09-23T10:00:00+00:00",
            "last_login_at": None,
        }
    ],
}

_PROVIDER_WIRE: dict[str, object] = {
    "name": "dex",
    "display_name": "Dex",
    "issuer": "https://idp.example.com",
    "client_id": "twinlab",
    "has_client_secret": True,
    "client_secret_readable": True,
    "scopes": ["openid", "email", "profile"],
    "allow_create_users": False,
    "allow_email_tying": True,
    "trust_email": False,
    "default_group": None,
    "enabled": True,
    "icon": None,
    "callback_url": "https://twinlab.example.com/api/v1/auth/oidc/dex/callback",
    "linked_users": 1,
    "created_at": "2026-09-23T10:00:00+00:00",
    "updated_at": "2026-09-23T10:00:00+00:00",
}


def _body(request: httpx2.Request) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(request.content.decode()))


async def test_create_user_omits_the_password_to_have_one_generated(
    make_client: ClientFactory,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert _body(request) == {
            "username": "alice",
            "email": "alice@example.com",
            "display_name": "Alice Liddell",
        }
        return httpx2.Response(201, json={"user": _USER_WIRE, "generated_password": "g" * 24})

    async with make_client(handler) as client:
        created = await client.create_user("alice", "alice@example.com", "Alice Liddell")
    assert created.generated_password == "g" * 24
    assert created.user.display_name == "Alice Liddell"
    assert created.user.identities[0].provider == "dex"


async def test_profile_and_unlink_routes(make_client: ClientFactory) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx2.Response(204)
        if request.url.path == "/api/v1/auth/profile":
            assert _body(request) == {"display_name": "Al"}
            return httpx2.Response(
                200,
                json={
                    "username": "alice",
                    "email": "alice@example.com",
                    "display_name": "Al",
                    "roles": [],
                    "permissions": [],
                },
            )
        assert _body(request) == {"email": "a@x.org", "display_name": "Alice"}
        return httpx2.Response(200, json=_USER_WIRE)

    async with make_client(handler) as client:
        _ = await client.update_user_profile(UUID(_USER_ID), email="a@x.org", display_name="Alice")
        info = await client.update_own_profile("Al")
        await client.unlink_identity(UUID(_USER_ID), UUID(_IDENTITY_ID))
    assert info.display_name == "Al"
    assert seen == [
        ("PUT", f"/api/v1/users/{_USER_ID}/profile"),
        ("PUT", "/api/v1/auth/profile"),
        ("DELETE", f"/api/v1/users/{_USER_ID}/identities/{_IDENTITY_ID}"),
    ]


async def test_login_providers_parse(make_client: ClientFactory) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, json=[{"name": "dex", "display_name": "Dex", "icon": "data:image/png;base64,AA=="}]
        )

    async with make_client(handler) as client:
        providers = await client.login_providers()
    assert providers[0].icon == "data:image/png;base64,AA=="


async def test_create_provider_states_the_secret_even_when_public(
    make_client: ClientFactory,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = _body(request)
        assert body["client_secret"] is None  # present, null: a public client
        assert "scopes" not in body  # the server's default
        assert body["allow_create_users"] is False
        return httpx2.Response(201, json={**_PROVIDER_WIRE, "has_client_secret": False})

    async with make_client(handler) as client:
        provider = await client.create_oidc_provider(
            "dex", "Dex", "https://idp.example.com", "twinlab", client_secret=None
        )
    assert provider.has_client_secret is False


async def _replace(client: TwinlabClient, secret: str | None | Unchanged) -> None:
    _ = await client.update_oidc_provider(
        "dex",
        display_name="Dex",
        issuer="https://idp.example.com",
        client_id="twinlab",
        scopes=["openid", "email"],
        allow_create_users=False,
        allow_email_tying=True,
        trust_email=False,
        default_group_id=None,
        enabled=True,
        client_secret=secret,
    )


async def test_replace_leaves_the_secret_alone_unless_told(make_client: ClientFactory) -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(_body(request))
        return httpx2.Response(200, json=_PROVIDER_WIRE)

    async with make_client(handler) as client:
        await _replace(client, UNCHANGED)
        await _replace(client, None)
        await _replace(client, "new-secret")
    assert "client_secret" not in bodies[0]  # omitted on the wire = keep
    assert bodies[1]["client_secret"] is None  # null = remove
    assert bodies[2]["client_secret"] == "new-secret"


async def test_icons_travel_as_raw_bytes_with_their_type(make_client: ClientFactory) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "PUT":
            assert request.headers["content-type"] == "image/png"
            assert request.content == png
        return httpx2.Response(200, json=_PROVIDER_WIRE)

    async with make_client(handler) as client:
        _ = await client.set_oidc_provider_icon("dex", png, "image/png")
        _ = await client.clear_oidc_provider_icon("dex")
