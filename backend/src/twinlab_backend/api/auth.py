"""Authentication endpoints: login/logout/identity, self password change,
API keys, SSH keys."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from twinlab_backend.api_errors import ApiError
from twinlab_backend.auth import api_keys, ssh_keygen, ssh_keys, user_management
from twinlab_backend.auth.dependencies import CurrentUserDep
from twinlab_backend.auth.passwords import verify_password
from twinlab_backend.auth.service import authenticate, global_permissions, global_role_names
from twinlab_backend.auth.sessions import create_session, revoke_all_for_user, revoke_session
from twinlab_backend.config import Settings
from twinlab_backend.db.models import ApiKey, SshKey, User
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


class CreateSshKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    # One authorized_keys-format line; 16 KiB is generous headroom over the
    # largest real key (an rsa-4096 line is ~750 bytes).
    public_key: str = Field(min_length=1, max_length=16384)


class SshKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    algorithm: str
    fingerprint: str  # "SHA256:<unpadded base64>", as `ssh-keygen -lf` prints
    comment: str | None
    created_at: datetime
    last_used_at: datetime | None  # last OFFERED at the jump, not last node login


class GenerateSshKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class SshKeyGeneratedOut(BaseModel):
    # The only time the private key exists outside the caller's hands: the
    # public half is registered, the private half never stored (no escrow).
    private_key: str
    info: SshKeyOut


class UserInfo(BaseModel):
    """The caller's identity and their **global** roles/permissions. Per-lab
    permissions are not here — they are carried on each lab's detail payload, since
    they depend on the lab."""

    username: str
    email: str
    display_name: str
    roles: list[str]
    permissions: list[str]


class SetOwnProfileRequest(BaseModel):
    # The display name ONLY (delta 33): self-service email change would let a
    # user capture a colleague's first OIDC sign-in through email tying.
    display_name: str = Field(min_length=1, max_length=128)


async def _user_info(db: AsyncSession, user: User) -> UserInfo:
    return UserInfo(
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        roles=await global_role_names(db, user),
        permissions=sorted(await global_permissions(db, user)),
    )


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
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
    set_session_cookie(response, settings, token)
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


@router.put("/profile")
async def update_profile(
    body: SetOwnProfileRequest, user: CurrentUserDep, db: SessionDep
) -> UserInfo:
    updated = await user_management.set_display_name(db, user, body.display_name)
    return await _user_info(db, updated)


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


def _ssh_key_out(row: SshKey) -> SshKeyOut:
    return SshKeyOut(
        id=row.id,
        name=row.name,
        algorithm=row.algorithm,
        fingerprint=row.fingerprint,
        comment=row.comment,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


# Store reason -> (status, message builder). Parse failures are 422 (the body
# is syntactically fine but the key inside it isn't); conflicts are 409.
_SSH_KEY_CREATE_ERRORS: dict[str, tuple[int, str]] = {
    "invalid_public_key": (422, "not a valid OpenSSH public key"),
    "unsupported_key_type": (422, "unsupported key type"),
    "name_taken": (409, "ssh key name already exists"),
    "key_already_registered": (409, "this key is already registered"),
}


@router.post("/ssh-keys", status_code=201)
async def create_ssh_key(
    body: CreateSshKeyRequest, user: CurrentUserDep, db: SessionDep
) -> SshKeyOut:
    created = await ssh_keys.create_key(db, user.id, body.name, body.public_key)
    if isinstance(created, Err):
        status, message = _SSH_KEY_CREATE_ERRORS[created.error.reason]
        detail = f": {created.error.detail}" if created.error.detail else ""
        raise ApiError(status, created.error.reason, f"{message}{detail}")
    return _ssh_key_out(created.value)


@router.post("/ssh-keys/generate", status_code=201)
async def generate_ssh_key(
    body: GenerateSshKeyRequest, user: CurrentUserDep, db: SessionDep
) -> SshKeyGeneratedOut:
    # ssh-keygen is blocking subprocess work; keep it off the event loop.
    generated = await run_in_threadpool(ssh_keygen.generate_ed25519, f"{user.username}@twinlab")
    if isinstance(generated, Err):
        raise ApiError(500, "internal_error", f"key generation failed: {generated.error.detail}")
    created = await ssh_keys.create_key(db, user.id, body.name, generated.value.public_key)
    if isinstance(created, Err):
        # Only name_taken can occur — the key is freshly random and the
        # public half just came out of ssh-keygen.
        status, message = _SSH_KEY_CREATE_ERRORS[created.error.reason]
        raise ApiError(status, created.error.reason, message)
    return SshKeyGeneratedOut(
        private_key=generated.value.private_key, info=_ssh_key_out(created.value)
    )


@router.get("/ssh-keys")
async def list_ssh_keys(user: CurrentUserDep, db: SessionDep) -> list[SshKeyOut]:
    return [_ssh_key_out(row) for row in await ssh_keys.list_keys(db, user.id)]


@router.delete("/ssh-keys/{key_id}", status_code=204)
async def delete_ssh_key(key_id: uuid.UUID, user: CurrentUserDep, db: SessionDep) -> None:
    error = await ssh_keys.delete_key(db, user.id, key_id)
    if error is not None:
        raise ApiError(404, "ssh_key_not_found", "ssh key not found")
