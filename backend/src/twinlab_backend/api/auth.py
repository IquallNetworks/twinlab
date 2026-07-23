"""Authentication endpoints: login, logout, and the current identity."""

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth.dependencies import CurrentUserDep
from twinlab_backend.auth.service import authenticate, global_permissions, global_role_names
from twinlab_backend.auth.sessions import create_session, revoke_session
from twinlab_backend.config import Settings
from twinlab_backend.db.models import User
from twinlab_backend.deps import SessionDep, SettingsDep
from twinlab_backend.result import Err

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


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
        raise HTTPException(status_code=401, detail="invalid credentials")
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
