import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    JSON,
    ForeignKey,
    Table,
    Interval,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

# Many-to-many: User ↔ TargetLinkedInProfile
user_target_profiles = Table(
    "user_target_profiles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("target_profile_id", Integer, ForeignKey("target_profiles.id"), primary_key=True)
)

# Many-to-many: OutreachLinkedInProfile ↔ TargetLinkedInProfile
outreach_target_profiles = Table(
    "outreach_target_profiles",
    Base.metadata,
    Column("outreach_profile_id", Integer, ForeignKey("outreach_profiles.id"), primary_key=True),
    Column("target_profile_id", Integer, ForeignKey("target_profiles.id"), primary_key=True)
)


class RegistrationKey(Base):
    __tablename__ = "registration_keys"

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True, nullable=False)
    used = Column(Boolean, default=False)
    issued_to = Column(Integer, nullable=True)  # optional metadata
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    expires_at = Column(TIMESTAMP(timezone=True), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True)

    # Relationships
    user = relationship("User", back_populates="registration_key") # one user-one key

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True),
        #DateTime,
        default=lambda: datetime.now(timezone.utc)
    )
    modified_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    outreach_profiles = relationship("OutreachLinkedInProfile", back_populates="user") # one user-many outreach profiles (user can have multiple LinkedIn accounts)
    # target_profiles = relationship(
    #     "TargetLinkedInProfile",
    #     secondary=user_target_profiles,
    #     back_populates="users"
    # ) # many users-many target profiles (multiple users can share same target profile)
    linkedin_sessions = relationship("LinkedInSession", back_populates="user") # one user-many sessions (user can have multiple LinkedIn sessions)
    actions = relationship("Action", back_populates="user") # one user-many actions
    registration_key = relationship("RegistrationKey", back_populates="user") # one user-one key
    campaign_templates = relationship("CampaignTemplate", back_populates="user") # one user-many campaign templates
    campaign_histories = relationship("CampaignHistory", back_populates="user") # one user-many campaign history records
    gohighlevel_accounts = relationship("GoHighLevelAccount", back_populates="user")  # one user-many GHL accounts
    verification_attempts = relationship("LinkedInVerificationAttempt", back_populates="submitted_by_user")
    # chat_history = relationship("ChatHistory", back_populates="user") # one user-many chat history records
    lead_imports = relationship("CampaignLeadImport", back_populates="user") # one user-many lead imports


class OutreachLinkedInProfile(Base):
    __tablename__ = "outreach_profiles"
    __table_args__ = (
        UniqueConstraint('user_id', 'linkedin_url', name='uq_user_linkedin_url'),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    linkedin_url = Column(String, nullable=False)
    linkedin_email = Column(String, nullable=False)
    linkedin_password = Column(String, nullable=False)
    account_name = Column(String, nullable=True)
    gohighlevel_location_id = Column(String, nullable=True, index=True)
    added_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    modified_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = relationship("User", back_populates="outreach_profiles") # one user-many outreach profiles
    target_profiles = relationship(
        "TargetLinkedInProfile",
        secondary=outreach_target_profiles,
        back_populates="outreach_profiles"
    ) # many outreach profiles-many target profiles (multiple LinkedIn accounts can share same target profile)
    actions = relationship("Action", back_populates="outreach_profile") # one outreach profile-many actions
    chat_histories = relationship("ChatHistory", back_populates="outreach_profile") # one outreach profile-many chat history records
    linkedin_session = relationship("LinkedInSession", back_populates="outreach_profile", uselist=False) # one outreach profile-one session
    campaign_histories = relationship("CampaignHistory", back_populates="outreach_profile") # one outreach profile-many campaign history records
    lead_imports = relationship("CampaignLeadImport", back_populates="outreach_profile") # one outreach profile-many lead imports
    # gohighlevel_account = relationship("GoHighLevelAccount", back_populates="outreach_profiles")
    target_contact_infos = relationship("TargetContactInfo", back_populates="outreach_profile")
    login_code_requests = relationship("LinkedInLoginCodeRequest", back_populates="outreach_profile")
    scrape_events = relationship("LinkedInScrapeEvent", back_populates="outreach_profile")


class GoHighLevelAccount(Base):
    __tablename__ = "gohighlevel_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "location_id",
            name="uq_gohighlevel_account_user_location",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    location_id = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    access_token_encrypted = Column(String, nullable=False)
    refresh_token_encrypted = Column(String, nullable=False)
    expires_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True
    )
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="gohighlevel_accounts")
    # outreach_profiles = relationship("OutreachLinkedInProfile", back_populates="gohighlevel_account")
    # target_contact_infos = relationship("TargetContactInfo", back_populates="gohighlevel_account")


class LinkedInSession(Base):
    __tablename__ = "linkedin_sessions"

    id = Column(Integer, primary_key=True, index=True)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cookies = Column(String, nullable=True)        # encrypted JSON
    user_agent = Column(String, nullable=True)     # plain JSON or string
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="linkedin_session") # one outreach profile-one session
    user = relationship("User", back_populates="linkedin_sessions") # one user-many outreach profiles

class TargetLinkedInProfile(Base):
    __tablename__ = "target_profiles"
    __table_args__ = (
        UniqueConstraint(
            "outreach_profile_id",
            "profile_url",
            name="uq_target_profile_outreach_profile_url",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False)
    # user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    profile_url = Column(String, nullable=False)
    name = Column(String, nullable=True)
    lastname = Column(String, nullable=True)
    title = Column(String, nullable=True)
    about = Column(String, nullable=True)
    location = Column(String, nullable=True)
    connected = Column(Boolean, default=False, nullable=True)
    connection_pending = Column(Boolean, default=False, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    modified_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    first_fetched_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True
        #default=lambda: datetime.now(timezone.utc)
    )
    last_fetched_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True
        #default=lambda: datetime.now(timezone.utc)
    )


    # Relationships
    # users = relationship(
    #     "User",
    #     secondary=user_target_profiles,
    #     back_populates="target_profiles"
    # ) # many users-many target profiles (multiple users can share same target profile)
    outreach_profiles = relationship(
        "OutreachLinkedInProfile",
        secondary=outreach_target_profiles,
        back_populates="target_profiles"
    ) # many outreach profiles-many target profiles (multiple LinkedIn accounts can share same target profile)
    campaign_histories = relationship("CampaignHistory", back_populates="target_profile") # one target profile-many campaign history records
    actions = relationship("Action", back_populates="target_profile") # one target profile-many actions
    chat_histories = relationship("ChatHistory", back_populates="target_profile") # one target profile-many chat history records
    contact_info = relationship("TargetContactInfo", back_populates="target_profile", uselist=False)
    login_code_requests = relationship("LinkedInLoginCodeRequest", back_populates="target_profile")
    scrape_events = relationship("LinkedInScrapeEvent", back_populates="target_profile")


class TargetContactInfo(Base):
    __tablename__ = "target_contact_info"

    id = Column(Integer, primary_key=True, index=True)
    target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=False, unique=True)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False, index=True)
    gohighlevel_location_id = Column(String, nullable=True, index=True)
    raw_sections = Column(JSON, nullable=False, default=list)
    normalized_data = Column(JSON, nullable=True)
    primary_email = Column(String, nullable=True)
    phones_json = Column(JSON, nullable=True)
    urls_json = Column(JSON, nullable=True)
    sync_status = Column(String, nullable=False, default="pending")
    sync_error = Column(String, nullable=True)
    last_synced_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_fetch_error = Column(String, nullable=True)
    ghl_contact_id = Column(String, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    target_profile = relationship("TargetLinkedInProfile", back_populates="contact_info")
    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="target_contact_infos")
    # gohighlevel_account = relationship("GoHighLevelAccount", back_populates="target_contact_infos")


class Action(Base):
    __tablename__ = "actions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=False)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False)
    action_type = Column(String, nullable=False)
    status = Column(String, nullable=False)
    chat_history_id = Column(Integer, ForeignKey("chat_history.id"), nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    user = relationship("User", back_populates="actions") # one user-many actions
    target_profile = relationship("TargetLinkedInProfile", back_populates="actions") # one target profile-many actions
    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="actions") # one outreach profile-many actions
    chat_history = relationship("ChatHistory", back_populates="action") # one chat history record-one action

class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    # user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False)
    target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=False)
    message_role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    message_sent_at = Column(
        TIMESTAMP(timezone=True),
        nullable=True
    )
    record_created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    # user = relationship("User", back_populates="chat_history") # one user-many chat history records
    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="chat_histories") # one outreach profile-many chat history records
    target_profile = relationship("TargetLinkedInProfile", back_populates="chat_histories") # one target profile-many chat history records
    action = relationship("Action", back_populates="chat_history") # one chat history record-one action

class CampaignTemplate(Base):
    __tablename__ = "campaign_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String)
    description = Column(String)
    number_of_steps = Column(Integer, default=1)
    #outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False)
    #target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=False)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    modified_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    #status = Column(String, default="active")  # active, paused, completed

    #outreach_profile = relationship("OutreachLinkedInProfile", back_populates="campaigns")
    user = relationship("User", back_populates="campaign_templates") # one user-many campaign templates
    campaign_steps = relationship("CampaignStepTemplate", back_populates="campaign_template", cascade="all, delete-orphan") # one campaign template-many steps
    campaign_histories = relationship("CampaignHistory", back_populates="campaign_template") # one campaign template-many campaign history records
    lead_imports = relationship("CampaignLeadImport", back_populates="campaign_template") # one campaign template-many lead imports

class CampaignStepTemplate(Base):
    __tablename__ = "campaign_template_steps"

    id = Column(Integer, primary_key=True, index=True)
    campaign_template_id = Column(Integer, ForeignKey("campaign_templates.id"))
    step_number = Column(Integer, nullable=False)
    action = Column(String, nullable=False)
    additional_note_template = Column(String, nullable=True)
    delay_timestamp = Column(Interval, nullable=False)
    message_template = Column(String, nullable=True)
    variables = Column(ARRAY(String), nullable=False, default=list)

    campaign_template = relationship("CampaignTemplate", back_populates="campaign_steps") # one campaign template-many steps

# class CampaignHistory(Base):
#     __tablename__ = "campaign_history"

#     id = Column(Integer, primary_key=True, index=True)
#     campaign_id = Column(UUID(as_uuid=True), default=uuid.uuid4)
#     user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
#     outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False)
#     target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=False)
#     campaign_template_id = Column(Integer, ForeignKey("campaign_templates.id"), nullable=False)
#     campaign_step = Column(Integer, nullable=False)
#     status = Column(String, nullable=False, default="active")  # active, paused, completed
#     started_at = Column(
#         TIMESTAMP(timezone=True),
#         default=lambda: datetime.now(timezone.utc)
#     )
#     modified_at = Column(
#         TIMESTAMP(timezone=True),
#         default=lambda: datetime.now(timezone.utc),
#         onupdate=lambda: datetime.now(timezone.utc),
#     )

#     user = relationship("User", back_populates="campaign_histories") # one user-many campaign history records
#     outreach_profile = relationship("OutreachLinkedInProfile", back_populates="campaign_histories") # one outreach profile-many campaign history records
#     target_profile = relationship("TargetLinkedInProfile", back_populates="campaign_histories") # one target profile-many campaign history records
#     campaign_template = relationship("CampaignTemplate", back_populates="campaign_histories") # one campaign template-many campaign history records



class CampaignHistory(Base):
    __tablename__ = "campaign_history"

    id = Column(Integer, primary_key=True, index=True)
    runtime_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False)
    target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=False)
    campaign_template_id = Column(Integer, ForeignKey("campaign_templates.id"), nullable=False)
    number_of_steps = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="active")  # active, paused, completed
    started_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    modified_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    finished_on_step_number = Column(Integer, nullable=True)
    target_profile_responded = Column(Boolean, default=False)
    details = Column(JSON, nullable=True)

    user = relationship("User", back_populates="campaign_histories") # one user-many campaign history records
    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="campaign_histories") # one outreach profile-many campaign history records
    target_profile = relationship("TargetLinkedInProfile", back_populates="campaign_histories") # one target profile-many campaign history records
    campaign_template = relationship("CampaignTemplate", back_populates="campaign_histories") # one campaign template-many campaign history records
    campaign_step_histories = relationship("CampaignStepHistory", back_populates="campaign_history", cascade="all, delete-orphan", foreign_keys="[CampaignStepHistory.campaign_history_id]") # one campaign history record-many step history records
    login_code_requests = relationship("LinkedInLoginCodeRequest", back_populates="campaign_history")
    scrape_events = relationship("LinkedInScrapeEvent", back_populates="campaign_history")


class CampaignStepHistory(Base):
    __tablename__ = "campaign_step_history"

    id = Column(Integer, primary_key=True, index=True)
    campaign_history_id = Column(Integer, ForeignKey("campaign_history.id"), nullable=False)
    campaign_runtime_id = Column(UUID(as_uuid=True), nullable=False)
    step_number = Column(Integer, nullable=False)
    action = Column(String, nullable=False)
    status = Column(String, nullable=False)  # completed, failed, ignored
    started_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    modified_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    details = Column(JSON, nullable=True)

    campaign_history = relationship("CampaignHistory", back_populates="campaign_step_histories", foreign_keys=[campaign_history_id]) # one campaign history record-many step history records


class ScheduledCampaignTask(Base):
    """
    Tracks dynamically scheduled Celery tasks for campaign steps.
    Used to manage and cancel scheduled campaign actions.
    """
    __tablename__ = "scheduled_campaign_tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_history_id = Column(Integer, ForeignKey("campaign_history.id"), nullable=True)  # Nullable: set after campaign_history created
    campaign_step_history_id = Column(Integer, ForeignKey("campaign_step_history.id"), nullable=True)
    target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    celery_task_id = Column(String, unique=True, nullable=False, index=True)  # UUID from Celery
    task_name = Column(String, nullable=False)  # e.g., 'execute_campaign_step'
    scheduled_at = Column(TIMESTAMP(timezone=True), nullable=False)  # When to execute
    status = Column(String, nullable=False, default="scheduled")  # scheduled, executed, cancelled, failed
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    executed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    details = Column(JSON, nullable=True)  # Store task arguments
    
    # No relationships needed - lightweight tracking table


class LinkedInLoginCodeRequest(Base):
    __tablename__ = "linkedin_login_code_requests"
    __table_args__ = (
        Index(
            "uq_login_code_request_outreach_pending",
            "outreach_profile_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False, index=True)
    target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=True, index=True)
    campaign_history_id = Column(Integer, ForeignKey("campaign_history.id"), nullable=True, index=True)
    request_type = Column(String, nullable=False, default="login")
    status = Column(String, nullable=False, default="pending", index=True)
    status_detail = Column(String, nullable=True)
    pending_reason = Column(String, nullable=True)
    two_captcha_job_id = Column(String, nullable=True)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    last_status_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    metadata_json = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="login_code_requests")
    target_profile = relationship("TargetLinkedInProfile", back_populates="login_code_requests")
    campaign_history = relationship("CampaignHistory", back_populates="login_code_requests")
    verification_attempts = relationship(
        "LinkedInVerificationAttempt",
        back_populates="request",
        cascade="all, delete-orphan",
    )
    scrape_events = relationship(
        "LinkedInScrapeEvent",
        back_populates="login_code_request",
        cascade="all, delete-orphan",
    )


class LinkedInVerificationAttempt(Base):
    __tablename__ = "linkedin_verification_attempts"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("linkedin_login_code_requests.id"), nullable=False, index=True)
    submitted_by = Column(String, nullable=True)
    submitted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    source = Column(String, nullable=False, default="manual")
    code_value = Column(String, nullable=True)
    two_captcha_used = Column(Boolean, nullable=False, default=False)
    result = Column(String, nullable=True)
    error_details = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True, default=dict)
    submitted_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    processed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    request = relationship("LinkedInLoginCodeRequest", back_populates="verification_attempts")
    submitted_by_user = relationship("User", back_populates="verification_attempts")


class LinkedInScrapeEvent(Base):
    __tablename__ = "linkedin_scrape_events"

    id = Column(Integer, primary_key=True, index=True)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False, index=True)
    target_profile_id = Column(Integer, ForeignKey("target_profiles.id"), nullable=True, index=True)
    campaign_history_id = Column(Integer, ForeignKey("campaign_history.id"), nullable=True, index=True)
    login_code_request_id = Column(Integer, ForeignKey("linkedin_login_code_requests.id"), nullable=True, index=True)
    event_type = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    action_taken = Column(String, nullable=True)
    two_captcha_used = Column(Boolean, nullable=False, default=False)
    metadata_json = Column(JSON, nullable=True, default=dict)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="scrape_events")
    target_profile = relationship("TargetLinkedInProfile", back_populates="scrape_events")
    campaign_history = relationship("CampaignHistory", back_populates="scrape_events")
    login_code_request = relationship("LinkedInLoginCodeRequest", back_populates="scrape_events")


class CampaignLeadImport(Base):
    """
    Records lead import attempts triggered via API or CLI for auditing and retry support.
    """

    __tablename__ = "campaign_lead_imports"

    id = Column(Integer, primary_key=True, index=True)
    import_id = Column(UUID(as_uuid=True), default=uuid.uuid4, unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    outreach_profile_id = Column(Integer, ForeignKey("outreach_profiles.id"), nullable=False)
    campaign_template_id = Column(Integer, ForeignKey("campaign_templates.id"), nullable=False)
    search_url = Column(String, nullable=False)
    search_filters = Column(JSON, nullable=True)
    requested_lead_count = Column(Integer, nullable=True)
    total_extracted = Column(Integer, default=0, nullable=False)
    total_imported = Column(Integer, default=0, nullable=False)
    status = Column(String, default="pending", nullable=False)  # pending, running, completed, partial, failed
    error = Column(String, nullable=True)
    celery_task_id = Column(String, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="lead_imports")
    outreach_profile = relationship("OutreachLinkedInProfile", back_populates="lead_imports")
    campaign_template = relationship("CampaignTemplate", back_populates="lead_imports")