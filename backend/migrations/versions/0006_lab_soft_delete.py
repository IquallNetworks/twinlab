"""labs: soft-delete marker

Revision ID: 0006_lab_soft_delete
Revises: 0005_lab_test_suites
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_lab_soft_delete"
down_revision: str | None = "0005_lab_test_suites"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: existing labs are active (NULL). A timestamp marks a lab deleted
    # from the catalog while keeping its row (definition + reserved mgmt subnet).
    op.add_column("labs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "deleted_at")
