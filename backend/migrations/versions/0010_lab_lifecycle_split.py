"""Lifecycle split: a lab record exists before it has a definition.

`labs.definition` becomes nullable — NULL only while the lab is a bare
"created" record (POST /labs is now create-only; authoring and deploying are
separate verbs). No data changes: existing rows all carry definitions and
valid statuses.

Revision ID: 0010_lab_lifecycle_split
Revises: 0009_api_keys
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_lab_lifecycle_split"
down_revision: str | None = "0009_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("labs", "definition", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM labs WHERE definition IS NULL")
    op.alter_column("labs", "definition", existing_type=sa.Text(), nullable=False)
