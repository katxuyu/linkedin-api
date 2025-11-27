"""add gohighlevel_location_id to outreach_profiles

Revision ID: f3b5e8b16f2d
Revises: 20251118_201154
Create Date: 2025-11-20 19:53:50.216548
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "f3b5e8b16f2d"
down_revision = "20251118_201154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    column_name = "gohighlevel_location_id"
    columns = {col["name"] for col in inspector.get_columns("outreach_profiles")}
    if column_name not in columns:
        op.add_column(
            "outreach_profiles",
            sa.Column(column_name, sa.String(), nullable=True),
        )

    index_name = op.f("ix_outreach_profiles_gohighlevel_location_id")
    indexes = {idx["name"] for idx in inspector.get_indexes("outreach_profiles")}
    if index_name not in indexes:
        op.create_index(
            index_name,
            "outreach_profiles",
            [column_name],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    index_name = op.f("ix_outreach_profiles_gohighlevel_location_id")
    indexes = {idx["name"] for idx in inspector.get_indexes("outreach_profiles")}
    if index_name in indexes:
        op.drop_index(
            index_name,
            table_name="outreach_profiles",
        )

    column_name = "gohighlevel_location_id"
    columns = {col["name"] for col in inspector.get_columns("outreach_profiles")}
    if column_name in columns:
        op.drop_column("outreach_profiles", column_name)

