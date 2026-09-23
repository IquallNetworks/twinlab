"""User-management operations: create, list, get, roles, password, profile,
active, delete, identities.

A user's global roles are global role bindings; assigning them replaces the user's
global bindings. Lab-scoped access is granted per lab (see the lab-grants API), not
here. DB access is the boundary; each mutating operation returns a typed result so
the HTTP layer can map it to a status code.

The **last-admin guard**: deactivating or deleting the only remaining active
admin would lock the system out, so both refuse ("last_admin"). The count is of
DIRECT global admin bindings — a group-derived admin doesn't count, which errs
on the safe (refusing) side.
"""

import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.passwords import hash_password
from twinlab_backend.db.models import RoleBinding, User, UserIdentity
from twinlab_backend.result import Err, Ok, Result
from twinlab_backend.services import rbac_store


@dataclass(frozen=True, slots=True)
class UserError:
    # "username_taken" | "email_taken" | "unknown_roles" | "user_not_found" |
    # "last_admin" | "identity_not_found"
    reason: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CreatedUser:
    user: User
    # The server-generated password when the caller supplied none — returned
    # ONCE (the api-key pattern); None when the caller chose one.
    generated_password: str | None


# 18 random bytes -> 24 URL-safe characters: well past any brute-force horizon
# and still pasteable. Also what a provider-created user gets, unseen.
_GENERATED_PASSWORD_BYTES = 18


def generate_password() -> str:
    return secrets.token_urlsafe(_GENERATED_PASSWORD_BYTES)


async def find_by_email(session: AsyncSession, email: str) -> User | None:
    """The user holding `email`, compared case-insensitively — the same rule
    the unique index enforces (lower() on both sides, so Postgres and not
    Python decides what "same" means)."""
    return await session.scalar(select(User).where(func.lower(User.email) == func.lower(email)))


async def _email_taken(session: AsyncSession, email: str, *, except_id: uuid.UUID | None) -> bool:
    holder = await find_by_email(session, email)
    return holder is not None and holder.id != except_id


def _validate_global_roles(role_names: list[str]) -> UserError | None:
    """Every name must be a real, globally-bindable role. A lab-only role (e.g.
    lab_viewer) or an unknown name is rejected — global assignment is the wrong place
    for it."""
    bad = sorted(
        name for name in set(role_names) if not perms.role_bindable_at(name, perms.SCOPE_GLOBAL)
    )
    return UserError("unknown_roles", ", ".join(bad)) if bad else None


async def username_taken(session: AsyncSession, username: str) -> bool:
    return await session.scalar(select(User).where(User.username == username)) is not None


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    display_name: str,
    password: str | None,
    role_names: list[str],
    commit: bool,
) -> Result[CreatedUser, UserError]:
    """Create a user. `password=None` generates one (returned on the result).
    `commit=False` leaves the transaction open so a caller can write more rows
    atomically with the user (an OIDC sign-in writes the identity link and the
    default-group membership in the same transaction)."""
    if await username_taken(session, username):
        return Err(UserError("username_taken", username))
    if await _email_taken(session, email, except_id=None):
        return Err(UserError("email_taken", f"an account already uses {email}"))

    # No roles requested -> the baseline `user` role (authenticated, no access).
    roles = role_names or [perms.DEFAULT_USER_ROLE]
    invalid = _validate_global_roles(roles)
    if invalid is not None:
        return Err(invalid)

    secret = password if password is not None else generate_password()
    user = User(
        username=username,
        email=email,
        display_name=display_name,
        password_hash=hash_password(secret),
    )
    session.add(user)
    await session.flush()  # assign user.id before its bindings reference it
    await rbac_store.set_principal_global_roles(
        session,
        principal_type=perms.PRINCIPAL_USER,
        principal_id=user.id,
        role_names=roles,
        granted_by=None,
        commit=commit,
    )
    return Ok(CreatedUser(user=user, generated_password=secret if password is None else None))


async def set_profile(
    session: AsyncSession, user_id: uuid.UUID, *, email: str, display_name: str
) -> Result[User, UserError]:
    """Admin edit of both profile fields — for ANY user, the caller included
    (that is how an admin replaces their own backfilled placeholder). The
    user's linked identities are untouched: the link, not the email, is what
    their provider sign-in resolves through."""
    user = await session.get(User, user_id)
    if user is None:
        return Err(UserError("user_not_found"))
    if await _email_taken(session, email, except_id=user.id):
        return Err(UserError("email_taken", f"an account already uses {email}"))
    user.email = email
    user.display_name = display_name
    await session.commit()
    return Ok(user)


async def set_display_name(session: AsyncSession, user: User, display_name: str) -> User:
    """Self-service edit — the display name ONLY. Email is excluded on purpose:
    with OIDC tying, a user who could set their own address to a colleague's
    would receive that colleague's first provider sign-in."""
    user.display_name = display_name
    await session.commit()
    return user


async def identities_by_user(session: AsyncSession) -> dict[uuid.UUID, list[UserIdentity]]:
    """Every linked identity, grouped by user — one query for a listing."""
    rows = (await session.scalars(select(UserIdentity).order_by(UserIdentity.created_at))).all()
    grouped: dict[uuid.UUID, list[UserIdentity]] = {}
    for row in rows:
        grouped.setdefault(row.user_id, []).append(row)
    return grouped


async def unlink_identity(
    session: AsyncSession, user_id: uuid.UUID, identity_id: uuid.UUID
) -> Result[None, UserError]:
    """Remove one link. Another user's identity id is indistinguishable from an
    absent one, so an admin cannot unlink through the wrong user by mistake."""
    row = await session.get(UserIdentity, identity_id)
    if row is None or row.user_id != user_id:
        return Err(UserError("identity_not_found"))
    await session.delete(row)
    await session.commit()
    return Ok(None)


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
        commit=True,
    )
    return Ok(user)
