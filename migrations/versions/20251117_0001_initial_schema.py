"""Initial schema for Supabase-backed deployment.

Revision ID: 20251117_0001
Revises: 
Create Date: 2025-11-17 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20251117_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password", sa.String(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("modified_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "registration_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("issued_to", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_registration_keys_key", "registration_keys", ["key"], unique=True)
    op.create_index(
        "ix_registration_keys_user_id",
        "registration_keys",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "gohighlevel_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("access_token_encrypted", sa.String(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.String(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "location_id",
            name="uq_gohighlevel_account_user_location",
        ),
    )
    op.create_index(
        "ix_gohighlevel_accounts_user_id",
        "gohighlevel_accounts",
        ["user_id"],
    )

    op.create_table(
        "campaign_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("number_of_steps", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("modified_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "outreach_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("linkedin_url", sa.String(), nullable=False),
        sa.Column("linkedin_email", sa.String(), nullable=False),
        sa.Column("linkedin_password", sa.String(), nullable=False),
        sa.Column("gohighlevel_account_id", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("modified_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["gohighlevel_account_id"], ["gohighlevel_accounts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outreach_profiles_gohighlevel_account_id",
        "outreach_profiles",
        ["gohighlevel_account_id"],
    )
    op.create_index(
        "ix_outreach_profiles_linkedin_url",
        "outreach_profiles",
        ["linkedin_url"],
        unique=True,
    )

    op.create_table(
        "linkedin_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cookies", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_sessions_outreach_profile_id",
        "linkedin_sessions",
        ["outreach_profile_id"],
        unique=True,
    )

    op.create_table(
        "target_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("profile_url", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("lastname", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("about", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("connected", sa.Boolean(), nullable=True),
        sa.Column("connection_pending", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("modified_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("first_fetched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_fetched_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "outreach_profile_id",
            "profile_url",
            name="uq_target_profile_outreach_profile_url",
        ),
    )

    op.create_table(
        "campaign_lead_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("campaign_template_id", sa.Integer(), nullable=False),
        sa.Column("search_url", sa.String(), nullable=False),
        sa.Column("search_filters", sa.JSON(), nullable=True),
        sa.Column("requested_lead_count", sa.Integer(), nullable=True),
        sa.Column("total_extracted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_imported", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_template_id"], ["campaign_templates.id"]),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_campaign_lead_imports_import_id",
        "campaign_lead_imports",
        ["import_id"],
        unique=True,
    )

    op.create_table(
        "campaign_template_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_template_id", sa.Integer(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("additional_note_template", sa.String(), nullable=True),
        sa.Column("delay_timestamp", sa.Interval(), nullable=False),
        sa.Column("message_template", sa.String(), nullable=True),
        sa.Column("variables", postgresql.ARRAY(sa.String()), nullable=False),
        sa.ForeignKeyConstraint(["campaign_template_id"], ["campaign_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "campaign_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("runtime_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.Column("campaign_template_id", sa.Integer(), nullable=False),
        sa.Column("number_of_steps", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("modified_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_on_step_number", sa.Integer(), nullable=True),
        sa.Column("target_profile_responded", sa.Boolean(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_template_id"], ["campaign_templates.id"]),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "campaign_step_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_history_id", sa.Integer(), nullable=False),
        sa.Column("campaign_runtime_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("modified_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_history_id"], ["campaign_history.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "scheduled_campaign_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_history_id", sa.Integer(), nullable=True),
        sa.Column("campaign_step_history_id", sa.Integer(), nullable=True),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'scheduled'")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("executed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_history_id"], ["campaign_history.id"]),
        sa.ForeignKeyConstraint(["campaign_step_history_id"], ["campaign_step_history.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_campaign_tasks_celery_task_id",
        "scheduled_campaign_tasks",
        ["celery_task_id"],
        unique=True,
    )

    op.create_table(
        "target_contact_info",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("gohighlevel_account_id", sa.Integer(), nullable=True),
        sa.Column("raw_sections", sa.JSON(), nullable=False),
        sa.Column("normalized_data", sa.JSON(), nullable=True),
        sa.Column("primary_email", sa.String(), nullable=True),
        sa.Column("phones_json", sa.JSON(), nullable=True),
        sa.Column("urls_json", sa.JSON(), nullable=True),
        sa.Column("sync_status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("sync_error", sa.String(), nullable=True),
        sa.Column("last_synced_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_fetch_error", sa.String(), nullable=True),
        sa.Column("ghl_contact_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["gohighlevel_account_id"], ["gohighlevel_accounts.id"]),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_profile_id"),
    )
    op.create_index(
        "ix_target_contact_info_outreach_profile_id",
        "target_contact_info",
        ["outreach_profile_id"],
    )
    op.create_index(
        "ix_target_contact_info_gohighlevel_account_id",
        "target_contact_info",
        ["gohighlevel_account_id"],
    )

    op.create_table(
        "chat_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.Column("message_role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("message_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("record_created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("chat_history_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["chat_history_id"], ["chat_history.id"]),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "user_target_profiles",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "target_profile_id"),
    )

    op.create_table(
        "outreach_target_profiles",
        sa.Column("outreach_profile_id", sa.Integer(), nullable=False),
        sa.Column("target_profile_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["outreach_profile_id"], ["outreach_profiles.id"]),
        sa.ForeignKeyConstraint(["target_profile_id"], ["target_profiles.id"]),
        sa.PrimaryKeyConstraint("outreach_profile_id", "target_profile_id"),
    )


def downgrade() -> None:
    op.drop_table("outreach_target_profiles")
    op.drop_table("user_target_profiles")
    op.drop_table("actions")
    op.drop_table("chat_history")
    op.drop_index("ix_target_contact_info_gohighlevel_account_id", table_name="target_contact_info")
    op.drop_index("ix_target_contact_info_outreach_profile_id", table_name="target_contact_info")
    op.drop_table("target_contact_info")
    op.drop_index(
        "ix_scheduled_campaign_tasks_celery_task_id",
        table_name="scheduled_campaign_tasks",
    )
    op.drop_table("scheduled_campaign_tasks")
    op.drop_table("campaign_step_history")
    op.drop_table("campaign_history")
    op.drop_table("campaign_template_steps")
    op.drop_index("ix_campaign_lead_imports_import_id", table_name="campaign_lead_imports")
    op.drop_table("campaign_lead_imports")
    op.drop_table("target_profiles")
    op.drop_index("ix_linkedin_sessions_outreach_profile_id", table_name="linkedin_sessions")
    op.drop_table("linkedin_sessions")
    op.drop_index("ix_outreach_profiles_linkedin_url", table_name="outreach_profiles")
    op.drop_index("ix_outreach_profiles_gohighlevel_account_id", table_name="outreach_profiles")
    op.drop_table("outreach_profiles")
    op.drop_table("campaign_templates")
    op.drop_index("ix_gohighlevel_accounts_user_id", table_name="gohighlevel_accounts")
    op.drop_table("gohighlevel_accounts")
    op.drop_index("ix_registration_keys_user_id", table_name="registration_keys")
    op.drop_index("ix_registration_keys_key", table_name="registration_keys")
    op.drop_table("registration_keys")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

