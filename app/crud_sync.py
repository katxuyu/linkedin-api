import uuid
from collections import defaultdict
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any, Iterable, Tuple
from datetime import datetime, timezone, timedelta
from app.celery_app import celery_app
from app import models
from app.utils.helpers import extract_template_variables, normalize_timedelta_to_standard_format
from app.errors import ProfileNotFoundError
from app.settings import FERNET, PWD_CONTEXT, logger


UNSET = object()

# LinkedIn verification constants
DEFAULT_LOGIN_CODE_TTL_SECONDS = 30 * 60
LOGIN_CODE_STATUS_PENDING = "pending"
LOGIN_CODE_STATUS_SUBMITTED = "submitted"
LOGIN_CODE_STATUS_SUCCEEDED = "succeeded"
LOGIN_CODE_STATUS_FAILED = "failed"
LOGIN_CODE_STATUS_TIMED_OUT = "timed_out"
LOGIN_CODE_STATUS_CANCELLED = "cancelled"
TERMINAL_LOGIN_CODE_STATUSES = {
    LOGIN_CODE_STATUS_SUCCEEDED,
    LOGIN_CODE_STATUS_FAILED,
    LOGIN_CODE_STATUS_TIMED_OUT,
    LOGIN_CODE_STATUS_CANCELLED,
}


def _encrypt_token(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return FERNET.encrypt(value.encode()).decode()


def _decrypt_token(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return FERNET.decrypt(value.encode()).decode()


# --------------------------
# GoHighLevel Accounts
# --------------------------
def list_gohighlevel_accounts(db: Session, user_id: int) -> list[models.GoHighLevelAccount]:
    result = db.execute(
        select(models.GoHighLevelAccount)
        .where(models.GoHighLevelAccount.user_id == user_id)
        .order_by(desc(models.GoHighLevelAccount.created_at))
    )
    return result.scalars().all()


def get_gohighlevel_account_by_id(
    db: Session,
    account_id: int,
    *,
    user_id: Optional[int] = None,
) -> Optional[models.GoHighLevelAccount]:
    result = db.execute(
        select(models.GoHighLevelAccount).where(models.GoHighLevelAccount.id == account_id)
    )
    account = result.scalars().first()
    if account and user_id is not None and account.user_id != user_id:
        return None
    return account


def get_gohighlevel_account_by_location_id(
    db: Session,
    location_id: str,
    *,
    user_id: Optional[int] = None,
) -> Optional[models.GoHighLevelAccount]:
    stmt = select(models.GoHighLevelAccount).where(models.GoHighLevelAccount.location_id == location_id)
    if user_id is not None:
        stmt = stmt.where(models.GoHighLevelAccount.user_id == user_id)
    
    result = db.execute(stmt)
    return result.scalars().first()


def get_gohighlevel_account_by_location(
    db: Session,
    user_id: int,
    location_id: str,
) -> Optional[models.GoHighLevelAccount]:
    result = db.execute(
        select(models.GoHighLevelAccount).where(
            models.GoHighLevelAccount.user_id == user_id,
            models.GoHighLevelAccount.location_id == location_id,
        )
    )
    return result.scalars().first()


def get_default_gohighlevel_account(db: Session, user_id: int) -> Optional[models.GoHighLevelAccount]:
    result = db.execute(
        select(models.GoHighLevelAccount).where(
            models.GoHighLevelAccount.user_id == user_id,
            models.GoHighLevelAccount.is_default.is_(True),
        )
    )
    return result.scalars().first()


def _clear_default_gohighlevel_accounts(db: Session, user_id: int) -> None:
    result = db.execute(
        select(models.GoHighLevelAccount).where(models.GoHighLevelAccount.user_id == user_id)
    )
    accounts = result.scalars().all()
    updated = False
    for account in accounts:
        if account.is_default:
            account.is_default = False
            updated = True
    if updated:
        db.commit()


def set_default_gohighlevel_account(
    db: Session,
    *,
    user_id: int,
    account_id: int,
) -> Optional[models.GoHighLevelAccount]:
    account = get_gohighlevel_account_by_id(db, account_id, user_id=user_id)
    if not account:
        return None

    result = db.execute(
        select(models.GoHighLevelAccount).where(models.GoHighLevelAccount.user_id == user_id)
    )
    accounts = result.scalars().all()
    for record in accounts:
        record.is_default = record.id == account_id
    db.commit()
    db.refresh(account)
    return account


def upsert_gohighlevel_account(
    db: Session,
    *,
    user_id: int,
    location_id: str,
    display_name: Optional[str],
    access_token: str,
    refresh_token: str,
    expires_at,
    metadata: Optional[Dict[str, Any]] = None,
    force_default: bool = False,
) -> models.GoHighLevelAccount:
    existing = get_gohighlevel_account_by_location(db, user_id, location_id)

    if existing:
        existing.display_name = display_name
        existing.access_token_encrypted = _encrypt_token(access_token)
        existing.refresh_token_encrypted = _encrypt_token(refresh_token)
        existing.expires_at = expires_at
        if metadata is not None:
            existing.metadata_json = metadata
        existing.is_active = True

        if force_default:
            set_default_gohighlevel_account(db, user_id=user_id, account_id=existing.id)
        else:
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing

    should_be_default = force_default or get_default_gohighlevel_account(db, user_id) is None
    if should_be_default:
        _clear_default_gohighlevel_accounts(db, user_id)

    account = models.GoHighLevelAccount(
        user_id=user_id,
        location_id=location_id,
        display_name=display_name,
        is_default=should_be_default,
        is_active=True,
        access_token_encrypted=_encrypt_token(access_token),
        refresh_token_encrypted=_encrypt_token(refresh_token),
        expires_at=expires_at,
        metadata_json=metadata or {},
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def update_gohighlevel_tokens(
    db: Session,
    *,
    account_id: int,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    expires_at=None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[models.GoHighLevelAccount]:
    account = get_gohighlevel_account_by_id(db, account_id)
    if not account:
        return None

    if access_token is not None:
        account.access_token_encrypted = _encrypt_token(access_token)
    if refresh_token is not None:
        account.refresh_token_encrypted = _encrypt_token(refresh_token)
    if expires_at is not None:
        account.expires_at = expires_at
    if metadata is not None:
        account.metadata_json = metadata

    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def deactivate_gohighlevel_account(
    db: Session,
    *,
    account_id: int,
    user_id: int,
) -> Optional[models.GoHighLevelAccount]:
    account = get_gohighlevel_account_by_id(db, account_id, user_id=user_id)
    if not account:
        return None
    account.is_active = False
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def deserialize_gohighlevel_tokens(account: models.GoHighLevelAccount) -> Dict[str, Optional[str]]:
    return {
        "access_token": _decrypt_token(account.access_token_encrypted),
        "refresh_token": _decrypt_token(account.refresh_token_encrypted),
    }


# --------------------------
# LinkedIn Verification Flow
# --------------------------
def get_login_code_request_by_id(db: Session, request_id: int) -> Optional[models.LinkedInLoginCodeRequest]:
    result = db.execute(
        select(models.LinkedInLoginCodeRequest).where(models.LinkedInLoginCodeRequest.id == request_id)
    )
    return result.scalars().first()


def get_login_code_request_for_user(
    db: Session,
    *,
    request_id: int,
    user_id: int,
) -> Optional[models.LinkedInLoginCodeRequest]:
    result = db.execute(
        select(models.LinkedInLoginCodeRequest)
        .join(
            models.OutreachLinkedInProfile,
            models.LinkedInLoginCodeRequest.outreach_profile_id == models.OutreachLinkedInProfile.id,
        )
        .where(
            models.LinkedInLoginCodeRequest.id == request_id,
            models.OutreachLinkedInProfile.user_id == user_id,
        )
    )
    return result.scalars().first()


def get_pending_login_code_request_for_outreach(
    db: Session, outreach_profile_id: int
) -> Optional[models.LinkedInLoginCodeRequest]:
    result = db.execute(
        select(models.LinkedInLoginCodeRequest)
        .where(
            models.LinkedInLoginCodeRequest.outreach_profile_id == outreach_profile_id,
            models.LinkedInLoginCodeRequest.status == LOGIN_CODE_STATUS_PENDING,
        )
        .order_by(models.LinkedInLoginCodeRequest.created_at.desc())
    )
    return result.scalars().first()


def create_login_code_request(
    db: Session,
    *,
    outreach_profile_id: int,
    request_type: str = "login",
    target_profile_id: Optional[int] = None,
    campaign_history_id: Optional[int] = None,
    pending_reason: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    ttl_seconds: int = DEFAULT_LOGIN_CODE_TTL_SECONDS,
    metadata: Optional[Dict[str, Any]] = None,
    two_captcha_job_id: Optional[str] = None,
) -> models.LinkedInLoginCodeRequest:
    existing = get_pending_login_code_request_for_outreach(db, outreach_profile_id)
    if existing:
        return existing

    now = datetime.now(timezone.utc)
    expires_at = expires_at or now + timedelta(seconds=max(ttl_seconds, 60))

    record = models.LinkedInLoginCodeRequest(
        outreach_profile_id=outreach_profile_id,
        target_profile_id=target_profile_id,
        campaign_history_id=campaign_history_id,
        request_type=request_type,
        status=LOGIN_CODE_STATUS_PENDING,
        pending_reason=pending_reason,
        two_captcha_job_id=two_captcha_job_id,
        expires_at=expires_at,
        last_status_at=now,
        metadata_json=metadata or {},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def update_login_code_request_status(
    db: Session,
    *,
    request_id: int,
    status: str,
    status_detail: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[models.LinkedInLoginCodeRequest]:
    record = get_login_code_request_by_id(db, request_id)
    if not record:
        return None

    now = datetime.now(timezone.utc)
    record.status = status
    if status_detail is not None:
        record.status_detail = status_detail
    record.last_status_at = now
    record.updated_at = now
    if metadata:
        current = record.metadata_json or {}
        current.update(metadata)
        record.metadata_json = current
    if status in TERMINAL_LOGIN_CODE_STATUSES:
        record.resolved_at = record.resolved_at or now

    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def resolve_all_pending_login_code_requests(
    db: Session,
    *,
    outreach_profile_id: int,
    status: str,
    status_detail: Optional[str] = None,
) -> int:
    """
    Resolve all pending/failed login code requests for a profile.
    Used when verification succeeds via app approval to clear old failed states.
    
    Returns the number of records updated.
    """
    from sqlalchemy import update
    
    now = datetime.now(timezone.utc)
    
    # Update all non-terminal requests for this profile
    non_terminal_statuses = [
        LOGIN_CODE_STATUS_PENDING,
        LOGIN_CODE_STATUS_SUBMITTED,
        LOGIN_CODE_STATUS_FAILED,
        LOGIN_CODE_STATUS_TIMED_OUT,
    ]
    
    stmt = (
        update(models.LinkedInLoginCodeRequest)
        .where(
            models.LinkedInLoginCodeRequest.outreach_profile_id == outreach_profile_id,
            models.LinkedInLoginCodeRequest.status.in_(non_terminal_statuses)
        )
        .values(
            status=status,
            status_detail=status_detail or "Resolved by successful verification",
            resolved_at=now,
            last_status_at=now,
            updated_at=now
        )
    )
    
    result = db.execute(stmt)
    db.commit()
    return result.rowcount


def record_verification_attempt(
    db: Session,
    *,
    request_id: int,
    source: str,
    submitted_by: Optional[str],
    submitted_by_user_id: Optional[int],
    code_value: Optional[str],
    result: Optional[str],
    error_details: Optional[str],
    two_captcha_used: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
    processed_at: Optional[datetime] = None,
) -> models.LinkedInVerificationAttempt:
    now = datetime.now(timezone.utc)
    attempt = models.LinkedInVerificationAttempt(
        request_id=request_id,
        source=source,
        submitted_by=submitted_by,
        submitted_by_user_id=submitted_by_user_id,
        code_value=code_value,
        two_captcha_used=two_captcha_used,
        result=result,
        error_details=error_details,
        metadata_json=metadata or {},
        submitted_at=now,
        processed_at=processed_at,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def get_latest_verification_attempt(
    db: Session,
    *,
    request_id: int,
) -> Optional[models.LinkedInVerificationAttempt]:
    result = db.execute(
        select(models.LinkedInVerificationAttempt)
        .where(models.LinkedInVerificationAttempt.request_id == request_id)
        .order_by(models.LinkedInVerificationAttempt.submitted_at.desc())
        .limit(1)
    )
    return result.scalars().first()


def get_verification_attempt_by_id(
    db: Session,
    attempt_id: int,
) -> Optional[models.LinkedInVerificationAttempt]:
    result = db.execute(
        select(models.LinkedInVerificationAttempt)
        .where(models.LinkedInVerificationAttempt.id == attempt_id)
    )
    return result.scalars().first()


def list_verification_attempts(
    db: Session,
    *,
    request_id: int,
) -> list[models.LinkedInVerificationAttempt]:
    result = db.execute(
        select(models.LinkedInVerificationAttempt)
        .where(models.LinkedInVerificationAttempt.request_id == request_id)
        .order_by(models.LinkedInVerificationAttempt.submitted_at.asc())
    )
    return result.scalars().all()


def update_verification_attempt(
    db: Session,
    *,
    attempt_id: int,
    result_value: Optional[str] = None,
    error_details: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[models.LinkedInVerificationAttempt]:
    attempt = db.execute(
        select(models.LinkedInVerificationAttempt).where(models.LinkedInVerificationAttempt.id == attempt_id)
    ).scalars().first()
    if not attempt:
        return None

    if result_value is not None:
        attempt.result = result_value
    if error_details is not None:
        attempt.error_details = error_details
    if metadata:
        data = attempt.metadata_json or {}
        data.update(metadata)
        attempt.metadata_json = data
    attempt.processed_at = datetime.now(timezone.utc)

    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def list_pending_login_code_requests(
    db: Session,
    *,
    include_expired: bool = False,
    limit: int = 200,
) -> list[models.LinkedInLoginCodeRequest]:
    now = datetime.now(timezone.utc)
    query = select(models.LinkedInLoginCodeRequest).where(
        models.LinkedInLoginCodeRequest.status == LOGIN_CODE_STATUS_PENDING,
    )
    if not include_expired:
        query = query.where(models.LinkedInLoginCodeRequest.expires_at > now)

    query = query.order_by(models.LinkedInLoginCodeRequest.expires_at.asc()).limit(limit)
    result = db.execute(query)
    return result.scalars().all()


def list_recent_verification_attempts(
    db: Session,
    *,
    limit: int = 250,
) -> list[models.LinkedInVerificationAttempt]:
    result = db.execute(
        select(models.LinkedInVerificationAttempt)
        .order_by(models.LinkedInVerificationAttempt.submitted_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


def list_login_code_requests_for_user(
    db: Session,
    *,
    user_id: int,
    statuses: Optional[Iterable[str]] = None,
    limit: int = 200,
) -> List[Tuple[models.LinkedInLoginCodeRequest, models.OutreachLinkedInProfile, Optional[models.TargetLinkedInProfile]]]:
    query = (
        db.query(
            models.LinkedInLoginCodeRequest,
            models.OutreachLinkedInProfile,
            models.TargetLinkedInProfile,
        )
        .join(
            models.OutreachLinkedInProfile,
            models.LinkedInLoginCodeRequest.outreach_profile_id == models.OutreachLinkedInProfile.id,
        )
        .outerjoin(
            models.TargetLinkedInProfile,
            models.LinkedInLoginCodeRequest.target_profile_id == models.TargetLinkedInProfile.id,
        )
        .where(models.OutreachLinkedInProfile.user_id == user_id)
    )
    if statuses:
        query = query.filter(models.LinkedInLoginCodeRequest.status.in_(list(statuses)))
    query = query.order_by(models.LinkedInLoginCodeRequest.created_at.desc()).limit(limit)
    return query.all()


def list_verification_attempts_for_requests(
    db: Session,
    request_ids: List[int],
) -> Dict[int, List[models.LinkedInVerificationAttempt]]:
    if not request_ids:
        return {}
    result = db.execute(
        select(models.LinkedInVerificationAttempt)
        .where(models.LinkedInVerificationAttempt.request_id.in_(request_ids))
        .order_by(models.LinkedInVerificationAttempt.submitted_at.desc())
    )
    attempts_map: Dict[int, List[models.LinkedInVerificationAttempt]] = defaultdict(list)
    for attempt in result.scalars().all():
        attempts_map[attempt.request_id].append(attempt)
    return attempts_map


def create_scrape_event(
    db: Session,
    *,
    outreach_profile_id: int,
    event_type: str,
    target_profile_id: Optional[int] = None,
    campaign_history_id: Optional[int] = None,
    login_code_request_id: Optional[int] = None,
    detail: Optional[str] = None,
    action_taken: Optional[str] = None,
    two_captcha_used: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> models.LinkedInScrapeEvent:
    event = models.LinkedInScrapeEvent(
        outreach_profile_id=outreach_profile_id,
        target_profile_id=target_profile_id,
        campaign_history_id=campaign_history_id,
        login_code_request_id=login_code_request_id,
        event_type=event_type,
        detail=detail,
        action_taken=action_taken,
        two_captcha_used=two_captcha_used,
        metadata_json=metadata or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_recent_scrape_events(
    db: Session,
    *,
    outreach_profile_id: Optional[int] = None,
    limit: int = 250,
) -> list[models.LinkedInScrapeEvent]:
    query = select(models.LinkedInScrapeEvent).order_by(models.LinkedInScrapeEvent.created_at.desc()).limit(limit)
    if outreach_profile_id:
        query = query.where(models.LinkedInScrapeEvent.outreach_profile_id == outreach_profile_id)
    result = db.execute(query)
    return result.scalars().all()


# --------------------------
# Target Contact Info
# --------------------------
def get_target_contact_info(db: Session, target_profile_id: int) -> Optional[models.TargetContactInfo]:
    result = db.execute(
        select(models.TargetContactInfo).where(models.TargetContactInfo.target_profile_id == target_profile_id)
    )
    return result.scalars().first()


def upsert_target_contact_info(
    db: Session,
    *,
    target_profile_id: int,
    outreach_profile_id: int,
    gohighlevel_location_id: Optional[str],
    raw_sections: Any,
    normalized_data: Optional[Dict[str, Any]],
    primary_email: Optional[str],
    phones_json: Optional[Any],
    urls_json: Optional[Any],
    sync_status: str = "pending",
    sync_error: Optional[str] = None,
    last_fetch_error: Optional[str] = None,
    ghl_contact_id: Optional[str] = None,
) -> models.TargetContactInfo:
    record = get_target_contact_info(db, target_profile_id)
    if record:
        record.raw_sections = raw_sections
        record.normalized_data = normalized_data
        record.primary_email = primary_email
        record.phones_json = phones_json
        record.urls_json = urls_json
        record.sync_status = sync_status
        record.sync_error = sync_error
        record.last_fetch_error = last_fetch_error
        record.ghl_contact_id = ghl_contact_id
        record.gohighlevel_location_id = gohighlevel_location_id
    else:
        record = models.TargetContactInfo(
            target_profile_id=target_profile_id,
            outreach_profile_id=outreach_profile_id,
            gohighlevel_location_id=gohighlevel_location_id,
            raw_sections=raw_sections,
            normalized_data=normalized_data,
            primary_email=primary_email,
            phones_json=phones_json,
            urls_json=urls_json,
            sync_status=sync_status,
            sync_error=sync_error,
            last_fetch_error=last_fetch_error,
            ghl_contact_id=ghl_contact_id,
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return record


def update_contact_sync_status(
    db: Session,
    *,
    target_profile_id: int,
    sync_status: str,
    sync_error: Optional[str] = None,
    last_synced_at=None,
    ghl_contact_id: Optional[str] = None,
) -> Optional[models.TargetContactInfo]:
    record = get_target_contact_info(db, target_profile_id)
    if not record:
        return None

    record.sync_status = sync_status
    record.sync_error = sync_error
    record.last_synced_at = last_synced_at
    if ghl_contact_id is not None:
        record.ghl_contact_id = ghl_contact_id

    db.commit()
    db.refresh(record)
    return record



# --------------------------
# User
# --------------------------
def get_user_by_id(db: Session, user_id: int) -> Optional[models.User]:
    result = db.execute(select(models.User).filter(models.User.id == user_id))
    return result.scalars().first()

# --------------------------
# Outreach LinkedIn Profile
# --------------------------
def get_outreach_profile_by_id(db: Session, profile_id: int):
    result = db.execute(
        select(models.OutreachLinkedInProfile)
        .where(
            models.OutreachLinkedInProfile.id == profile_id
        )
    )
    return result.scalars().first()

def get_target_profile_by_id(db: Session, target_profile_id: int) -> Optional[models.TargetLinkedInProfile]:
    result = db.execute(
        select(models.TargetLinkedInProfile).where(models.TargetLinkedInProfile.id == target_profile_id)
    )
    return result.scalars().first()


def update_outreach_profile_gohighlevel_location(
    db: Session,
    profile_id: int,
    gohighlevel_location_id: Optional[str],
) -> Optional[models.OutreachLinkedInProfile]:
    profile = get_outreach_profile_by_id(db, profile_id)
    if not profile:
        return None
    profile.gohighlevel_location_id = gohighlevel_location_id
    db.commit()
    db.refresh(profile)
    return profile

# --------------------------
# Target LinkedIn Profile
# --------------------------
def get_target_profile_by_url(db: Session, profile_url: str, outreach_profile_id: Optional[int] = None):
    """
    Get target profile by URL. If outreach_profile_id is provided, filter by both.
    This is important because target profiles are unique per (outreach_profile_id, profile_url).
    """
    filters = [models.TargetLinkedInProfile.profile_url == profile_url]
    if outreach_profile_id is not None:
        filters.append(models.TargetLinkedInProfile.outreach_profile_id == outreach_profile_id)
    
    result = db.execute(
        select(models.TargetLinkedInProfile).filter(*filters)
    )
    return result.scalars().first()

def create_target_profile(
    db: Session,
    profile_url: str,
    outreach_profile_id: int,
    profile_data: Optional[Dict] = None
):
    """
    Create a target profile. outreach_profile_id is required as it's part of the unique constraint.
    """
    db_profile = models.TargetLinkedInProfile(
        profile_url=profile_url,
        outreach_profile_id=outreach_profile_id
    )

    if profile_data:
        for key, value in profile_data.items():
            if hasattr(db_profile, key) and key not in ["id", "profile_url", "outreach_profile_id", "first_fetched_at", "modified_at"]:
                setattr(db_profile, key, value)
        db_profile.modified_at = datetime.now(timezone.utc)

    db.add(db_profile)
    db.commit()
    db.refresh(db_profile)
    return db_profile

def update_target_profile(
    db: Session,
    profile_url: str,
    outreach_profile_id: Optional[int] = None,
    profile_data: Optional[Dict] = None,
    create_if_not_exists: bool = True
):
    """
    Update or create a target profile.
    If outreach_profile_id is provided, use it for filtering and creation.
    """
    filters = [models.TargetLinkedInProfile.profile_url == profile_url]
    if outreach_profile_id is not None:
        filters.append(models.TargetLinkedInProfile.outreach_profile_id == outreach_profile_id)
    
    stmt = select(models.TargetLinkedInProfile).filter(*filters)
    db_profile = db.execute(stmt).scalars().first()

    if not db_profile and create_if_not_exists:
        if outreach_profile_id is None:
            raise ValueError("outreach_profile_id is required to create a new target profile")
        return create_target_profile(
            db=db,
            profile_url=profile_url,
            outreach_profile_id=outreach_profile_id,
            profile_data=profile_data
        )
    elif not db_profile:
        raise ValueError(f"Profile with URL {profile_url} not found")

    if profile_data:
        for key, value in profile_data.items():
            if hasattr(db_profile, key) and key not in ["id", "profile_url", "outreach_profile_id", "first_fetched_at", "modified_at"]:
                if value is not None:
                    setattr(db_profile, key, value)
        db_profile.modified_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(db_profile)
    return db_profile

# --------------------------
# LinkedIn Session
# --------------------------
def get_linkedin_session(db: Session, outreach_profile_id: int):
    result = db.execute(
        select(models.LinkedInSession).filter(models.LinkedInSession.outreach_profile_id == outreach_profile_id)
    )
    return result.scalars().first()

def save_linkedin_session(db: Session, outreach_profile_id: int, cookies: str, user_agent: str):
    session = get_linkedin_session(db, outreach_profile_id)
    encrypted_cookies = FERNET.encrypt(cookies.encode())

    if session:
        session.cookies = encrypted_cookies.decode()
        session.user_agent = user_agent
    else:
        # Get user_id from outreach_profile_id
        outreach_profile = get_outreach_profile_by_id(db, outreach_profile_id)
        if not outreach_profile:
            raise ValueError(f"Outreach profile with ID {outreach_profile_id} not found")
        
        session = models.LinkedInSession(
            outreach_profile_id=outreach_profile_id,
            user_id=outreach_profile.user_id,  # Add the required user_id
            cookies=encrypted_cookies.decode(),
            user_agent=user_agent,
        )
        db.add(session)

    db.commit()
    db.refresh(session)
    return session


# --------------------------
# Campaign Lead Imports
# --------------------------
def create_campaign_lead_import(
    db: Session,
    *,
    user_id: int,
    outreach_profile_id: int,
    campaign_template_id: int,
    search_url: str,
    requested_lead_count: Optional[int] = None,
    search_filters: Optional[Dict[str, Any]] = None,
    celery_task_id: Optional[str] = None,
) -> models.CampaignLeadImport:
    now = datetime.now(timezone.utc)
    lead_import = models.CampaignLeadImport(
        user_id=user_id,
        outreach_profile_id=outreach_profile_id,
        campaign_template_id=campaign_template_id,
        search_url=search_url,
        requested_lead_count=requested_lead_count,
        search_filters=search_filters or None,
        status="pending",
        celery_task_id=celery_task_id,
        created_at=now,
        updated_at=now,
    )
    db.add(lead_import)
    db.commit()
    db.refresh(lead_import)
    return lead_import


def get_campaign_lead_import_by_import_id(
    db: Session,
    import_id: uuid.UUID,
) -> Optional[models.CampaignLeadImport]:
    result = db.execute(
        select(models.CampaignLeadImport).where(models.CampaignLeadImport.import_id == import_id)
    )
    return result.scalars().first()


def get_campaign_lead_import_by_id(
    db: Session,
    lead_import_id: int,
) -> Optional[models.CampaignLeadImport]:
    result = db.execute(
        select(models.CampaignLeadImport).where(models.CampaignLeadImport.id == lead_import_id)
    )
    return result.scalars().first()


def update_campaign_lead_import(
    db: Session,
    lead_import: models.CampaignLeadImport,
    *,
    status: Optional[str] = None,
    total_extracted: Optional[int] = None,
    total_imported: Optional[int] = None,
    error: Any = UNSET,
    celery_task_id: Optional[str] = None,
    search_filters: Optional[Dict[str, Any]] = None,
    started: bool = False,
    finished: bool = False,
) -> models.CampaignLeadImport:
    now = datetime.now(timezone.utc)

    if status is not None:
        lead_import.status = status
    if total_extracted is not None:
        lead_import.total_extracted = total_extracted
    if total_imported is not None:
        lead_import.total_imported = total_imported
    if error is not UNSET:
        lead_import.error = error
    if celery_task_id is not None:
        lead_import.celery_task_id = celery_task_id
    if search_filters is not None:
        lead_import.search_filters = search_filters
    if started:
        lead_import.started_at = now
    if finished:
        lead_import.finished_at = now

    lead_import.updated_at = now

    db.add(lead_import)
    db.commit()
    db.refresh(lead_import)
    return lead_import

# --------------------------
# Action
# --------------------------
# def create_action(
#     db: Session,
#     user_id: int,
#     outreach_profile_id: int,
#     target_profile_id: int,
#     action_type: str,
#     status: str,
#     details: Optional[dict] = None,
#     chat_history_id: Optional[int] = None
# ) -> models.Action:
#     action = models.Action(
#         user_id=user_id,
#         outreach_profile_id=outreach_profile_id,
#         target_profile_id=target_profile_id,
#         action_type=action_type,
#         status=status,
#         details=details,
#         chat_history_id=chat_history_id
#     )
#     db.add(action)
#     db.commit()
#     db.refresh(action)
#     return action

# --------------------------
# Chat History
# --------------------------
def create_chat_history(
    db: Session,
    user_id: int,
    outreach_profile_id: int,
    target_profile_id: int,
    message_role: str,
    message: str,
) -> models.ChatHistory:
    chat_entry = models.ChatHistory(
        user_id=user_id,
        outreach_profile_id=outreach_profile_id,
        target_profile_id=target_profile_id,
        message_role=message_role,
        content=message
    )
    db.add(chat_entry)
    db.commit()
    db.refresh(chat_entry)
    return chat_entry

# --------------------------
# Campaign Tracking (Sync - for Celery tasks)
# --------------------------
def create_campaign_history(
    db: Session,
    user_id: int,
    campaign_runtime_id: uuid.UUID,
    outreach_profile_id: int,
    target_profile_id: int,
    campaign_template_id: int,
    number_of_steps: int,
    status: str = "active"
) -> models.CampaignHistory:
    campaign_history = models.CampaignHistory(
        user_id=user_id,
        runtime_id=campaign_runtime_id,
        outreach_profile_id=outreach_profile_id,
        target_profile_id=target_profile_id,
        campaign_template_id=campaign_template_id,
        number_of_steps=number_of_steps,
        status=status
    )
    db.add(campaign_history)
    db.commit()
    db.refresh(campaign_history)
    return campaign_history

def get_campaign_history_by_id(db: Session, campaign_history_id: int) -> Optional[models.CampaignHistory]:
    """Get campaign history by ID."""
    return db.query(models.CampaignHistory).filter(
        models.CampaignHistory.id == campaign_history_id
    ).first()

def create_campaign_step_history(
    db: Session,
    campaign_history_id: int,
    campaign_runtime_id: uuid.UUID,
    step_number: int,
    action: str,
    status: str,
    details: Optional[Dict] = None
) -> models.CampaignStepHistory:

    campaign_step_history = models.CampaignStepHistory(
        campaign_history_id=campaign_history_id,
        campaign_runtime_id=campaign_runtime_id,
        step_number=step_number,
        action=action,
        status=status,
        details=details
    )
    db.add(campaign_step_history)
    db.commit()
    db.refresh(campaign_step_history)
    return campaign_step_history

def get_campaign_history_by_runtime_id(db: Session, runtime_id: uuid.UUID) -> Optional[models.CampaignHistory]:
    """
    Get campaign history by runtime_id (UUID).
    Used in Celery tasks to track campaign progress.
    """
    return db.query(models.CampaignHistory).filter(
        models.CampaignHistory.runtime_id == runtime_id
    ).first()


def update_campaign_history_status(
    db: Session, 
    campaign_history_id: int, 
    status: str,
    finished_on_step_number: Optional[int] = None,
    details: Optional[Dict] = None
) -> models.CampaignHistory:
    """
    Update campaign history status and details.
    Used when campaign completes, fails, or is paused.
    """
    campaign_history = db.query(models.CampaignHistory).filter(
        models.CampaignHistory.id == campaign_history_id
    ).first()
    
    if not campaign_history:
        raise ValueError(f"Campaign history {campaign_history_id} not found")
    
    campaign_history.status = status
    campaign_history.modified_at = datetime.now(timezone.utc)
    
    if finished_on_step_number is not None:
        campaign_history.finished_on_step_number = finished_on_step_number
    
    if details:
        campaign_history.details = details
    
    db.commit()
    db.refresh(campaign_history)
    return campaign_history


def get_campaign_step_history(
    db: Session,
    campaign_history_id: int,
    step_number: int
) -> Optional[models.CampaignStepHistory]:
    """
    Get a specific step history record.
    """
    return db.query(models.CampaignStepHistory).filter(
        models.CampaignStepHistory.campaign_history_id == campaign_history_id,
        models.CampaignStepHistory.step_number == step_number
    ).first()


def update_campaign_step_history_status(
    db: Session,
    campaign_history_id: int,
    step_number: int,
    status: str,
    details: Optional[Dict] = None
) -> models.CampaignStepHistory:
    """
    Update a campaign step status.
    Used to track step progress: pending -> in_progress -> completed/failed
    """
    step_history = get_campaign_step_history(db, campaign_history_id, step_number)
    
    if not step_history:
        raise ValueError(f"Step history not found for campaign {campaign_history_id}, step {step_number}")
    
    step_history.status = status
    step_history.modified_at = datetime.now(timezone.utc)
    
    if details:
        step_history.details = details
    
    db.commit()
    db.refresh(step_history)
    return step_history


def create_action(
    db: Session,
    user_id: int,
    outreach_profile_id: int,
    target_profile_id: int,
    action_type: str,
    status: str,
    chat_history_id: Optional[int] = None,
    details: Optional[Dict] = None
) -> models.Action:
    """
    Create an action record for campaign tracking.
    Actions: connection_request, send_message, profile_view, etc.
    """
    action = models.Action(
        user_id=user_id,
        outreach_profile_id=outreach_profile_id,
        target_profile_id=target_profile_id,
        action_type=action_type,
        status=status,
        chat_history_id=chat_history_id,
        details=details or {}
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    logger.info(f"Action created: {action_type} for target {target_profile_id} - status: {status}")
    return action


def get_target_profile_by_id(db: Session, target_profile_id: int) -> Optional[models.TargetLinkedInProfile]:
    """
    Get target profile by ID (sync version for Celery tasks).
    """
    return db.query(models.TargetLinkedInProfile).filter(
        models.TargetLinkedInProfile.id == target_profile_id
    ).first()


def get_campaign_history_by_target_and_template(
    db: Session,
    target_profile_id: int,
    campaign_template_id: int,
    outreach_profile_id: int
) -> Optional[models.CampaignHistory]:
    """
    Get campaign history for a specific target, template, and outreach profile.
    Used to check if a campaign is already running for this target.
    """
    return db.query(models.CampaignHistory).filter(
        models.CampaignHistory.target_profile_id == target_profile_id,
        models.CampaignHistory.campaign_template_id == campaign_template_id,
        models.CampaignHistory.outreach_profile_id == outreach_profile_id,
        models.CampaignHistory.status == "active"
    ).first()


# def create_chat_history(
#     db: Session,
#     user_id: int,
#     outreach_profile_id: int,
#     target_profile_id: int,
#     message_role: str,
#     content: str
# ) -> models.ChatHistory:
#     """
#     Create a chat history record (sync version for Celery tasks).
#     message_role: 'outbound' or 'inbound'
#     """
#     chat = models.ChatHistory(
#         user_id=user_id,
#         outreach_profile_id=outreach_profile_id,
#         target_profile_id=target_profile_id,
#         message_role=message_role,
#         content=content
#     )
#     db.add(chat)
#     db.commit()
#     db.refresh(chat)
#     logger.info(f"Chat history created: {message_role} message for target {target_profile_id}")
#     return chat


def get_user_id_by_outreach_profile(db: Session, outreach_profile_id: int) -> Optional[int]:
    """
    Get user_id from outreach_profile_id.
    Helper function for Celery tasks.
    """
    outreach_profile = db.query(models.OutreachLinkedInProfile).filter(
        models.OutreachLinkedInProfile.id == outreach_profile_id
    ).first()
    
    if outreach_profile:
        return outreach_profile.user_id
    return None


def get_all_active_campaign_histories_for_target(
    db: Session,
    target_profile_id: int
) -> List[models.CampaignHistory]:
    """
    Get all active campaigns for a target profile.
    Used to check what campaigns are currently running.
    """
    return db.query(models.CampaignHistory).filter(
        models.CampaignHistory.target_profile_id == target_profile_id,
        models.CampaignHistory.status == "active"
    ).all()


def pause_all_campaigns_for_target(
    db: Session,
    target_profile_id: int,
    reason: str = "Target responded"
) -> List[models.CampaignHistory]:
    """
    Pause all active campaigns for a target.
    Used when target responds or other conditions require pausing.
    """
    active_campaigns = get_all_active_campaign_histories_for_target(db, target_profile_id)
    
    for campaign in active_campaigns:
        campaign.status = "paused"
        campaign.details = campaign.details or {}
        campaign.details["pause_reason"] = reason
        campaign.modified_at = datetime.now(timezone.utc)
    
    db.commit()
    logger.info(f"Paused {len(active_campaigns)} campaigns for target {target_profile_id}")
    return active_campaigns


# --------------------------
# Scheduled Campaign Tasks
# --------------------------

def create_scheduled_campaign_task(
    db: Session,
    target_profile_id: int,
    step_number: int,
    celery_task_id: str,
    task_name: str,
    scheduled_at: datetime,
    campaign_history_id: Optional[int] = None,
    campaign_step_history_id: Optional[int] = None,
    details: Optional[Dict] = None
) -> models.ScheduledCampaignTask:
    """
    Create a record of a scheduled Celery task for campaign step.
    """
    scheduled_task = models.ScheduledCampaignTask(
        campaign_history_id=campaign_history_id,
        campaign_step_history_id=campaign_step_history_id,
        target_profile_id=target_profile_id,
        step_number=step_number,
        celery_task_id=celery_task_id,
        task_name=task_name,
        scheduled_at=scheduled_at,
        status="scheduled",
        details=details or {}
    )
    db.add(scheduled_task)
    db.commit()
    db.refresh(scheduled_task)
    logger.info(f"Scheduled task {celery_task_id} for step {step_number} at {scheduled_at}")
    return scheduled_task


def get_scheduled_tasks_for_campaign(
    db: Session,
    campaign_history_id: int
) -> List[models.ScheduledCampaignTask]:
    """
    Get all scheduled tasks for a campaign.
    """
    return db.query(models.ScheduledCampaignTask).filter(
        models.ScheduledCampaignTask.campaign_history_id == campaign_history_id
    ).all()


def update_scheduled_task_status(
    db: Session,
    celery_task_id: str,
    status: str,
    executed_at: Optional[datetime] = None
) -> Optional[models.ScheduledCampaignTask]:
    """
    Update the status of a scheduled task.
    """
    scheduled_task = db.query(models.ScheduledCampaignTask).filter(
        models.ScheduledCampaignTask.celery_task_id == celery_task_id
    ).first()
    
    if not scheduled_task:
        return None
    
    scheduled_task.status = status
    if executed_at:
        scheduled_task.executed_at = executed_at
    
    db.commit()
    db.refresh(scheduled_task)
    return scheduled_task


def cancel_scheduled_tasks_for_campaign(
    db: Session,
    campaign_history_id: int
) -> int:
    """
    Cancel all pending scheduled tasks for a campaign.
    Returns number of tasks cancelled.
    """
    scheduled_tasks = db.query(models.ScheduledCampaignTask).filter(
        models.ScheduledCampaignTask.campaign_history_id == campaign_history_id,
        models.ScheduledCampaignTask.status == "scheduled"
    ).all()
    
    cancelled_count = 0
    for task in scheduled_tasks:
        try:
            # Revoke the Celery task
            celery_app.control.revoke(task.celery_task_id, terminate=True)
            task.status = "cancelled"
            cancelled_count += 1
        except Exception as e:
            logger.error(f"Failed to cancel task {task.celery_task_id}: {e}")
    
    db.commit()
    logger.info(f"Cancelled {cancelled_count} scheduled tasks for campaign {campaign_history_id}")
    return cancelled_count
