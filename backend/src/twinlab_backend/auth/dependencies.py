"""Auth dependencies: resolve the current user, and guard routes by permission."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from twinlab_backend.auth.service import effective_permissions
from twinlab_backend.auth.sessions import resolve_session
from twinlab_backend.db.models import User
from twinlab_backend.deps import SessionDep, SettingsDep
from twinlab_backend.result import Err


async def current_user(request: Request, db: SessionDep, settings: SettingsDep) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    resolved = await resolve_session(db, token)
    if isinstance(resolved, Err):
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return resolved.value


CurrentUserDep = Annotated[User, Depends(current_user)]


def require(permission: str) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: 403 unless the current user holds `permission`."""

    async def dependency(user: CurrentUserDep) -> User:
        if permission not in effective_permissions(user):
            raise HTTPException(status_code=403, detail=f"missing permission: {permission}")
        return user

    return dependency
