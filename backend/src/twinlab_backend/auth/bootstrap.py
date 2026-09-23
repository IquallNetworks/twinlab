"""Idempotent startup seeding: permissions, roles, and the bootstrap admin.

Runs in the app lifespan (after migrations). Keeps the code-defined RBAC catalog in
sync with the DB introspection tables and guarantees at least one admin exists, so
the system is never left open-by-default. Authorization itself resolves from the code
catalog (`auth.permissions`); these tables exist so roles/permissions can be listed.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.passwords import hash_password
from twinlab_backend.db.models import Permission, Role, RoleBinding, User


async def seed_rbac(session: AsyncSession) -> None:
    """Ensure every code-defined permission and role exists and each role is wired to
    its permissions. Idempotent."""
    by_name = {p.name: p for p in (await session.scalars(select(Permission))).all()}
    for name in perms.ALL_PERMISSIONS:
        if name not in by_name:
            created = Permission(name=name)
            session.add(created)
            by_name[name] = created
    await session.flush()

    roles = {r.name: r for r in (await session.scalars(select(Role))).all()}
    for role_name, granted in perms.ROLE_DEFINITIONS.items():
        role = roles.get(role_name)
        if role is None:
            role = Role(name=role_name)
            session.add(role)
        role.permissions = [by_name[n] for n in granted]
    await session.commit()


async def ensure_admin(session: AsyncSession, username: str, password: str, email: str) -> None:
    """Create the bootstrap admin (with a global `admin` binding), but only when there
    are no users yet. Its display name is its username: it is the break-glass
    account, and a second required variable for it would buy nothing."""
    user_count = await session.scalar(select(func.count()).select_from(User))
    if user_count:
        return

    admin = User(
        username=username,
        email=email,
        display_name=username,
        password_hash=hash_password(password),
    )
    session.add(admin)
    await session.flush()  # assign admin.id before the binding references it
    session.add(
        RoleBinding(
            principal_type=perms.PRINCIPAL_USER,
            principal_id=admin.id,
            role_name=perms.ADMIN_ROLE,
            scope_type=perms.SCOPE_GLOBAL,
        )
    )
    await session.commit()
