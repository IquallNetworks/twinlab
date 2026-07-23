"""User-management operations (create, list, set global roles).

A user's global roles are global role bindings; assigning them replaces the user's
global bindings. Lab-scoped access is granted per lab (see the lab-grants API), not
here. DB access is the boundary; each mutating operation returns a typed result so
the HTTP layer can map it to a status code.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.passwords import hash_password
from twinlab_backend.db.models import User
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import rbac_store


@dataclass(frozen=True, slots=True)
class UserError:
    reason: str  # "username_taken" | "unknown_roles" | "user_not_found"
    detail: str = ""


def _validate_global_roles(role_names: list[str]) -> UserError | None:
    """Every name must be a real, globally-bindable role. A lab-only role (e.g.
    lab_viewer) or an unknown name is rejected — global assignment is the wrong place
    for it."""
    bad = sorted(
        name for name in set(role_names) if not perms.role_bindable_at(name, perms.SCOPE_GLOBAL)
    )
    return UserError("unknown_roles", ", ".join(bad)) if bad else None


async def create_user(
    session: AsyncSession, username: str, password: str, role_names: list[str]
) -> Result[User, UserError]:
    if await session.scalar(select(User).where(User.username == username)) is not None:
        return Err(UserError("username_taken", username))

    # No roles requested -> the baseline `user` role (authenticated, no access).
    roles = role_names or [perms.DEFAULT_USER_ROLE]
    invalid = _validate_global_roles(roles)
    if invalid is not None:
        return Err(invalid)

    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    await session.flush()  # assign user.id before its bindings reference it
    await rbac_store.set_principal_global_roles(
        session,
        principal_type=perms.PRINCIPAL_USER,
        principal_id=user.id,
        role_names=roles,
        granted_by=None,
    )
    return Ok(user)


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.username))).all())


async def set_roles(
    session: AsyncSession, user_id: uuid.UUID, role_names: list[str]
) -> Result[User, UserError]:
    user = await session.get(User, user_id)
    if user is None:
        return Err(UserError("user_not_found"))

    invalid = _validate_global_roles(role_names)
    if invalid is not None:
        return Err(invalid)

    await rbac_store.set_principal_global_roles(
        session,
        principal_type=perms.PRINCIPAL_USER,
        principal_id=user.id,
        role_names=role_names,
        granted_by=None,
    )
    return Ok(user)
