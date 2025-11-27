from pydantic import BaseModel, EmailStr, HttpUrl, field_validator, Field, model_validator
from uuid import UUID
from typing import Literal, Union
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import re
import json
import ast
from app.enums import CampaignStatus
from app.settings import LEAD_IMPORT_MAX_RESULTS_CAP

# -------------------------
# User Schemas
# -------------------------
class UserCreate(BaseModel):
    email: str
    password: str
    registration_key: str

class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    email: EmailStr
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True

class UserUpdateRequest(BaseModel):
    email: Optional[EmailStr] = None
    is_admin: Optional[bool] = None

class UserDetailResponse(BaseModel):
    id: int
    email: EmailStr
    is_admin: bool
    created_at: datetime
    profile_count: int
    campaign_count: int

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class PasswordResetRequest(BaseModel):
    email: EmailStr

class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str

# -------------------------
# GoHighLevel Schemas
# -------------------------

class GoHighLevelAuthResponse(BaseModel):
    authorization_url: HttpUrl
    message: str


class GoHighLevelManualExchangeRequest(BaseModel):
    code: str = Field(..., description="Authorization code returned by GoHighLevel")
    make_default: bool = Field(
        default=False, description="Set the resulting GoHighLevel account as default"
    )
    client_state: Optional[str] = Field(
        default=None,
        description="Optional opaque value to echo back in the response",
    )


class GoHighLevelAuthCompleteResponse(BaseModel):
    status: Literal["success"] = "success"
    account_id: int
    location_id: str
    is_default: bool
    client_state: Optional[str] = None


class GoHighLevelAccountBase(BaseModel):
    id: int
    location_id: str
    display_name: Optional[str] = None
    is_default: bool
    is_active: bool
    expires_at: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = Field(default=None, alias="metadata_json")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        allow_population_by_field_name = True


class GoHighLevelAccountResponse(GoHighLevelAccountBase):
    user_id: int


class GoHighLevelAccountListResponse(GoHighLevelAccountBase):
    pass


class GoHighLevelSetDefaultResponse(BaseModel):
    id: int
    is_default: bool

    class Config:
        from_attributes = True


class GoHighLevelStatusDetails(BaseModel):
    configured: bool
    client_id_set: bool
    client_secret_set: bool
    redirect_uri_set: bool


class GoHighLevelStatusResponse(BaseModel):
    status: Literal["ok", "error"]
    ghl_integration: GoHighLevelStatusDetails


# --------------------
# Target LinkedIn Profile Schemas
# --------------------
class FetchProfilesRequest(BaseModel):
    target_profile_urls: List[HttpUrl]
    outreach_profile_id: int

#class FetchProfilesResponse(BaseModel):


class ConnectionRequest(BaseModel):
    target_profile_url: HttpUrl
    outreach_profile_id: int
    message: Optional[str] = None

class MessageRequest(BaseModel):
    target_profile_url: HttpUrl
    outreach_profile_id: int
    message: str

class TargetProfileResponse(BaseModel):
    id: int
    profile_url: str
    name: Optional[str]
    lastname: Optional[str]
    title: Optional[str]
    about: Optional[str]
    location: Optional[str]
    connected: bool
    connection_pending: bool
    can_message: bool
    first_fetched_at: datetime
    modified_at: datetime

    class Config:
        from_attributes = True


# --------------------
# Outreach LinkedIn Profile Schemas
# --------------------

class OutreachProfileCreateRequest(BaseModel):
    linkedin_email: EmailStr
    linkedin_password: str
    linkedin_url: HttpUrl
    account_name: Optional[str] = Field(
        default=None,
        description="Optional account name for easier identification",
    )
    gohighlevel_location_id: Optional[str] = Field(
        default=None,
        description="Optional GoHighLevel location ID to associate with this outreach profile",
    )

class OutreachProfileCreateResponse(BaseModel):
    id: int
    linkedin_url: HttpUrl
    linkedin_email: EmailStr
    account_name: Optional[str] = None
    gohighlevel_location_id: Optional[str] = None

    class Config:
        from_attributes = True

class OutreachProfileListResponse(BaseModel):
    id: int
    linkedin_url: HttpUrl
    linkedin_email: EmailStr
    account_name: Optional[str] = None
    gohighlevel_location_id: Optional[str] = None

    class Config:
        from_attributes = True


class OutreachProfileGoHighLevelUpdate(BaseModel):
    gohighlevel_location_id: Optional[str] = Field(
        default=None,
        description="New GoHighLevel location ID to associate (null to unlink)",
    )


class OutreachProfileUpdateRequest(BaseModel):
    linkedin_email: Optional[EmailStr] = None
    linkedin_password: Optional[str] = None
    linkedin_url: Optional[HttpUrl] = None
    account_name: Optional[str] = None
    gohighlevel_location_id: Optional[str] = None


class OutreachProfileStatsResponse(BaseModel):
    total_campaigns: int
    active_campaigns: int
    total_connections: int
    total_messages: int
    total_actions: int
    last_active: Optional[datetime] = None


class OutreachProfileStatusResponse(BaseModel):
    id: int
    is_connected: bool
    is_verified: bool
    last_verified_at: Optional[datetime] = None
    session_status: str
    needs_attention: bool
    issues: List[str] = []


class OutreachProfileStatusBulkResponse(BaseModel):
    statuses: dict[int, OutreachProfileStatusResponse]


class OutreachProfileDeleteResponse(BaseModel):
    id: int
    status: str
    message: str


# --------------------
# Outreach LinkedIn Profile Update Schemas
# --------------------

class UpdateLinkedInUrlRequest(BaseModel):
    old_linkedin_url: HttpUrl
    new_linkedin_url: HttpUrl

class UpdateLinkedInEmailRequest(BaseModel):
    old_linkedin_email: EmailStr
    new_linkedin_email: EmailStr

class UpdateLinkedInPasswordRequest(BaseModel):
    old_linkedin_password: str
    new_linkedin_password: str

class VerifyPinRequest(BaseModel):
    pin: str
    operator_name: Optional[str] = None

# --------------------
# Action Schemas
# --------------------
class ActionCreate(BaseModel):
    user_id: int
    target_profile_id: int
    action_type: str
    details: Optional[dict] = None

class ActionResponse(BaseModel):
    id: int
    user_id: int
    target_profile_id: int
    action_type: str
    status: str
    details: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True

# --------------------
# Request Schemas
# --------------------
# class ConnectionRequest(BaseModel):
#     profile_url: HttpUrl
#     message: Optional[str] = None

class ConnectionRequestResponse(BaseModel):
    id: int
    profile_url: HttpUrl
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

# class MessageRequest(BaseModel):
#     profile_url: HttpUrl
#     message: str

class MessageRequestResponse(BaseModel):
    outreach_profile_id: int
    outreach_profile_url: HttpUrl
    target_profile_id: int
    target_profile_url: HttpUrl
    message: str
    status: str
    sent_at: datetime

    class Config:
        from_attributes = True

# --------------------
# Campaign Schemas
# --------------------
class CampaignStepTemplate(BaseModel):
    step_number: int = Field(..., description="Step number (1, 2, 3, etc.)")
    action: Literal["send_connection", "send_message"] = Field(..., description="Action type")
    additional_note_template: Optional[str] = Field(None, description="Additional message when sending connection request")
    delay_timestamp: Union[str, dict, timedelta] = Field(..., description="Delay after previous step - accepts time strings, dicts, or timedelta objects")
    message_template: Optional[str] = Field(None, description="Personalized message content")

    @field_validator('step_number')
    @classmethod
    def validate_step_number(cls, v):
        if v < 1:
            raise ValueError("Step number must be greater than 0")
        return v

    @field_validator('delay_timestamp', mode='before')
    @classmethod
    def validate_delay_timestamp(cls, v):
        if isinstance(v, str):
            # Handle JSON string format like '{"days": 0, "hours": 0, "minutes": 0, "seconds": 0}'
            # Also handle Python dict string format like "{'hours': 1, 'minutes': 10, 'seconds': 15}"
            if v.strip().startswith('{') and v.strip().endswith('}'):
                try:
                    # First try JSON parsing (double quotes)
                    try:
                        time_dict = json.loads(v)
                    except json.JSONDecodeError:
                        # If JSON fails, try ast.literal_eval (handles single quotes)
                        time_dict = ast.literal_eval(v)
                    
                    if all(key in time_dict for key in ['days', 'hours', 'minutes', 'seconds']):
                        days = int(time_dict['days'])
                        hours = int(time_dict['hours'])
                        minutes = int(time_dict['minutes'])
                        seconds = int(time_dict['seconds'])
                        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
                except (json.JSONDecodeError, ValueError, KeyError, SyntaxError):
                    pass
            
            # Handle time string formats like "00:00", "01:30", "00:00:00", "2:15:30", "1:22:15"
            time_pattern = r'^(\d{1,3}):(\d{2})(?::(\d{2}))?$'
            match = re.match(time_pattern, v)
            if match:
                hours = int(match.group(1))
                minutes = int(match.group(2))
                seconds = int(match.group(3)) if match.group(3) else 0
                return timedelta(hours=hours, minutes=minutes, seconds=seconds)
            
            # Handle duration string formats like "1d2h30m40s", "1h30m", "30m40s", "1h", "30m", "40s"
            duration_pattern = r'^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$'
            match = re.match(duration_pattern, v)
            if match and any(match.groups()):
                days = int(match.group(1)) if match.group(1) else 0
                hours = int(match.group(2)) if match.group(2) else 0
                minutes = int(match.group(3)) if match.group(3) else 0
                seconds = int(match.group(4)) if match.group(4) else 0
                return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            
            raise ValueError("delay_timestamp must be in format 'HH:MM', 'HH:MM:SS', '1d2h30m40s', or '{\"days\": 0, \"hours\": 0, \"minutes\": 0, \"seconds\": 0}'")

        elif isinstance(v, dict):
            # Handle dictionary format like {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}
            if all(key in v for key in ['days', 'hours', 'minutes', 'seconds']):
                days = int(v['days'])
                hours = int(v['hours'])
                minutes = int(v['minutes'])
                seconds = int(v['seconds'])
                return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
            else:
                raise ValueError("Dictionary format must contain 'days', 'hours', 'minutes', and 'seconds' keys")

        elif isinstance(v, timedelta):
            # Ensure timedelta is normalized with explicit components
            total_seconds = int(v.total_seconds())
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        else:
            raise ValueError("delay_timestamp must be a timedelta object, time string, or dictionary")

    @model_validator(mode="after")
    def validate_message_required_for_send_message(self):
        action = self.action
        message_template = self.message_template
        if action == "send_message" and not message_template:
            raise ValueError("message_template is required when action is 'send_message'")
        return self

    @model_validator(mode="after")
    def validate_additional_note_required_for_send_connection(self):
        action = self.action
        additional_note_template = self.additional_note_template
        if action == "send_connection" and not additional_note_template:
            raise ValueError("additional_note_template is required when action is 'send_connection'")
        return self

class CampaignTemplateCreateRequest(BaseModel):
    name: Optional[str] = Field(None, description="Campaign name, optional")
    description: Optional[str] = Field(None, description="Campaign description, optional")
    steps: List[CampaignStepTemplate]

    @field_validator('steps')
    @classmethod
    def validate_steps(cls, steps):
        if not steps:
            raise ValueError("Steps must not be empty")
        step_numbers = [s.step_number for s in steps]
        if len(set(step_numbers)) != len(step_numbers):
            raise ValueError("Duplicate step numbers are not allowed")
        return steps

class CampaignTemplateCreateResponse(BaseModel):
    id: int
    name: Optional[str]
    variables: Optional[List[str]] = Field(default_factory=list, description="List of template variable names used in steps")

class TargetProfileVariables(BaseModel):
    url: str = Field(..., description="LinkedIn profile URL")
    variables: Dict[str, str] = Field(None, description="Variables required by the campaign template")

class RunCampaignRequest(BaseModel):
    campaign_template_id: int = Field(..., description="Campaign template ID")
    outreach_profile_id: int = Field(..., description="LinkedIn outreach profile ID")
    target_profiles: List[TargetProfileVariables]

    # Note: Variable validation is now handled in the API endpoint where database session is available


class LeadImportRequest(BaseModel):
    campaign_template_id: int = Field(..., description="Campaign template to use for imported leads")
    outreach_profile_id: int = Field(..., description="Outreach profile to execute the campaign")
    search_url: HttpUrl = Field(..., description="LinkedIn people search URL to scrape")
    max_results: Optional[int] = Field(
        None,
        ge=1,
        description=f"Maximum leads to import (cap: {LEAD_IMPORT_MAX_RESULTS_CAP})",
    )
    search_filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata describing the search filters applied",
    )

    @field_validator("search_url")
    @classmethod
    def validate_search_url(cls, value: HttpUrl):
        url_lower = str(value).lower()
        if "linkedin.com" not in url_lower or "/search/" not in url_lower:
            raise ValueError("search_url must be a LinkedIn search URL.")
        return value

    @model_validator(mode="after")
    def enforce_max_results_cap(self):
        if self.max_results and self.max_results > LEAD_IMPORT_MAX_RESULTS_CAP:
            raise ValueError(f"max_results cannot exceed {LEAD_IMPORT_MAX_RESULTS_CAP}.")
        return self


class LeadImportPreviewRequest(BaseModel):
    outreach_profile_id: int = Field(..., description="Outreach profile that will execute the preview scrape")
    search_url: HttpUrl = Field(..., description="LinkedIn people search URL to preview")
    max_results: Optional[int] = Field(
        None,
        ge=1,
        description=f"Maximum leads to preview (cap: {LEAD_IMPORT_MAX_RESULTS_CAP})",
    )

    @field_validator("search_url")
    @classmethod
    def validate_search_url(cls, value: HttpUrl):
        url_lower = str(value).lower()
        if "linkedin.com" not in url_lower or "/search/" not in url_lower:
            raise ValueError("search_url must be a LinkedIn search URL.")
        return value

    @model_validator(mode="after")
    def enforce_max_results_cap(self):
        if self.max_results and self.max_results > LEAD_IMPORT_MAX_RESULTS_CAP:
            raise ValueError(f"max_results cannot exceed {LEAD_IMPORT_MAX_RESULTS_CAP}.")
        return self


class LeadImportTriggerResponse(BaseModel):
    import_id: UUID = Field(..., description="Lead import identifier")
    status: str = Field(..., description="Initial lead import status")
    requested_lead_count: Optional[int] = Field(None, description="Requested limit for the import")


class LeadImportPreviewResponse(BaseModel):
    total: int = Field(..., description="Number of leads returned in the preview")
    targets: List[TargetProfileVariables]


class LeadImportStatusResponse(BaseModel):
    import_id: UUID
    status: str
    search_url: str
    requested_lead_count: Optional[int]
    total_extracted: int
    total_imported: int
    error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    skipped: int = 0

    @model_validator(mode="after")
    def compute_skipped(self):
        extracted = self.total_extracted or 0
        imported = self.total_imported or 0
        self.skipped = max(extracted - imported, 0)
        return self


class CampaignStepStatusResponse(BaseModel):
    started_at: datetime
    modified_at: datetime
    status: CampaignStatus
    step_number: int
    details: Optional[Dict[str, str]]


class CampaignStatusResponse(BaseModel):
    campaign_history_id: int
    runtime_id: UUID
    started_at: datetime
    modified_at: datetime
    status: CampaignStatus
    latest_step: int
    total_steps: int
    details: Optional[Dict[str, str]]

    class Config:
        from_attributes = True


class PauseCampaignResponse(BaseModel):
    status: str
    message: str
    campaign_history_id: int
    cancelled_tasks_count: int
    cancelled_watchers_count: int


class CampaignHistoryResponse(BaseModel):
    campaign_history_id: int
    runtime_id: UUID
    user_id: int
    outreach_profile_id: int
    target_profile_id: int
    campaign_template_id: int
    number_of_steps: int
    status: CampaignStatus
    started_at: datetime
    modified_at: datetime
    finished_on_step_number: Optional[int]
    target_profile_responded: bool
    details: Optional[Dict[str, Any]]
    target_profile_url: Optional[str] = None
    outreach_profile_email: Optional[str] = None
    template_name: Optional[str] = None

    class Config:
        from_attributes = True


class CampaignTemplateResponse(BaseModel):
    id: int
    user_id: int
    name: Optional[str]
    description: Optional[str]
    number_of_steps: int
    created_at: datetime

    class Config:
        from_attributes = True


class CampaignStepHistoryResponse(BaseModel):
    id: int
    campaign_history_id: int
    campaign_runtime_id: UUID
    step_number: int
    action: str
    status: str
    started_at: datetime
    modified_at: datetime
    details: Optional[Union[Dict[str, Any], str]] = None

    class Config:
        from_attributes = True


class ScheduledTaskResponse(BaseModel):
    id: int
    campaign_history_id: Optional[int]
    campaign_step_history_id: Optional[int]
    target_profile_id: int
    step_number: int
    celery_task_id: str
    task_name: str
    scheduled_at: datetime
    status: str
    created_at: datetime
    executed_at: Optional[datetime]
    details: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True


class CampaignDetailResponse(BaseModel):
    campaign_history_id: int
    runtime_id: UUID
    user_id: int
    outreach_profile_id: int
    target_profile_id: int
    campaign_template_id: int
    number_of_steps: int
    status: CampaignStatus
    started_at: datetime
    modified_at: datetime
    finished_on_step_number: Optional[int]
    target_profile_responded: bool
    details: Optional[Dict[str, Any]]
    target_profile_url: Optional[str] = None
    outreach_profile_email: Optional[str] = None
    template_name: Optional[str] = None
    step_histories: List[CampaignStepHistoryResponse] = []

    class Config:
        from_attributes = True


# --------------------
# LinkedIn Verification Schemas
# --------------------


class LoginCodeRequestCreate(BaseModel):
    outreach_profile_id: int
    request_type: str = Field(default="login", description="Type of verification request (login/captcha/etc.)")
    target_profile_id: Optional[int] = None
    campaign_history_id: Optional[int] = None
    pending_reason: Optional[str] = None
    ttl_seconds: Optional[int] = Field(default=1800, ge=60, le=3600)
    metadata: Optional[Dict[str, Any]] = None
    two_captcha_job_id: Optional[str] = None


class LoginCodeRequestStatusUpdate(BaseModel):
    status: str
    status_detail: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    event_type: Optional[str] = None
    event_detail: Optional[str] = None
    action_taken: Optional[str] = None
    two_captcha_used: bool = False


class LoginCodeAttemptSubmit(BaseModel):
    code_value: Optional[str] = Field(default=None, description="Verification code provided by operator")
    source: str = Field(default="manual", description="manual/twocaptcha/etc.")
    submitted_by: Optional[str] = Field(default=None, description="Free-form identifier for operator/browser")
    submitted_by_user_id: Optional[int] = Field(default=None, description="User ID when available")
    two_captcha_used: bool = False
    result: Optional[str] = None
    error_details: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LoginCodeAttemptResponse(BaseModel):
    id: int
    request_id: int
    source: str
    submitted_by: Optional[str]
    submitted_by_user_id: Optional[int]
    code_value: Optional[str]
    two_captcha_used: bool
    result: Optional[str]
    error_details: Optional[str]
    metadata: Optional[Dict[str, Any]] = Field(default=None, alias="metadata_json")
    submitted_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True
        allow_population_by_field_name = True


class LoginCodeAttemptUpdate(BaseModel):
    result: Optional[str] = None
    error_details: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LoginCodeRequestResponse(BaseModel):
    id: int
    outreach_profile_id: int
    target_profile_id: Optional[int]
    campaign_history_id: Optional[int]
    status: str
    request_type: str
    expires_at: datetime
    remaining_seconds: int
    pending_reason: Optional[str]
    status_detail: Optional[str]
    metadata: Optional[Dict[str, Any]] = None


class CodeRequestSubmitPayload(BaseModel):
    code: str = Field(..., min_length=1, max_length=32)
    operator_name: Optional[str] = Field(default=None, max_length=120)
    source: Optional[str] = Field(default="portal", max_length=64)


class CodeRequestDetails(BaseModel):
    id: int
    outreach_profile_id: int
    outreach_email: str
    outreach_linkedin_url: str
    target_profile_id: Optional[int]
    target_name: Optional[str]
    target_url: Optional[str]
    campaign_history_id: Optional[int]
    status: str
    request_type: str
    expires_at: datetime
    remaining_seconds: int
    pending_reason: Optional[str]
    status_detail: Optional[str]
    resolved_at: Optional[datetime]
    last_status_at: Optional[datetime]
    two_captcha_job_id: Optional[str]
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    latest_attempt: Optional["LoginCodeAttemptResponse"]
    attempts: List["LoginCodeAttemptResponse"]

    class Config:
        from_attributes = True


class CodeRequestListResponse(BaseModel):
    pending: List[CodeRequestDetails]
    succeeded: List[CodeRequestDetails]
    errored: List[CodeRequestDetails]
