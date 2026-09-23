"""OIDC sign-in (contract delta 33, docs/oidc.md).

Two routers. `router` is the UNAUTHENTICATED browser side: the login page's
provider list and the two navigations of the flow. `admin_router` manages
provider records under `user:manage`.
"""

import uuid
from datetime import datetime, timedelta
from typing import Annotated, NoReturn

import httpx2
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import AfterValidator, BaseModel, Field

from twinlab_backend.api.auth import set_session_cookie
from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.dependencies import require_global
from twinlab_backend.auth.oidc import flow, icons, providers
from twinlab_backend.auth.oidc.providers import UNCHANGED, ProviderError, ProviderSpec, Unchanged
from twinlab_backend.auth.sessions import create_session
from twinlab_backend.config import Settings
from twinlab_backend.db.models import OidcProvider
from twinlab_backend.deps import OidcCacheDep, SessionDep, SettingsDep
from twinlab_backend.models import Principal
from twinlab_backend.result import Err

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])
admin_router = APIRouter(
    prefix="/oidc-providers",
    tags=["oidc"],
    dependencies=[Depends(require_global(perms.USER_MANAGE))],
)

# The slug in the callback URL registered at the provider.
_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,31}$"
_ProviderName = Annotated[str, Path(pattern=_NAME_PATTERN)]

# Why these scopes by default: `openid` makes it OIDC, `email` feeds tying and
# creation, `profile` the display name and the derived username — exactly what
# the resolution rules read, nothing more.
_DEFAULT_SCOPES = ["openid", "email", "profile"]


def _scopes(value: list[str]) -> list[str]:
    if "openid" not in value:
        raise ValueError('the scopes must include "openid"')
    if any(not scope or any(char.isspace() for char in scope) for scope in value):
        raise ValueError("a scope is one non-empty word")
    return list(dict.fromkeys(value))


def _issuer(value: str) -> str:
    if not value.startswith(("https://", "http://")):
        raise ValueError("the issuer is an http(s) URL")
    return value


Scopes = Annotated[list[str], AfterValidator(_scopes)]
Issuer = Annotated[str, Field(min_length=8, max_length=512), AfterValidator(_issuer)]
DisplayName = Annotated[str, Field(min_length=1, max_length=64)]
ClientId = Annotated[str, Field(min_length=1, max_length=255)]
ClientSecret = Annotated[str, Field(min_length=1, max_length=4096)]


class LoginProviderOut(BaseModel):
    name: str
    display_name: str
    icon: str | None  # a data: URI, or None for the client's monogram


class ProviderCreate(BaseModel):
    name: str = Field(pattern=_NAME_PATTERN)
    display_name: DisplayName
    issuer: Issuer
    client_id: ClientId
    # REQUIRED even though it may be null (a public client): a confidential
    # client must never be created without its secret by omission.
    client_secret: ClientSecret | None
    scopes: Scopes = Field(default_factory=lambda: list(_DEFAULT_SCOPES))
    # All three default off: the safe state is a provider that can only sign
    # in users who are already linked, and vouching for an issuer's emails is
    # a deliberate act.
    allow_create_users: bool = False
    allow_email_tying: bool = False
    trust_email: bool = False
    default_group_id: uuid.UUID | None = None
    enabled: bool = True


class ProviderReplace(BaseModel):
    display_name: DisplayName
    issuer: Issuer
    client_id: ClientId
    scopes: Scopes
    allow_create_users: bool
    allow_email_tying: bool
    trust_email: bool
    default_group_id: uuid.UUID | None
    enabled: bool
    # Write-only. OMITTED keeps the stored secret; a string replaces it; null
    # removes it (the provider becomes a public client). The field's absence
    # is read from `model_fields_set`, so the default below is never used as
    # a value.
    client_secret: ClientSecret | None = None

    def spec(self) -> ProviderSpec:
        return ProviderSpec(
            display_name=self.display_name,
            issuer=self.issuer,
            client_id=self.client_id,
            scopes=self.scopes,
            allow_create_users=self.allow_create_users,
            allow_email_tying=self.allow_email_tying,
            trust_email=self.trust_email,
            default_group_id=self.default_group_id,
            enabled=self.enabled,
        )

    def secret_change(self) -> str | None | Unchanged:
        return self.client_secret if "client_secret" in self.model_fields_set else UNCHANGED


class OidcProviderOut(BaseModel):
    name: str
    display_name: str
    issuer: str
    client_id: str
    has_client_secret: bool
    client_secret_readable: bool
    scopes: list[str]
    allow_create_users: bool
    allow_email_tying: bool
    trust_email: bool
    default_group: Principal | None
    enabled: bool
    icon: str | None
    callback_url: str | None
    linked_users: int
    created_at: datetime
    updated_at: datetime


_STATUS = {
    "provider_not_found": 404,
    "provider_name_taken": 409,
    "issuer_taken": 409,
    "oidc_secret_key_unset": 409,
    "oidc_discovery_failed": 422,
    "issuer_immutable": 422,
    "group_not_found": 422,
    "invalid_icon": 422,
}


def _raise(error: ProviderError) -> NoReturn:
    raise ApiError(_STATUS[error.reason], error.reason, error.detail or error.reason)


def _secret_key(settings: Settings) -> str | None:
    key = settings.oidc_secret_key
    return key.get_secret_value() if key is not None else None


def _out(
    provider: OidcProvider, settings: Settings, linked: dict[uuid.UUID, int]
) -> OidcProviderOut:
    group = provider.default_group
    return OidcProviderOut(
        name=provider.name,
        display_name=provider.display_name,
        issuer=provider.issuer,
        client_id=provider.client_id,
        has_client_secret=provider.client_secret_encrypted is not None,
        client_secret_readable=providers.secret_readable(provider, _secret_key(settings)),
        scopes=provider.scopes,
        allow_create_users=provider.allow_create_users,
        allow_email_tying=provider.allow_email_tying,
        trust_email=provider.trust_email,
        default_group=Principal(id=group.id, name=group.name) if group is not None else None,
        enabled=provider.enabled,
        icon=providers.icon_uri(provider),
        callback_url=flow.callback_url(settings, provider.name),
        linked_users=linked.get(provider.id, 0),
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


# --------------------------------------------------------------------------- #
# The browser side (unauthenticated)
# --------------------------------------------------------------------------- #


@router.get("/providers")
async def login_providers(db: SessionDep, settings: SettingsDep) -> list[LoginProviderOut]:
    # Empty while PUBLIC_ORIGIN is unset: no callback URL, so no sign-in.
    if not flow.enabled(settings):
        return []
    return [
        LoginProviderOut(
            name=provider.name,
            display_name=provider.display_name,
            icon=providers.icon_uri(provider),
        )
        for provider in await providers.list_providers(db)
        if provider.enabled
    ]


def _clear_state_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(flow.STATE_COOKIE, path=flow.state_cookie_path(settings))


@router.get("/{name}/login")
async def login(
    name: _ProviderName,
    db: SessionDep,
    settings: SettingsDep,
    cache: OidcCacheDep,
    next_path: Annotated[str | None, Query(alias="next")] = None,
) -> RedirectResponse:
    started = await flow.start(db, cache, settings, name, next_path)
    if isinstance(started, Err):
        return RedirectResponse(flow.login_error_location(settings, started.error.code), 302)
    response = RedirectResponse(started.value.authorization_url, 302)
    # Binds the attempt to THIS browser (see flow._consume_attempt). Lax, so
    # the provider's top-level redirect back still carries it.
    response.set_cookie(
        key=flow.STATE_COOKIE,
        value=started.value.state,
        max_age=flow.ATTEMPT_SECONDS,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path=flow.state_cookie_path(settings),
    )
    return response


@router.get("/{name}/callback")
async def callback(
    name: _ProviderName,
    request: Request,
    db: SessionDep,
    settings: SettingsDep,
    cache: OidcCacheDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    iss: str | None = None,
) -> RedirectResponse:
    finished = await flow.finish(
        db,
        cache,
        settings,
        provider_name=name,
        params=flow.CallbackParams(code=code, state=state, error=error, iss=iss),
        cookie_state=request.cookies.get(flow.STATE_COOKIE),
        # Per call: Authlib's client closes its transport when it exits.
        transport=httpx2.AsyncHTTPTransport(),
    )
    if isinstance(finished, Err):
        response = RedirectResponse(flow.login_error_location(settings, finished.error.code), 302)
        _clear_state_cookie(response, settings)
        return response
    token = await create_session(
        db, finished.value.user_id, timedelta(hours=settings.session_ttl_hours)
    )
    response = RedirectResponse(flow.post_login_location(settings, finished.value.next_path), 302)
    set_session_cookie(response, settings, token)
    _clear_state_cookie(response, settings)
    return response


# --------------------------------------------------------------------------- #
# Provider admin (user:manage)
# --------------------------------------------------------------------------- #


@admin_router.get("")
async def list_all(db: SessionDep, settings: SettingsDep) -> list[OidcProviderOut]:
    linked = await providers.linked_counts(db)
    return [_out(provider, settings, linked) for provider in await providers.list_providers(db)]


@admin_router.post("", status_code=201)
async def create(
    body: ProviderCreate, db: SessionDep, settings: SettingsDep, cache: OidcCacheDep
) -> OidcProviderOut:
    created = await providers.create_provider(
        db,
        cache,
        name=body.name,
        spec=ProviderSpec(
            display_name=body.display_name,
            issuer=body.issuer,
            client_id=body.client_id,
            scopes=body.scopes,
            allow_create_users=body.allow_create_users,
            allow_email_tying=body.allow_email_tying,
            trust_email=body.trust_email,
            default_group_id=body.default_group_id,
            enabled=body.enabled,
        ),
        client_secret=body.client_secret,
        secret_key=_secret_key(settings),
    )
    if isinstance(created, Err):
        _raise(created.error)
    return _out(created.value, settings, {})


async def _found(db: SessionDep, name: str) -> OidcProvider:
    provider = await providers.get_provider(db, name)
    if provider is None:
        _raise(ProviderError("provider_not_found", f"unknown provider '{name}'"))
    return provider


@admin_router.get("/{name}")
async def get_one(name: _ProviderName, db: SessionDep, settings: SettingsDep) -> OidcProviderOut:
    return _out(await _found(db, name), settings, await providers.linked_counts(db))


@admin_router.put("/{name}")
async def replace(
    name: _ProviderName, body: ProviderReplace, db: SessionDep, settings: SettingsDep
) -> OidcProviderOut:
    updated = await providers.update_provider(
        db,
        name=name,
        spec=body.spec(),
        client_secret=body.secret_change(),
        secret_key=_secret_key(settings),
    )
    if isinstance(updated, Err):
        _raise(updated.error)
    return _out(updated.value, settings, await providers.linked_counts(db))


@admin_router.delete("/{name}", status_code=204)
async def delete(name: _ProviderName, db: SessionDep) -> None:
    deleted = await providers.delete_provider(db, name)
    if isinstance(deleted, Err):
        _raise(deleted.error)


async def _bounded_body(request: Request) -> bytes | None:
    """The request body, or None past the icon cap — read incrementally so an
    oversized upload is refused without being buffered whole."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > icons.MAX_ICON_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@admin_router.put("/{name}/icon")
async def set_icon(
    name: _ProviderName, request: Request, db: SessionDep, settings: SettingsDep
) -> OidcProviderOut:
    content = await _bounded_body(request)
    if content is None:
        _raise(ProviderError("invalid_icon", f"the icon exceeds {icons.MAX_ICON_BYTES} bytes"))
    updated = await providers.set_icon(db, name, content, request.headers.get("content-type"))
    if isinstance(updated, Err):
        _raise(updated.error)
    return _out(updated.value, settings, await providers.linked_counts(db))


@admin_router.delete("/{name}/icon")
async def clear_icon(name: _ProviderName, db: SessionDep, settings: SettingsDep) -> OidcProviderOut:
    updated = await providers.clear_icon(db, name)
    if isinstance(updated, Err):
        _raise(updated.error)
    return _out(updated.value, settings, await providers.linked_counts(db))
