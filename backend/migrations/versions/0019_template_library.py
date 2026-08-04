"""Template library (contract delta 21): lab publication + node templates.

Labs gain the publication toggle state (a published lab's stored definition is
served live as a user-tier network template; the description is the library
card). `node_templates` holds the user-tier node fragments. No backfill:
nothing was published before the feature existed.

Revision ID: 0019_template_library
Revises: 0018_lab_layout_groups
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_template_library"
down_revision: str | None = "0018_lab_layout_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "labs",
        sa.Column(
            "template_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("labs", sa.Column("template_description", sa.String(255), nullable=True))
    op.create_table(
        "node_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=False),
        sa.Column("device", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_node_templates_name", "node_templates", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_node_templates_name", table_name="node_templates")
    op.drop_table("node_templates")
    op.drop_column("labs", "template_description")
    op.drop_column("labs", "template_published")
