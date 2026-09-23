"""Persistence for groups and role bindings.

DB access is the boundary; each mutating operation commits and returns a typed
result so the HTTP layer maps it to a status code. Domain outcomes are values;
genuine infrastructure failures raise. Anti-escalation and role-scope validation are
enforced in the API layer (they need the caller's effective permissions); this store
persists once those checks pass.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from twinlab_backend.auth import permissions as perms
from twinlab_backend.db.models import Group, RoleBinding, User


@dataclass(frozen=True, slots=True)
class RbacStoreError:
    reason: str  # "group_not_found" | "user_not_found" | "name_taken" | "binding_not_found"
    detail: str = ""


# --- Groups ---


async def create_group(
    session: AsyncSession, name: str, description: str
) -> Group | RbacStoreError:
    group = Group(name=name, description=description)
    session.add(group)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return RbacStoreError("name_taken", name)
    return group


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.scalars(select(Group).order_by(Group.name))).all())


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> Group | None:
    return await session.get(Group, group_id)


async def set_group_members(
    session: AsyncSession, group_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> Group | RbacStoreError:
    group = await session.get(Group, group_id)
    if group is None:
        return RbacStoreError("group_not_found")
    users = list((await session.scalars(select(User).where(User.id.in_(user_ids)))).all())
    missing = sorted(str(uid) for uid in set(user_ids) - {u.id for u in users})
    if missing:
        return RbacStoreError("user_not_found", ", ".join(missing))
    group.members = users
    await session.commit()
    return group


async def delete_group(session: AsyncSession, group_id: uuid.UUID) -> None | RbacStoreError:
    group = await session.get(Group, group_id)
    if group is None:
        return RbacStoreError("group_not_found")
    # Bindings target a group polymorphically (no FK cascade), so drop the group's
    # own bindings explicitly — a binding to a nonexistent group would be inert dead
    # weight. Membership rows go via the group_members FK cascade.
    await session.execute(
        delete(RoleBinding).where(
            RoleBinding.principal_type == perms.PRINCIPAL_GROUP,
            RoleBinding.principal_id == group_id,
        )
    )
    await session.delete(group)
    await session.commit()
    return None


# --- Bindings ---


async def list_lab_bindings(session: AsyncSession, lab_id: uuid.UUID) -> list[RoleBinding]:
    return list(
        (
            await session.scalars(
                select(RoleBinding)
                .where(RoleBinding.scope_type == perms.SCOPE_LAB, RoleBinding.lab_id == lab_id)
                .order_by(RoleBinding.granted_at)
            )
        ).all()
    )


async def create_binding(
    session: AsyncSession,
    *,
    principal_type: str,
    principal_id: uuid.UUID,
    role_name: str,
    scope_type: str,
    lab_id: uuid.UUID | None,
    granted_by: uuid.UUID | None,
) -> RoleBinding | RbacStoreError:
    """Persist a binding. Validates the principal exists; a duplicate (same principal,
    role, scope, lab) is idempotently returned rather than erroring."""
    if principal_type == perms.PRINCIPAL_USER:
        if await session.get(User, principal_id) is None:
            return RbacStoreError("user_not_found", str(principal_id))
    elif await session.get(Group, principal_id) is None:
        return RbacStoreError("group_not_found", str(principal_id))

    binding = RoleBinding(
        principal_type=principal_type,
        principal_id=principal_id,
        role_name=role_name,
        scope_type=scope_type,
        lab_id=lab_id,
        granted_by=granted_by,
    )
    session.add(binding)
    try:
        await session.commit()
    except IntegrityError:
        # The uniqueness constraint fired: the grant already exists. Return it so the
        # call is idempotent.
        await session.rollback()
        existing = await session.scalar(
            select(RoleBinding).where(
                RoleBinding.principal_type == principal_type,
                RoleBinding.principal_id == principal_id,
                RoleBinding.role_name == role_name,
                RoleBinding.scope_type == scope_type,
                _lab_id_match(lab_id),
            )
        )
        if existing is not None:
            return existing
        raise
    return binding


def _lab_id_match(lab_id: uuid.UUID | None) -> ColumnElement[bool]:
    return RoleBinding.lab_id.is_(None) if lab_id is None else RoleBinding.lab_id == lab_id


async def get_lab_binding(
    session: AsyncSession, binding_id: uuid.UUID, lab_id: uuid.UUID
) -> RoleBinding | None:
    """A binding by id, scoped to one lab — so the lab-grants endpoint can only touch
    bindings on the lab it authorized against."""
    return await session.scalar(
        select(RoleBinding).where(
            RoleBinding.id == binding_id,
            RoleBinding.scope_type == perms.SCOPE_LAB,
            RoleBinding.lab_id == lab_id,
        )
    )


async def delete_binding(session: AsyncSession, binding: RoleBinding) -> None:
    await session.delete(binding)
    await session.commit()


async def set_principal_global_roles(
    session: AsyncSession,
    *,
    principal_type: str,
    principal_id: uuid.UUID,
    role_names: list[str],
    granted_by: uuid.UUID | None,
    commit: bool,
) -> None:
    """Replace a principal's global bindings with exactly `role_names`. Caller has
    validated the roles are global-bindable and the principal exists. `commit`
    False leaves the transaction open for a caller writing more rows
    atomically with these (creating a user through an OIDC sign-in)."""
    await session.execute(
        delete(RoleBinding).where(
            RoleBinding.principal_type == principal_type,
            RoleBinding.principal_id == principal_id,
            RoleBinding.scope_type == perms.SCOPE_GLOBAL,
        )
    )
    for role_name in dict.fromkeys(role_names):  # de-dupe, preserve order
        session.add(
            RoleBinding(
                principal_type=principal_type,
                principal_id=principal_id,
                role_name=role_name,
                scope_type=perms.SCOPE_GLOBAL,
                granted_by=granted_by,
            )
        )
    if commit:
        await session.commit()


async def global_role_names_for(
    session: AsyncSession, principal_type: str, principal_id: uuid.UUID
) -> list[str]:
    rows = await session.scalars(
        select(RoleBinding.role_name).where(
            RoleBinding.principal_type == principal_type,
            RoleBinding.principal_id == principal_id,
            RoleBinding.scope_type == perms.SCOPE_GLOBAL,
        )
    )
    return sorted(set(rows.all()))
