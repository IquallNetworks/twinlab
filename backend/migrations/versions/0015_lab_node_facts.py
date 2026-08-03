"""labs: the per-node fact namespace cache (contract delta 17)

Revision ID: 0015_lab_node_facts
Revises: 0014_lab_host_bridges
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015_lab_node_facts"
down_revision: str | None = "0014_lab_host_bridges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A derived, regenerable cache like `links` (0013): netlab's raw per-node
    # dicts from the expanded topology — the namespace test-suite templates
    # render against. NULL = not yet generated; GET /labs/{name}/facts lazily
    # regenerates and persists, so no data backfill here.
    op.add_column("labs", sa.Column("node_facts", JSONB(), nullable=True))
    # Test-suites v2 (delta 17) replaced the stored suite schema. The
    # user-decided migration strategy is NO data migration — the project is in
    # dev phase with no real-world suites — so v1 rows are cleared instead of
    # converted (a v1 suite no longer parses; leaving it would 500 the reads).
    op.execute(
        "UPDATE labs SET test_suites = NULL, last_validation = NULL, config_time_ok = NULL"
        " WHERE test_suites IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("labs", "node_facts")
