"""Auth dependencies: resolve the current user, and guard routes by permission.

Two guard families, matching the two kinds of permission:

- `require_global(perm)` — global-only permissions (lab:create, user:manage,
  group:manage): checked against the caller's global bindings.
- `require_lab(perm)` — lab-scoped permissions: resolves the lab from the `{lab_name}`
  path segment and checks the caller's effective permissions on *that* lab. A lab the
  caller can't read is reported as 404 (its existence isn't leaked); a readable lab
  the caller lacks `perm` on is 403.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.service import effective_permissions_for, global_permissions
from twinlab_backend.auth.sessions import resolve_session
from twinlab_backend.db.models import User
from twinlab_backend.deps import SessionDep, SettingsDep
from twinlab_backend.result import Err
from twinlab_backend.services import lab_store


async def current_user(request: Request, db: SessionDep, settings: SettingsDep) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    resolved = await resolve_session(db, token)
    if isinstance(resolved, Err):
        raise HTTPException(status_code=401, detail="invalid or expired session")
    return resolved.value


CurrentUserDep = Annotated[User, Depends(current_user)]

# The lab-name path segment, same tight charset as the labs router uses. Declared
# here (not imported from api.labs) to avoid a dependency cycle.
_LabNamePath = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


def _unknown_lab(lab_name: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail={"stage": "labs", "message": f"unknown lab '{lab_name}'"}
    )


def require_global(permission: str) -> Callable[..., Awaitable[User]]:
    """Dependency factory: 403 unless the caller holds `permission` globally."""

    async def dependency(user: CurrentUserDep, db: SessionDep) -> User:
        if permission not in await global_permissions(db, user):
            raise HTTPException(status_code=403, detail=f"missing permission: {permission}")
        return user

    return dependency


def require_lab(permission: str) -> Callable[..., Awaitable[User]]:
    """Dependency factory: resolve the `{lab_name}` lab and require `permission` on it.
    A caller without even `lab:read` gets 404 (existence hidden); with read but not
    `permission`, 403."""

    async def dependency(lab_name: _LabNamePath, user: CurrentUserDep, db: SessionDep) -> User:
        lab = await lab_store.get_lab(db, lab_name)
        if lab is None:
            raise _unknown_lab(lab_name)
        granted = await effective_permissions_for(db, user, lab)
        if perms.LAB_READ not in granted:
            raise _unknown_lab(lab_name)
        if permission not in granted:
            raise HTTPException(status_code=403, detail=f"missing permission: {permission}")
        return user

    return dependency
