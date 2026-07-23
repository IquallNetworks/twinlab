"""labs: durable lab records (definition + status)

Revision ID: 0002_labs
Revises: 0001_initial
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_labs"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "labs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        # SET NULL: deleting a user must not erase the durable definition.
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_labs_name", "labs", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_labs_name", table_name="labs")
    op.drop_table("labs")
