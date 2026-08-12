"""labs: the resolved group map (contract delta 32)

Revision ID: 0022_lab_node_groups
Revises: 0021_job_steps
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0022_lab_node_groups"
down_revision: str | None = "0021_job_steps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The definition's groups with members resolved by netlab's own expansion —
    # what a test's `groups:` target selects. NULLABLE, like `links` and
    # `node_facts` beside it: this is a regenerable cache, and NULL means "not
    # generated yet" rather than "no groups", which the lazy backfill needs to
    # tell apart from a definition that genuinely declares none.
    op.add_column("labs", sa.Column("node_groups", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "node_groups")
