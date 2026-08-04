"""labs: the deployed-definition snapshot (contract delta 19)

Revision ID: 0016_lab_deployed_definition
Revises: 0015_lab_node_facts
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_lab_deployed_definition"
down_revision: str | None = "0015_lab_node_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The definition of the last successful deploy, written by the deploy job
    # and cleared on destroy. No backfill: a lab deployed before this column
    # existed has no record of what was deployed, so its drift flag honestly
    # reads unknown (NULL) until the next deploy snapshots it.
    op.add_column("labs", sa.Column("deployed_definition", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "deployed_definition")
