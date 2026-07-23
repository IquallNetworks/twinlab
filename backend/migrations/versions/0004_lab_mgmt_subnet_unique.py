"""labs: unique management subnet

Revision ID: 0004_lab_mgmt_subnet_unique
Revises: 0003_lab_mgmt_subnet
Create Date: 2026-07-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_lab_mgmt_subnet_unique"
down_revision: str | None = "0003_lab_mgmt_subnet"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Reserve each mgmt subnet atomically: two concurrent deploys can't both
    # commit the same /24. Postgres allows many NULLs under a unique index, so
    # pre-feature rows (NULL subnet) are unaffected.
    op.create_index("uq_labs_mgmt_subnet", "labs", ["mgmt_subnet"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_labs_mgmt_subnet", table_name="labs")
