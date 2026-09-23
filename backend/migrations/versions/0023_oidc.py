"""users gain email + display name; OIDC providers and identities (contract delta 33)

Revision ID: 0023_oidc
Revises: 0022_lab_node_groups
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0023_oidc"
down_revision: str | None = "0022_lab_node_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every user now carries an email and a display name. Existing rows are
    # backfilled rather than failing the upgrade: the display name is the
    # username, and the email a placeholder under the RFC 2606 `.invalid` TLD,
    # which no provider can ever verify — so a backfilled account can never be
    # the target of an OIDC tie. The admin UI flags these for a real address.
    # Two usernames differing only in case would collide on the unique index
    # below; that fails the upgrade LOUDLY, which is the right outcome for a
    # case no stack is known to have.
    op.add_column("users", sa.Column("display_name", sa.String(128), nullable=True))
    op.execute("UPDATE users SET display_name = username WHERE display_name IS NULL")
    op.execute("UPDATE users SET email = username || '@users.invalid' WHERE email IS NULL")
    op.alter_column("users", "display_name", nullable=False)
    op.alter_column("users", "email", nullable=False)
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "oidc_providers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False, unique=True),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("scopes", JSONB(), nullable=False),
        sa.Column("allow_create_users", sa.Boolean(), nullable=False),
        sa.Column("allow_email_tying", sa.Boolean(), nullable=False),
        sa.Column("trust_email", sa.Boolean(), nullable=False),
        sa.Column(
            "default_group_id",
            sa.Uuid(),
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("icon", sa.LargeBinary(), nullable=True),
        sa.Column("icon_type", sa.String(32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_oidc_providers_name", "oidc_providers", ["name"], unique=True)

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "provider_id",
            sa.Uuid(),
            sa.ForeignKey("oidc_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email_at_link", sa.String(320), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider_id", "subject", name="uq_identity_provider_subject"),
        sa.UniqueConstraint("user_id", "provider_id", name="uq_identity_user_provider"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    op.create_index("ix_user_identities_provider_id", "user_identities", ["provider_id"])

    op.create_table(
        "oidc_login_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column(
            "provider_id",
            sa.Uuid(),
            sa.ForeignKey("oidc_providers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("next_path", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_oidc_login_attempts_state_hash", "oidc_login_attempts", ["state_hash"], unique=True
    )
    op.create_index("ix_oidc_login_attempts_expires_at", "oidc_login_attempts", ["expires_at"])


def downgrade() -> None:
    op.drop_table("oidc_login_attempts")
    op.drop_table("user_identities")
    op.drop_index("ix_oidc_providers_name", table_name="oidc_providers")
    op.drop_table("oidc_providers")
    op.drop_index("uq_users_email_lower", table_name="users")
    # The backfilled placeholders are not distinguishable from real addresses
    # an admin later entered, so emails are kept; only the constraint relaxes.
    op.alter_column("users", "email", nullable=True)
    op.drop_column("users", "display_name")
