"""ORM models for users, RBAC (roles/permissions/groups/bindings), and sessions.

RBAC v2 is scoped: a **binding** (`role_bindings`) attaches a role to a principal (a
user or a group) at a scope (global, or one lab). Authorization resolves a role's
permissions from the code catalog (`auth.permissions`); the `roles`/`permissions`
tables are seeded from that catalog for introspection. Group membership is a plain
M2M; a user's effective permissions union their own and their groups' bindings.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from twinlab_backend.db.base import Base

# Association tables carry explicit column types (their FK targets' types) so the
# columns are fully typed rather than Column[Unknown].
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

# Group membership: users belong to zero or many groups.
group_members = Table(
    "group_members",
    Base.metadata,
    Column("group_id", Uuid(), ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # The groups this user belongs to; their bindings also count toward the user's
    # effective permissions. Eager-loaded so the resolver can gather group ids.
    groups: Mapped[list[Group]] = relationship(
        secondary=group_members, lazy="selectin", back_populates="members"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")

    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)


class Group(Base):
    """An admin-defined set of users. A binding can target a group, granting its role
    to every member — so access is managed by curating membership, not re-granting."""

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list[User]] = relationship(
        secondary=group_members, lazy="selectin", back_populates="groups"
    )


class RoleBinding(Base):
    """The RBAC join: a principal (user or group) holds a role at a scope. `scope_type`
    is `global` (applies to every lab, incl. future) or `lab` (then `lab_id` names the
    one lab). `role_name` references the code catalog, not a FK, since roles are
    code-defined. `principal_id` is a user id or group id per `principal_type` — a
    polymorphic reference, so it carries no DB-level FK."""

    __tablename__ = "role_bindings"
    __table_args__ = (
        UniqueConstraint(
            "principal_type",
            "principal_id",
            "role_name",
            "scope_type",
            "lab_id",
            name="uq_role_binding",
        ),
        CheckConstraint("principal_type IN ('user','group')", name="ck_binding_principal_type"),
        CheckConstraint("scope_type IN ('global','lab')", name="ck_binding_scope_type"),
        # A lab binding names a lab; a global binding must not.
        CheckConstraint(
            "(scope_type = 'lab') = (lab_id IS NOT NULL)", name="ck_binding_scope_lab_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    principal_type: Mapped[str] = mapped_column(String(8), index=True)  # "user" | "group"
    principal_id: Mapped[uuid.UUID] = mapped_column(Uuid(), index=True)
    role_name: Mapped[str] = mapped_column(String(64))
    scope_type: Mapped[str] = mapped_column(String(8))  # "global" | "lab"
    # SET NULL would violate the scope/lab_id check, so a lab binding is removed with
    # its lab (hard removal). Soft-deleted labs keep the row (the lab row survives).
    lab_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("labs.id", ondelete="CASCADE"), default=None, index=True
    )
    # Audit: who created the grant (SET NULL so deleting that user keeps the grant).
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Lab(Base):
    """A durable lab record: the netlab definition is the source of truth and
    outlives any single deployment, so it survives destroy (status flips to
    `destroyed`, the definition is retained). Live node state is not stored here
    — it is read from clab-api on demand and merged at the read boundary.
    """

    __tablename__ = "labs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # The stable lab name injected into the definition; shared identity across
    # create/deploy/configure/destroy. Charset is clab-safe (see the API layer).
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    # The named netlab definition the lab deploys from — stored so deploy and
    # configure re-render deterministically without the caller resupplying it.
    # NULL only while the lab is a bare "created" record (not yet authored).
    definition: Mapped[str | None] = mapped_column(Text(), default=None)
    # "created" (record only) | "deploying" (in-flight mutex) | "deployed" |
    # "destroyed" (torn down, redeployable).
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
    # The twinlab user who first created the lab — immutable creation audit. SET
    # NULL (not CASCADE): deleting a user must not erase the durable definition they
    # authored.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # The lab's current owner: authoritative for ownership (display + transfer). The
    # owner implicitly holds the full lab_owner permission set on this lab, so they
    # can never revoke themselves. Distinct from created_by, which never changes;
    # owner_id moves on transfer. Backfilled from created_by for pre-v2 rows.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Soft-delete marker. NULL means active; a timestamp means the lab was deleted
    # from the catalog (torn down and hidden from list/detail) but the row is kept
    # for audit. Deletion RELEASES the mgmt subnet (set NULL, contract delta 11);
    # a plain `destroyed` lab keeps its subnet so a redeploy reproduces the same
    # environment.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Two FKs point at users (created_by + owner_id), so the relationship must name
    # which one it follows. `owner` tracks owner_id (the authoritative owner).
    owner: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[owner_id])


class Job(Base):
    """One async lab operation (deploy/configure/destroy/suite run). The row IS
    the API's job resource: submitted params echoed in `request`, the terminal
    payload in `result` (succeeded) or the error envelope in `error` (failed).
    Rows outlive the in-process task — a restart sweep fails any orphaned
    `running` row — and are pruned to recent history per lab."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('deploy','configure','destroy','suite_run')", name="ck_jobs_kind"
        ),
        CheckConstraint("status IN ('running','succeeded','failed')", name="ck_jobs_status"),
        # THE one-running-job-per-lab mutex: a concurrent submit loses this
        # partial unique index at INSERT and maps to 409 job_in_flight.
        Index(
            "uq_jobs_one_running_per_lab",
            "lab_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    # CASCADE is safe: labs are soft-deleted (the row survives), so a hard
    # delete only happens via out-of-band DB surgery — jobs go with it.
    lab_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("labs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    # The submitted parameters, echoed verbatim (history/display data). A deploy
    # job also stashes the lab's pre-deploy status here (`previous_status`) so a
    # failure — or the restart sweep — can restore it.
    request: Mapped[dict[str, object]] = mapped_column(JSONB())
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB(), default=None)
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB(), default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ApiKey(Base):
    """A long-lived Bearer credential acting as its creating user (automation:
    CI, the black-box suite). Only the sha256 of the secret is stored; the raw
    key is shown once at creation. Revocation deletes the row; a deactivated or
    deleted user's keys stop working (is_active check on resolve + CASCADE)."""

    __tablename__ = "api_keys"
    # Names are per-user labels ("ci"); two users may both have a "ci" key.
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_api_key_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # sha256 hex of the raw key; deterministic so the Bearer lookup is by hash.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped[User] = relationship(lazy="selectin")


class SshKey(Base):
    """A user's registered SSH public key — their credential at the stack's
    jump host. Nothing secret is stored (it IS the public half). The
    fingerprint is globally unique: sshd's key lookup carries only the
    fingerprint, so a key must identify exactly one person. User deletion
    cascades; a deactivated user's keys stop authorizing (is_active check in
    the resolver)."""

    __tablename__ = "ssh_keys"
    # Names are per-user labels ("laptop"); two users may both have one.
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_ssh_key_user_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    algorithm: Mapped[str] = mapped_column(String(64))
    # Canonical base64 of the key blob — exactly what sshd must be handed back
    # in the authorized_keys answer for authentication to succeed.
    key_b64: Mapped[str] = mapped_column(Text())
    comment: Mapped[str | None] = mapped_column(String(255), default=None)
    # "SHA256:<unpadded base64>" — sshd's %f token verbatim; the jump lookup key.
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Stamped whenever the key is OFFERED at the jump (sshd looks it up).
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped[User] = relationship(lazy="selectin")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # sha256 hex of the opaque token; the raw token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(lazy="selectin")
