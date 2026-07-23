"""labs: test suites, last validation, config-time gate

Revision ID: 0005_lab_test_suites
Revises: 0004_lab_mgmt_subnet_unique
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0005_lab_test_suites"
down_revision: str | None = "0004_lab_mgmt_subnet_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All nullable: existing labs have no suites, no runs, and no config-time
    # verdict. test_suites/last_validation hold serialized pydantic data; JSONB so
    # a report can be inspected in the DB if needed.
    op.add_column("labs", sa.Column("test_suites", JSONB(), nullable=True))
    op.add_column("labs", sa.Column("last_validation", JSONB(), nullable=True))
    op.add_column("labs", sa.Column("config_time_ok", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "config_time_ok")
    op.drop_column("labs", "last_validation")
    op.drop_column("labs", "test_suites")
