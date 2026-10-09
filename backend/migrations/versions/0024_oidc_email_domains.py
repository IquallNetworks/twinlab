"""oidc_providers: the email domains a provider may tie or create for (delta 35)

Revision ID: 0024_oidc_email_domains
Revises: 0023_oidc
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0024_oidc_email_domains"
down_revision: str | None = "0023_oidc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # '[]' is "any domain", so every existing provider keeps behaving exactly
    # as it did before the setting existed.
    op.add_column(
        "oidc_providers",
        sa.Column(
            "allowed_email_domains",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("oidc_providers", "allowed_email_domains")
