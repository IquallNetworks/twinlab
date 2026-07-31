"""labs: the host-bridge claim (hostprep)

Revision ID: 0014_lab_host_bridges
Revises: 0013_lab_links
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014_lab_host_bridges"
down_revision: str | None = "0013_lab_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The host bridges a deploy created via the hostprep sidecar (a JSON array
    # of names): the lab's claim on host state, used for destroy-time cleanup
    # and the cross-lab bridge-name collision check. NULL = none claimed; no
    # backfill — labs deployed before the feature could not have LAN links (the
    # deploy would have failed on the missing bridge).
    op.add_column("labs", sa.Column("host_bridges", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("labs", "host_bridges")
