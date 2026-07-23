"""Idempotent startup seeding: permissions, roles, and the bootstrap admin.

Runs in the app lifespan (after migrations). Keeps the code-defined RBAC in sync
with the database and guarantees at least one admin exists, so the system is
never left open-by-default.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from twinlab_backend.auth import permissions as perms
from twinlab_backend.auth.passwords import hash_password
from twinlab_backend.db.models import Permission, Role, User


async def seed_rbac(session: AsyncSession) -> None:
    """Ensure every code-defined permission and role exists and each role is
    wired to its permissions. Idempotent."""
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


async def ensure_admin(session: AsyncSession, username: str, password: str) -> None:
    """Create the bootstrap admin, but only when there are no users yet."""
    user_count = await session.scalar(select(func.count()).select_from(User))
    if user_count:
        return

    admin_role = await session.scalar(select(Role).where(Role.name == perms.ADMIN_ROLE))
    if admin_role is None:
        raise RuntimeError("admin role missing; seed_rbac must run before ensure_admin")

    admin = User(username=username, password_hash=hash_password(password))
    admin.roles = [admin_role]
    session.add(admin)
    await session.commit()
