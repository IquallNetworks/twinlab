"""Authentication endpoints: login/logout/identity, self password change, API keys."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import api_keys, user_management
from twinlab_backend.auth.dependencies import CurrentUserDep
from twinlab_backend.auth.passwords import verify_password
from twinlab_backend.auth.service import authenticate, global_permissions, global_role_names
from twinlab_backend.auth.sessions import create_session, revoke_all_for_user, revoke_session
from twinlab_backend.config import Settings
from twinlab_backend.db.models import ApiKey, User
from twinlab_backend.deps import SessionDep, SettingsDep
from twinlab_backend.result import Err

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyCreatedOut(BaseModel):
    key: str  # the Bearer secret — returned only here, stored hashed
    info: ApiKeyOut


class UserInfo(BaseModel):
    """The caller's identity and their **global** roles/permissions. Per-lab
    permissions are not here — they are carried on each lab's detail payload, since
    they depend on the lab."""

    username: str
    roles: list[str]
    permissions: list[str]


async def _user_info(db: AsyncSession, user: User) -> UserInfo:
    return UserInfo(
        username=user.username,
        roles=await global_role_names(db, user),
        permissions=sorted(await global_permissions(db, user)),
    )


def _set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login")
async def login(
    credentials: LoginRequest,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
) -> UserInfo:
    result = await authenticate(db, credentials.username, credentials.password)
    if isinstance(result, Err):
        # One opaque message for both unknown-user and wrong-password.
        raise ApiError(401, "invalid_credentials", "invalid credentials")
    user = result.value
    token = await create_session(db, user.id, timedelta(hours=settings.session_ttl_hours))
    _set_session_cookie(response, settings, token)
    return await _user_info(db, user)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: SessionDep,
    settings: SettingsDep,
) -> None:
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await revoke_session(db, token)
    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/me")
async def me(user: CurrentUserDep, db: SessionDep) -> UserInfo:
    return await _user_info(db, user)


@router.put("/password", status_code=204)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: CurrentUserDep,
    db: SessionDep,
    settings: SettingsDep,
) -> None:
    # Self-service change: requires the current password, keeps THIS session,
    # revokes the user's others (a stolen-session attacker can't ride along).
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(403, "invalid_credentials", "current password is incorrect")
    updated = await user_management.set_password(db, user.id, body.new_password)
    if isinstance(updated, Err):  # the caller exists; defensive only
        raise ApiError(404, updated.error.reason, updated.error.detail)
    await revoke_all_for_user(
        db, user.id, keep_raw_token=request.cookies.get(settings.session_cookie_name)
    )


def _api_key_out(row: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id, name=row.name, created_at=row.created_at, last_used_at=row.last_used_at
    )


@router.post("/api-keys", status_code=201)
async def create_api_key(
    body: CreateApiKeyRequest, user: CurrentUserDep, db: SessionDep
) -> ApiKeyCreatedOut:
    created = await api_keys.create_key(db, user.id, body.name)
    if isinstance(created, Err):
        raise ApiError(409, "name_taken", f"api key '{body.name}' already exists")
    raw_key, row = created.value
    return ApiKeyCreatedOut(key=raw_key, info=_api_key_out(row))


@router.get("/api-keys")
async def list_api_keys(user: CurrentUserDep, db: SessionDep) -> list[ApiKeyOut]:
    return [_api_key_out(row) for row in await api_keys.list_keys(db, user.id)]


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: uuid.UUID, user: CurrentUserDep, db: SessionDep) -> None:
    error = await api_keys.revoke_key(db, user.id, key_id)
    if error is not None:
        raise ApiError(404, "api_key_not_found", "api key not found")
