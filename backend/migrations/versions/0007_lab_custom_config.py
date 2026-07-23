"""labs: user-defined custom-config templates

Revision ID: 0007_lab_custom_config
Revises: 0006_lab_soft_delete
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0007_lab_custom_config"
down_revision: str | None = "0006_lab_soft_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: existing labs have no user templates. Holds a {relpath: content}
    # fileset of user-authored netlab custom-config templates (built-ins are
    # shipped in code, not stored here). JSONB so it can be inspected in the DB.
    op.add_column("labs", sa.Column("custom_config", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "custom_config")
