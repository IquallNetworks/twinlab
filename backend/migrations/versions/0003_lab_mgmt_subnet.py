"""labs: per-lab management subnet

Revision ID: 0003_lab_mgmt_subnet
Revises: 0002_labs
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_lab_mgmt_subnet"
down_revision: str | None = "0002_labs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: existing rows have no assigned subnet; new deploys populate it.
    op.add_column("labs", sa.Column("mgmt_subnet", sa.String(18), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "mgmt_subnet")
