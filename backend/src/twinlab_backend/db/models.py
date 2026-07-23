"""ORM models for users, RBAC (roles/permissions), and login sessions.

Roles and permissions are stored as data (assignable per user at runtime), but
the set of permission names is defined in code — see `auth.permissions`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    # The management /24 assigned to this lab (e.g. "10.77.3.0/24"), baked into
    # the stored definition. Kept per-record so allocation avoids it for the
    # lab's whole lifetime. Nullable: rows predating the feature, and labs never
    # given one, carry NULL (Postgres allows many NULLs under a unique index).
    # UNIQUE so a subnet is reserved atomically: concurrent deploys that pick the
    # same /24 can't both commit — the loser retries with the next free one.
    mgmt_subnet: Mapped[str | None] = mapped_column(String(18), unique=True, default=None)
    # Declarative test suites (the source of truth for what validation runs),
    # stored as JSON — the serialized `dict[str, TestSuite]`. Never sent to
    # `netlab create`, so it can't trip netlab's topology attribute validation.
    # NULL means the lab has no suites.
    test_suites: Mapped[dict[str, object] | None] = mapped_column(JSONB(), default=None)
    # The last run of each suite, keyed by suite name (serialized SuiteReport), so
    # the UI can show each suite's standing without re-running. NULL until first run.
    last_validation: Mapped[dict[str, object] | None] = mapped_column(JSONB(), default=None)
    # The config-time validation gate from the most recent configure: NULL (not run
    # / skipped / no config-time suites), True (passed), False (failed). An explicit
    # flag so a lab whose config-time checks failed is unambiguous in a listing.
    config_time_ok: Mapped[bool | None] = mapped_column(Boolean(), default=None)
    # User-authored netlab custom-config templates: a {relpath: content} fileset
    # (e.g. {"nat/ios.j2": "..."}), shipped to the runner alongside the built-in
    # library on every configure. Built-ins live in code, not here. Never sent to
    # `netlab create`. NULL means the lab has no user templates.
    custom_config: Mapped[dict[str, object] | None] = mapped_column(JSONB(), default=None)
    # The twinlab user who created the lab. SET NULL (not CASCADE): deleting a
    # user must not erase the durable definition they authored.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Soft-delete marker. NULL means active; a timestamp means the lab was deleted
    # from the catalog (torn down and hidden from list/detail) but the row is kept
    # — the definition is retained for audit, and the mgmt subnet stays reserved so
    # it isn't handed to a new lab. Distinct from `destroyed` (a lifecycle status: a
    # still-listed lab that can be redeployed).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

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
