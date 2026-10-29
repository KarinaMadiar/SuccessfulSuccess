"""add ai_suggestion JSONB column to meetings

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meetings",
        sa.Column("ai_suggestion", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("meetings", "ai_suggestion")
