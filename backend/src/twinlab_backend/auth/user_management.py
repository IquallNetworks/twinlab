"""User-management operations (create, list, set roles).

DB access is the boundary; each mutating operation returns a typed result so the
HTTP layer can map it to a status code.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth.passwords import hash_password
from twinlab_backend.db.models import Role, User
from twinlab_backend.result import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class UserError:
    reason: str  # "username_taken" | "unknown_roles" | "user_not_found"
    detail: str = ""


async def _resolve_roles(
    session: AsyncSession, role_names: list[str]
) -> Result[list[Role], UserError]:
    roles = list((await session.scalars(select(Role).where(Role.name.in_(role_names)))).all())
    missing = sorted(set(role_names) - {role.name for role in roles})
    if missing:
        return Err(UserError("unknown_roles", ", ".join(missing)))
    return Ok(roles)


async def create_user(
    session: AsyncSession, username: str, password: str, role_names: list[str]
) -> Result[User, UserError]:
    if await session.scalar(select(User).where(User.username == username)) is not None:
        return Err(UserError("username_taken", username))

    resolved = await _resolve_roles(session, role_names)
    if isinstance(resolved, Err):
        return resolved

    user = User(username=username, password_hash=hash_password(password))
    user.roles = resolved.value
    session.add(user)
    await session.commit()
    return Ok(user)


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.username))).all())


async def set_roles(
    session: AsyncSession, user_id: uuid.UUID, role_names: list[str]
) -> Result[User, UserError]:
    user = await session.get(User, user_id)
    if user is None:
        return Err(UserError("user_not_found"))

    resolved = await _resolve_roles(session, role_names)
    if isinstance(resolved, Err):
        return resolved

    user.roles = resolved.value
    await session.commit()
    return Ok(user)
