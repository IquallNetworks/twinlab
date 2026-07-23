"""ORM models for users, RBAC (roles/permissions), and login sessions.

Roles and permissions are stored as data (assignable per user at runtime), but
the set of permission names is defined in code — see `auth.permissions`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twinlab_backend.db.base import Base

# Association tables carry explicit column types (their FK targets' types) so the
# columns are fully typed rather than Column[Unknown].
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer(), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer(), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        Integer(),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    roles: Mapped[list["Role"]] = relationship(secondary=user_roles, lazy="selectin")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")

    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)


class Lab(Base):
    """A durable lab record: the netlab definition is the source of truth and
    outlives any single deployment, so it survives destroy (status flips to
    `destroyed`, the definition is retained). Live node state is not stored here
    — it is read from clab-api on demand and merged at the read boundary.
    """

    __tablename__ = "labs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The stable lab name injected into the definition; shared identity across
    # create/deploy/configure/destroy. Charset is clab-safe (see the API layer).
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # The named netlab definition the lab was deployed from — stored so configure
    # can re-render deterministically without the caller resupplying it.
    definition: Mapped[str] = mapped_column(Text())
    # "deployed" | "destroyed". "stored" (saved but never deployed) is reserved
    # for a future save-only flow; today's flows only produce the first two.
    status: Mapped[str] = mapped_column(String(16))
    # The twinlab user who created the lab. SET NULL (not CASCADE): deleting a
    # user must not erase the durable definition they authored.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User | None"] = relationship(lazy="selectin")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # sha256 hex of the opaque token; the raw token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(lazy="selectin")
