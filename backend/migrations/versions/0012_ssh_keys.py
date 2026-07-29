"""Registered SSH public keys: the user's credential at the stack's jump host.

Nothing secret is stored (it is the public half). Fingerprints are globally
unique — sshd's lookup carries only the fingerprint, so a key must identify
exactly one person. Names are per-user labels; user deletion cascades.

Revision ID: 0012_ssh_keys
Revises: 0011_jobs
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_ssh_keys"
down_revision: str | None = "0011_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ssh_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=False),
        sa.Column("key_b64", sa.Text(), nullable=False),
        sa.Column("comment", sa.String(255), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_ssh_key_user_name"),
    )
    op.create_index("ix_ssh_keys_user_id", "ssh_keys", ["user_id"])
    op.create_index("ix_ssh_keys_fingerprint", "ssh_keys", ["fingerprint"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_ssh_keys_fingerprint", table_name="ssh_keys")
    op.drop_index("ix_ssh_keys_user_id", table_name="ssh_keys")
    op.drop_table("ssh_keys")
