"""jobs: the step log (contract delta 29)

Revision ID: 0021_job_steps
Revises: 0020_custom_config_records
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0021_job_steps"
down_revision: str | None = "0020_custom_config_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # What the operation did, appended as it ran. NOT NULL with a '[]' default
    # so the append (`steps = steps || …`) never has to handle a null, and so a
    # job that predates the column reads as the empty list — honest: it has no
    # steps and none can be invented for it.
    op.add_column(
        "jobs",
        sa.Column("steps", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("jobs", "steps")
