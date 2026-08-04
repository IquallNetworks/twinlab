"""labs: layout gains per-group styling (contract delta 20)

Revision ID: 0018_lab_layout_groups
Revises: 0017_lab_layout
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_lab_layout_groups"
down_revision: str | None = "0017_lab_layout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The stored layout grows from the bare positions map ({canvas-id: {x,y}},
    # delta 19) to {"positions": ..., "groups": ...}. Every existing row was
    # written in the bare form, so wrap unconditionally; groups starts absent
    # (read as {}).
    op.execute(
        "UPDATE labs SET layout = jsonb_build_object('positions', layout) WHERE layout IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("UPDATE labs SET layout = layout->'positions' WHERE layout IS NOT NULL")
