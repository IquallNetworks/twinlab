"""labs: the shared manual topology layout (contract delta 19)

Revision ID: 0017_lab_layout
Revises: 0016_lab_deployed_definition
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0017_lab_layout"
down_revision: str | None = "0016_lab_deployed_definition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One manual topology arrangement per lab ({canvas-id: {x, y}}), shared
    # across users — replaces the frontend's per-browser localStorage. NULL =
    # never saved; no backfill (browser-local layouts are not reachable here).
    op.add_column("labs", sa.Column("layout", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "layout")
