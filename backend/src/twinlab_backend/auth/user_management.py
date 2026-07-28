"""User-management operations: create, list, get, roles, password, active, delete.

A user's global roles are global role bindings; assigning them replaces the user's
global bindings. Lab-scoped access is granted per lab (see the lab-grants API), not
here. DB access is the boundary; each mutating operation returns a typed result so
the HTTP layer can map it to a status code.

The **last-admin guard**: deactivating or deleting the only remaining active
admin would lock the system out, so both refuse ("last_admin"). The count is of
DIRECT global admin bindings — a group-derived admin doesn't count, which errs
on the safe (refusing) side.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.passwords import hash_password
from twinlab_backend.db.models import RoleBinding, User
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import rbac_store


@dataclass(frozen=True, slots=True)
class UserError:
    reason: str  # "username_taken" | "unknown_roles" | "user_not_found" | "last_admin"
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


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def _is_last_active_admin(session: AsyncSession, user: User) -> bool:
    """True when `user` is an active, directly-bound admin and no OTHER active
    user holds a direct global admin binding."""
    if not user.is_active:
        return False
    admin_ids = select(RoleBinding.principal_id).where(
        RoleBinding.principal_type == perms.PRINCIPAL_USER,
        RoleBinding.scope_type == perms.SCOPE_GLOBAL,
        RoleBinding.role_name == perms.ADMIN_ROLE,
    )
    count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.is_active, User.id.in_(admin_ids), User.id != user.id)
    )
    is_admin = await session.scalar(admin_ids.where(RoleBinding.principal_id == user.id).limit(1))
    return is_admin is not None and (count or 0) == 0


async def set_password(
    session: AsyncSession, user_id: uuid.UUID, password: str
) -> Result[User, UserError]:
    user = await session.get(User, user_id)
    if user is None:
        return Err(UserError("user_not_found"))
    user.password_hash = hash_password(password)
    await session.commit()
    return Ok(user)


async def set_active(
    session: AsyncSession, user_id: uuid.UUID, is_active: bool
) -> Result[User, UserError]:
    user = await session.get(User, user_id)
    if user is None:
        return Err(UserError("user_not_found"))
    if not is_active and await _is_last_active_admin(session, user):
        return Err(UserError("last_admin", "cannot deactivate the last active admin"))
    user.is_active = is_active
    await session.commit()
    return Ok(user)


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> Result[None, UserError]:
    """Delete a user: their RECEIVED role bindings go with them (polymorphic
    principal reference, so removed explicitly); sessions and API keys cascade;
    rows where they were the actor survive (owned labs -> owner NULL, grants
    they made keep granted_by NULL — both FK-level SET NULL)."""
    user = await session.get(User, user_id)
    if user is None:
        return Err(UserError("user_not_found"))
    if await _is_last_active_admin(session, user):
        return Err(UserError("last_admin", "cannot delete the last active admin"))
    _ = await session.execute(
        delete(RoleBinding).where(
            RoleBinding.principal_type == perms.PRINCIPAL_USER,
            RoleBinding.principal_id == user.id,
        )
    )
    await session.delete(user)
    await session.commit()
    return Ok(None)


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
