"""LinkedIn verification + scrape event tables.

Revision ID: 20251117_0002
Revises: 20251117_0001
Create Date: 2025-11-17 12:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20251117_0002"
down_revision = "20251117_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "linkedin_login_code_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=True),
        sa.Column("campaign_history_id", sa.Integer(), nullable=True),
        sa.Column("request_type", sa.String(), nullable=False, server_default=sa.text("'login'")),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("status_detail", sa.String(), nullable=True),
        sa.Column("pending_reason", sa.String(), nullable=True),
        sa.Column("two_captcha_job_id", sa.String(), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("last_status_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_history_id"], ["campaign_history.id"]),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_login_code_requests_outreach_profile_id",
        "linkedin_login_code_requests",
        ["outreach_profile_id"],
    )
    op.create_index(
        "ix_linkedin_login_code_requests_target_profile_id",
        "linkedin_login_code_requests",
        ["target_profile_id"],
    )
    op.create_index(
        "ix_linkedin_login_code_requests_status",
        "linkedin_login_code_requests",
        ["status"],
    )
    op.create_index(
        "uq_login_code_request_outreach_pending",
        "linkedin_login_code_requests",
        ["outreach_profile_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "linkedin_verification_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by", sa.String(), nullable=True),
        sa.Column("submitted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("code_value", sa.String(), nullable=True),
        sa.Column("two_captcha_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("result", sa.String(), nullable=True),
        sa.Column("error_details", sa.String(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("submitted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("processed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["request_id"], ["linkedin_login_code_requests.id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_verification_attempts_request_id",
        "linkedin_verification_attempts",
        ["request_id"],
    )

    op.create_table(
        "linkedin_scrape_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=True),
        sa.Column("campaign_history_id", sa.Integer(), nullable=True),
        sa.Column("login_code_request_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("action_taken", sa.String(), nullable=True),
        sa.Column("two_captcha_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata_json", sa.JSON(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_history_id"], ["campaign_history.id"]),
        sa.ForeignKeyConstraint(["login_code_request_id"], ["linkedin_login_code_requests.id"]),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_scrape_events_outreach_profile_id",
        "linkedin_scrape_events",
        ["outreach_profile_id"],
    )
    op.create_index(
        "ix_linkedin_scrape_events_created_at",
        "linkedin_scrape_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_linkedin_scrape_events_created_at", table_name="linkedin_scrape_events")
    op.drop_index("ix_linkedin_scrape_events_outreach_profile_id", table_name="linkedin_scrape_events")
    op.drop_table("linkedin_scrape_events")
    op.drop_index("ix_linkedin_verification_attempts_request_id", table_name="linkedin_verification_attempts")
    op.drop_table("linkedin_verification_attempts")
    op.drop_index("uq_login_code_request_outreach_pending", table_name="linkedin_login_code_requests")
    op.drop_index("ix_linkedin_login_code_requests_status", table_name="linkedin_login_code_requests")
    op.drop_index(
        "ix_linkedin_login_code_requests_target_profile_id",
        table_name="linkedin_login_code_requests",
    )
    op.drop_index(
        "ix_linkedin_login_code_requests_outreach_profile_id",
        table_name="linkedin_login_code_requests",
    )
    op.drop_table("linkedin_login_code_requests")




