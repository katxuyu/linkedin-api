"""add account_name to outreach_profiles

Revision ID: 20251118_201154
Revises: 20251117_0002
Create Date: 2025-11-18 20:11:54
"""

from alembic import op
import sqlalchemy as sa


revision = "20251118_201154"
down_revision = "20251117_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outreach_profiles",
        sa.Column("account_name", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("outreach_profiles", "account_name")

