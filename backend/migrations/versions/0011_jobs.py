"""Async lab jobs: the four long operations (deploy/configure/destroy/suite
run) persist as `jobs` rows. The partial unique index on (lab_id) WHERE
status='running' IS the one-running-job-per-lab mutex — a concurrent submit
loses the INSERT and maps to 409.

Revision ID: 0011_jobs
Revises: 0010_lab_lifecycle_split
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011_jobs"
down_revision: str | None = "0010_lab_lifecycle_split"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "lab_id", sa.Uuid(), sa.ForeignKey("labs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("request", JSONB(), nullable=False),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("error", JSONB(), nullable=True),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('deploy','configure','destroy','suite_run')", name="ck_jobs_kind"
        ),
        sa.CheckConstraint("status IN ('running','succeeded','failed')", name="ck_jobs_status"),
    )
    op.create_index("ix_jobs_lab_id", "jobs", ["lab_id"])
    op.create_index(
        "uq_jobs_one_running_per_lab",
        "jobs",
        ["lab_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_one_running_per_lab", table_name="jobs")
    op.drop_index("ix_jobs_lab_id", table_name="jobs")
    op.drop_table("jobs")
