"""labs: the derived link table (contract delta 14)

Revision ID: 0013_lab_links
Revises: 0012_ssh_keys
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0013_lab_links"
down_revision: str | None = "0012_ssh_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A derived, regenerable cache: the logical link table extracted from the
    # same `netlab create` that validates the stored definition ({"links":
    # [TopologyLink, ...]}). NULL = not yet generated (rows predating the
    # feature); GET /labs/{name}/links lazily regenerates and persists, so no
    # data backfill here.
    op.add_column("labs", sa.Column("links", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "links")
