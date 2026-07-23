"""RBAC v2: scoped role bindings, groups, and lab ownership

Introduces the scoped-authorization model: `groups` + `group_members` (users belong
to zero or many groups), `role_bindings` (a principal — user or group — holds a role
at a scope: global, or one lab), and `labs.owner_id` (the authoritative, transferable
owner, distinct from the immutable `created_by`). Backfills owner_id from created_by
and converts every existing global role assignment (`user_roles`) into a global
binding, then drops `user_roles`.

Revision ID: 0008_rbac_scoped_bindings
Revises: 0007_lab_custom_config
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_rbac_scoped_bindings"
down_revision: str | None = "0007_lab_custom_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Lab ownership: authoritative, transferable, distinct from created_by. ---
    op.add_column(
        "labs", sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"))
    )
    # Pre-v2 rows: the creator is the owner.
    op.execute("UPDATE labs SET owner_id = created_by")

    # --- Groups + membership. ---
    op.create_table(
        "groups",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_groups_name", "groups", ["name"], unique=True)

    op.create_table(
        "group_members",
        sa.Column(
            "group_id", sa.Uuid(), sa.ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
    )

    # --- Role bindings. ---
    op.create_table(
        "role_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("principal_type", sa.String(8), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("role_name", sa.String(64), nullable=False),
        sa.Column("scope_type", sa.String(8), nullable=False),
        sa.Column("lab_id", sa.Uuid(), sa.ForeignKey("labs.id", ondelete="CASCADE"), nullable=True),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "principal_type",
            "principal_id",
            "role_name",
            "scope_type",
            "lab_id",
            name="uq_role_binding",
        ),
        sa.CheckConstraint("principal_type IN ('user','group')", name="ck_binding_principal_type"),
        sa.CheckConstraint("scope_type IN ('global','lab')", name="ck_binding_scope_type"),
        sa.CheckConstraint(
            "(scope_type = 'lab') = (lab_id IS NOT NULL)", name="ck_binding_scope_lab_id"
        ),
    )
    op.create_index("ix_role_bindings_principal_type", "role_bindings", ["principal_type"])
    op.create_index("ix_role_bindings_principal_id", "role_bindings", ["principal_id"])
    op.create_index("ix_role_bindings_lab_id", "role_bindings", ["lab_id"])

    # Convert every existing global role assignment into a global user binding, then
    # retire user_roles (bindings are the one uniform mechanism from here on).
    op.execute(
        """
        INSERT INTO role_bindings
            (id, principal_type, principal_id, role_name, scope_type, lab_id, granted_at)
        SELECT gen_random_uuid(), 'user', ur.user_id, r.name, 'global', NULL, now()
        FROM user_roles ur
        JOIN roles r ON r.id = ur.role_id
        """
    )
    op.drop_table("user_roles")


def downgrade() -> None:
    op.create_table(
        "user_roles",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    # Restore global user assignments from bindings (lab-scoped bindings are dropped).
    op.execute(
        """
        INSERT INTO user_roles (user_id, role_id)
        SELECT rb.principal_id, r.id
        FROM role_bindings rb
        JOIN roles r ON r.name = rb.role_name
        WHERE rb.principal_type = 'user' AND rb.scope_type = 'global'
        ON CONFLICT DO NOTHING
        """
    )
    op.drop_index("ix_role_bindings_lab_id", table_name="role_bindings")
    op.drop_index("ix_role_bindings_principal_id", table_name="role_bindings")
    op.drop_index("ix_role_bindings_principal_type", table_name="role_bindings")
    op.drop_table("role_bindings")
    op.drop_table("group_members")
    op.drop_index("ix_groups_name", table_name="groups")
    op.drop_table("groups")
    op.drop_column("labs", "owner_id")
