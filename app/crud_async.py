import uuid
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from app import models
from app.utils.helpers import extract_template_variables, normalize_timedelta_to_standard_format
from app.errors import ProfileNotFoundError
from app.settings import FERNET, PWD_CONTEXT, logger
from sqlalchemy.exc import IntegrityError


UNSET = object()

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
async def list_gohighlevel_accounts(db: AsyncSession, user_id: int) -> list[models.GoHighLevelAccount]:
    result = await db.execute(
        select(models.GoHighLevelAccount)
        .where(models.GoHighLevelAccount.user_id == user_id)
        .order_by(desc(models.GoHighLevelAccount.created_at))
    )
    return result.scalars().all()


async def get_gohighlevel_account_by_id(
    db: AsyncSession,
    account_id: int,
    *,
    user_id: Optional[int] = None,
) -> Optional[models.GoHighLevelAccount]:
    result = await db.execute(
        select(models.GoHighLevelAccount).where(models.GoHighLevelAccount.id == account_id)
    )
    account = result.scalars().first()
    if account and user_id is not None and account.user_id != user_id:
        return None
    return account


async def get_gohighlevel_account_by_location(
    db: AsyncSession,
    user_id: int,
    location_id: str,
) -> Optional[models.GoHighLevelAccount]:
    result = await db.execute(
        select(models.GoHighLevelAccount).where(
            models.GoHighLevelAccount.user_id == user_id,
            models.GoHighLevelAccount.location_id == location_id,
        )
    )
    return result.scalars().first()


async def get_default_gohighlevel_account(
    db: AsyncSession,
    user_id: int,
) -> Optional[models.GoHighLevelAccount]:
    result = await db.execute(
        select(models.GoHighLevelAccount).where(
            models.GoHighLevelAccount.user_id == user_id,
            models.GoHighLevelAccount.is_default.is_(True),
        )
    )
    return result.scalars().first()


async def _clear_default_gohighlevel_accounts(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(
        select(models.GoHighLevelAccount).where(models.GoHighLevelAccount.user_id == user_id)
    )
    accounts = result.scalars().all()
    updated = False
    for account in accounts:
        if account.is_default:
            account.is_default = False
            updated = True
    if updated:
        await db.commit()


async def set_default_gohighlevel_account(
    db: AsyncSession,
    *,
    user_id: int,
    account_id: int,
) -> Optional[models.GoHighLevelAccount]:
    account = await get_gohighlevel_account_by_id(db, account_id, user_id=user_id)
    if not account:
        return None

    result = await db.execute(
        select(models.GoHighLevelAccount).where(models.GoHighLevelAccount.user_id == user_id)
    )
    accounts = result.scalars().all()
    for record in accounts:
        record.is_default = record.id == account_id
    await db.commit()
    await db.refresh(account)
    return account


async def upsert_gohighlevel_account(
    db: AsyncSession,
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
    existing = await get_gohighlevel_account_by_location(db, user_id, location_id)

    if existing:
        existing.display_name = display_name
        existing.access_token_encrypted = _encrypt_token(access_token)
        existing.refresh_token_encrypted = _encrypt_token(refresh_token)
        existing.expires_at = expires_at
        if metadata is not None:
            existing.metadata_json = metadata
        existing.is_active = True

        if force_default:
            await set_default_gohighlevel_account(db, user_id=user_id, account_id=existing.id)
        else:
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
        return existing

    # If there is no default account yet, mark the new account as default
    should_be_default = force_default
    if not should_be_default:
        current_default = await get_default_gohighlevel_account(db, user_id)
        should_be_default = current_default is None

    if should_be_default:
        await _clear_default_gohighlevel_accounts(db, user_id)

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
    await db.commit()
    await db.refresh(account)
    return account


async def update_gohighlevel_tokens(
    db: AsyncSession,
    *,
    account_id: int,
    access_token: Optional[str] = None,
    refresh_token: Optional[str] = None,
    expires_at=None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[models.GoHighLevelAccount]:
    account = await get_gohighlevel_account_by_id(db, account_id)
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
    await db.commit()
    await db.refresh(account)
    return account


async def deactivate_gohighlevel_account(
    db: AsyncSession,
    *,
    account_id: int,
    user_id: int,
) -> Optional[models.GoHighLevelAccount]:
    account = await get_gohighlevel_account_by_id(db, account_id, user_id=user_id)
    if not account:
        return None
    account.is_active = False
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


def deserialize_gohighlevel_tokens(account: models.GoHighLevelAccount) -> Dict[str, Optional[str]]:
    return {
        "access_token": _decrypt_token(account.access_token_encrypted),
        "refresh_token": _decrypt_token(account.refresh_token_encrypted),
    }


# --------------------------
# LinkedIn Verification Flow
# --------------------------
async def get_login_code_request_by_id(
    db: AsyncSession, request_id: int
) -> Optional[models.LinkedInLoginCodeRequest]:
    result = await db.execute(
        select(models.LinkedInLoginCodeRequest).where(models.LinkedInLoginCodeRequest.id == request_id)
    )
    return result.scalars().first()


async def get_pending_login_code_request_for_outreach(
    db: AsyncSession, outreach_profile_id: int
) -> Optional[models.LinkedInLoginCodeRequest]:
    result = await db.execute(
        select(models.LinkedInLoginCodeRequest)
        .where(
            models.LinkedInLoginCodeRequest.outreach_profile_id == outreach_profile_id,
            models.LinkedInLoginCodeRequest.status == LOGIN_CODE_STATUS_PENDING,
        )
        .order_by(models.LinkedInLoginCodeRequest.created_at.desc())
    )
    return result.scalars().first()


async def create_login_code_request(
    db: AsyncSession,
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
    existing = await get_pending_login_code_request_for_outreach(db, outreach_profile_id)
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
    await db.commit()
    await db.refresh(record)
    return record


async def update_login_code_request_status(
    db: AsyncSession,
    *,
    request_id: int,
    status: str,
    status_detail: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[models.LinkedInLoginCodeRequest]:
    record = await get_login_code_request_by_id(db, request_id)
    if not record:
        return None

    now = datetime.now(timezone.utc)
    record.status = status
    if status_detail is not None:
        record.status_detail = status_detail
    record.last_status_at = now
    record.updated_at = now
    if metadata:
        payload = record.metadata_json or {}
        payload.update(metadata)
        record.metadata_json = payload
    if status in TERMINAL_LOGIN_CODE_STATUSES:
        record.resolved_at = record.resolved_at or now

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def record_verification_attempt(
    db: AsyncSession,
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
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def get_latest_verification_attempt(
    db: AsyncSession,
    *,
    request_id: int,
) -> Optional[models.LinkedInVerificationAttempt]:
    result = await db.execute(
        select(models.LinkedInVerificationAttempt)
        .where(models.LinkedInVerificationAttempt.request_id == request_id)
        .order_by(models.LinkedInVerificationAttempt.submitted_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def list_verification_attempts(
    db: AsyncSession,
    *,
    request_id: int,
) -> list[models.LinkedInVerificationAttempt]:
    result = await db.execute(
        select(models.LinkedInVerificationAttempt)
        .where(models.LinkedInVerificationAttempt.request_id == request_id)
        .order_by(models.LinkedInVerificationAttempt.submitted_at.asc())
    )
    return result.scalars().all()


async def update_verification_attempt(
    db: AsyncSession,
    *,
    attempt_id: int,
    result_value: Optional[str] = None,
    error_details: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[models.LinkedInVerificationAttempt]:
    result = await db.execute(
        select(models.LinkedInVerificationAttempt).where(models.LinkedInVerificationAttempt.id == attempt_id)
    )
    attempt = result.scalars().first()
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
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def list_pending_login_code_requests(
    db: AsyncSession,
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
    result = await db.execute(query)
    return result.scalars().all()


async def list_recent_verification_attempts(
    db: AsyncSession,
    *,
    limit: int = 250,
) -> list[models.LinkedInVerificationAttempt]:
    result = await db.execute(
        select(models.LinkedInVerificationAttempt)
        .order_by(models.LinkedInVerificationAttempt.submitted_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def create_scrape_event(
    db: AsyncSession,
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
    await db.commit()
    await db.refresh(event)
    return event


async def list_recent_scrape_events(
    db: AsyncSession,
    *,
    outreach_profile_id: Optional[int] = None,
    limit: int = 250,
) -> list[models.LinkedInScrapeEvent]:
    query = select(models.LinkedInScrapeEvent).order_by(models.LinkedInScrapeEvent.created_at.desc()).limit(limit)
    if outreach_profile_id:
        query = query.where(models.LinkedInScrapeEvent.outreach_profile_id == outreach_profile_id)
    result = await db.execute(query)
    return result.scalars().all()


# --------------------------
# Admin
# --------------------------
async def create_registration_key(db: AsyncSession, issued_to: int = None, expires_at=None) -> models.RegistrationKey:
    key = str(uuid.uuid4())
    reg_key = models.RegistrationKey(
        key=key,
        issued_to=issued_to,
        expires_at=expires_at
    )
    db.add(reg_key)
    await db.commit()
    await db.refresh(reg_key)
    return reg_key

async def get_registration_key_by_user_id(db: AsyncSession, user_id: int) -> Optional[models.RegistrationKey]:
    result = await db.execute(select(models.RegistrationKey).filter(models.RegistrationKey.issued_to == user_id))
    return result.scalars().first()

async def delete_registration_key(db: AsyncSession, issued_to: int):
    key = await get_registration_key_by_user_id(db, issued_to)
    if not key:
        return False
    await db.delete(key)
    await db.commit()
    return True



# --------------------------
# User
# --------------------------
async def create_user(db: AsyncSession, email: str, password: str) -> models.User:
    hashed_password = PWD_CONTEXT.hash(password)
    now = datetime.now(timezone.utc)
    user = models.User(
        email=email,
        password=hashed_password,
        created_at=now,
        modified_at=now
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

# async def update_user(db: AsyncSession, user: models.User, email: str = None, password: str = None) -> models.User:
#     updated = False
#     if email:
#         user.email = email
#         updated = True
#     if password:
#         user.password = PWD_CONTEXT.hash(password)
#         updated = True
    
#     if updated:
#         user.modified_at = datetime.now(timezone.utc)
#         db.add(user)
#         await db.commit()
#         await db.refresh(user)
    
#     return user

async def update_user_password(db: AsyncSession, user: models.User, password: str = None) -> models.User:
    updated = False
    if password:
        user.password = PWD_CONTEXT.hash(password)
        updated = True
    if updated:
        user.modified_at = datetime.now(timezone.utc)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user

async def update_user(db: AsyncSession, user_id: int, email: Optional[str] = None, is_admin: Optional[bool] = None) -> Optional[models.User]:
    user = await get_user_by_id(db, user_id)
    if not user:
        return None
    updated = False
    if email is not None and email != user.email:
        user.email = email
        updated = True
    if is_admin is not None and is_admin != user.is_admin:
        user.is_admin = is_admin
        updated = True
    if updated:
        user.modified_at = datetime.now(timezone.utc)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user

async def delete_user(db: AsyncSession, user_id: int) -> bool:
    user = await get_user_by_id(db, user_id)
    if not user:
        return False
    await db.delete(user)
    await db.commit()
    return True

async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[models.User]:
    result = await db.execute(select(models.User).filter(models.User.id == user_id))
    return result.scalars().first()

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[models.User]:
    result = await db.execute(select(models.User).filter(models.User.email == email))
    return result.scalars().first()

# --------------------------
# Outreach LinkedIn Profile
# --------------------------
async def create_outreach_profile(
    db: AsyncSession,
    user_id: int,
    linkedin_email: str,
    linkedin_password: str,
    linkedin_url: str,
    account_name: Optional[str] = None,
    gohighlevel_location_id: Optional[str] = None,
) -> models.OutreachLinkedInProfile:
    encrypted_password = FERNET.encrypt(linkedin_password.encode()).decode()
    db_profile = models.OutreachLinkedInProfile(
        user_id=user_id,
        linkedin_email=linkedin_email,
        linkedin_password=encrypted_password,
        linkedin_url=linkedin_url,
        account_name=account_name,
        gohighlevel_location_id=gohighlevel_location_id,
    )
    db.add(db_profile)
    await db.flush()
    await db.commit()
    await db.refresh(db_profile)
    return db_profile

async def delete_outreach_profile(db: AsyncSession, profile_id: int, user_id: int) -> bool:
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        return False
    if profile.user_id != user_id:
        return False
    
    # Delete related sessions
    session = await get_linkedin_session(db, profile_id)
    if session:
        await db.delete(session)

    await db.delete(profile)
    await db.commit()
    return True

async def update_outreach_profile_all_fields(
    db: AsyncSession,
    profile_id: int,
    update_data: Dict[str, Any]
) -> Optional[models.OutreachLinkedInProfile]:
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        return None

    if update_data.get("linkedin_email"):
        profile.linkedin_email = update_data["linkedin_email"]
    if update_data.get("linkedin_password"):
        profile.linkedin_password = FERNET.encrypt(update_data["linkedin_password"].encode()).decode()
    if update_data.get("linkedin_url"):
        profile.linkedin_url = str(update_data["linkedin_url"])
    if "account_name" in update_data:
        profile.account_name = update_data["account_name"]
    if "gohighlevel_location_id" in update_data:
        profile.gohighlevel_location_id = update_data["gohighlevel_location_id"]

    await db.commit()
    await db.refresh(profile)
    return profile

async def get_outreach_profile_stats(db: AsyncSession, profile_id: int) -> Dict[str, Any]:
    # Total campaigns
    total_campaigns = await db.scalar(
        select(func.count(models.CampaignHistory.id))
        .where(models.CampaignHistory.outreach_profile_id == profile_id)
    ) or 0

    # Active campaigns
    active_campaigns = await db.scalar(
        select(func.count(models.CampaignHistory.id))
        .where(
            models.CampaignHistory.outreach_profile_id == profile_id,
            models.CampaignHistory.status == "active"
        )
    ) or 0

    # Connections made (based on actions)
    total_connections = await db.scalar(
        select(func.count(models.Action.id))
        .where(
            models.Action.outreach_profile_id == profile_id,
            models.Action.action_type == "send_connection",
            models.Action.status == "completed" 
        )
    ) or 0
    
    # Messages sent
    total_messages = await db.scalar(
        select(func.count(models.Action.id))
        .where(
            models.Action.outreach_profile_id == profile_id,
            models.Action.action_type == "send_message",
            models.Action.status == "completed"
        )
    ) or 0
    
    # Total actions
    total_actions = await db.scalar(
        select(func.count(models.Action.id))
        .where(models.Action.outreach_profile_id == profile_id)
    ) or 0

    # Last active
    last_active = await db.scalar(
        select(func.max(models.Action.created_at))
        .where(models.Action.outreach_profile_id == profile_id)
    )

    return {
        "total_campaigns": total_campaigns,
        "active_campaigns": active_campaigns,
        "total_connections": total_connections,
        "total_messages": total_messages,
        "total_actions": total_actions,
        "last_active": last_active
    }

async def get_latest_login_code_request_for_outreach(
    db: AsyncSession, outreach_profile_id: int
) -> Optional[models.LinkedInLoginCodeRequest]:
    result = await db.execute(
        select(models.LinkedInLoginCodeRequest)
        .where(models.LinkedInLoginCodeRequest.outreach_profile_id == outreach_profile_id)
        .order_by(models.LinkedInLoginCodeRequest.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()

async def get_outreach_profile_status(db: AsyncSession, profile_id: int) -> Dict[str, Any]:
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        raise ProfileNotFoundError("Outreach profile not found")
        
    # Check session
    session = await get_linkedin_session(db, profile_id)
    session_status = "active" if session else "missing"
        
    # Check latest login request
    latest_request = await get_latest_login_code_request_for_outreach(db, profile_id)
    
    is_verified = False
    last_verified_at = None
    issues = []
    
    if latest_request:
        if latest_request.status == LOGIN_CODE_STATUS_SUCCEEDED:
             is_verified = True
             last_verified_at = latest_request.resolved_at or latest_request.updated_at
        elif latest_request.status == LOGIN_CODE_STATUS_PENDING:
            issues.append("Verification pending - awaiting code submission")
        elif latest_request.status == LOGIN_CODE_STATUS_SUBMITTED:
            issues.append("Verifying code - please wait...")
        elif latest_request.status == LOGIN_CODE_STATUS_FAILED:
            issues.append(f"Last verification failed: {latest_request.status_detail}")
        elif latest_request.status == LOGIN_CODE_STATUS_TIMED_OUT:
            issues.append("Last verification timed out - please try again")
        elif latest_request.status == LOGIN_CODE_STATUS_CANCELLED:
            issues.append("Last verification was cancelled")
    
    # Only show "No active session" if there's no other issue explaining why
    # (e.g., don't show it after a failed verification - the failure message is enough)
    if not session and not issues:
        issues.append("No active session - click 'Verify Connection' to authenticate")

    # Connection healthy?
    is_connected = session_status == "active" and (is_verified or not latest_request)
    
    # If never verified and has session, we might assume connected but unverified state? 
    # Or maybe simple existence of session implies connection? 
    # Let's assume session + no recent failure = connected.
    
    if session and not issues:
        is_connected = True
    elif issues:
        is_connected = False

    return {
        "id": profile_id,
        "is_connected": is_connected,
        "is_verified": is_verified,
        "last_verified_at": last_verified_at,
        "session_status": session_status,
        "needs_attention": len(issues) > 0,
        "issues": issues
    }


async def get_outreach_profiles_status_bulk(db: AsyncSession, profile_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not profile_ids:
        return {}
    
    sessions_result = await db.execute(
        select(models.LinkedInSession)
        .where(models.LinkedInSession.outreach_profile_id.in_(profile_ids))
    )
    sessions = {s.outreach_profile_id: s for s in sessions_result.scalars().all()}
    
    login_requests_result = await db.execute(
        select(models.LinkedInLoginCodeRequest)
        .where(models.LinkedInLoginCodeRequest.outreach_profile_id.in_(profile_ids))
        .order_by(models.LinkedInLoginCodeRequest.created_at.desc())
    )
    all_login_requests = login_requests_result.scalars().all()
    
    latest_requests = {}
    for req in all_login_requests:
        if req.outreach_profile_id not in latest_requests:
            latest_requests[req.outreach_profile_id] = req
    
    statuses = {}
    for profile_id in profile_ids:
        session = sessions.get(profile_id)
        session_status = "active" if session else "missing"
        
        latest_request = latest_requests.get(profile_id)
        
        is_verified = False
        last_verified_at = None
        issues = []
        
        if latest_request:
            if latest_request.status == LOGIN_CODE_STATUS_SUCCEEDED:
                is_verified = True
                last_verified_at = latest_request.resolved_at or latest_request.updated_at
            elif latest_request.status == LOGIN_CODE_STATUS_PENDING:
                issues.append("Verification pending - awaiting code submission")
            elif latest_request.status == LOGIN_CODE_STATUS_SUBMITTED:
                issues.append("Verifying code - please wait...")
            elif latest_request.status == LOGIN_CODE_STATUS_FAILED:
                issues.append(f"Last verification failed: {latest_request.status_detail}")
            elif latest_request.status == LOGIN_CODE_STATUS_TIMED_OUT:
                issues.append("Last verification timed out - please try again")
            elif latest_request.status == LOGIN_CODE_STATUS_CANCELLED:
                issues.append("Last verification was cancelled")
        
        # Only show "No active session" if there's no other issue explaining why
        if not session and not issues:
            issues.append("No active session - click 'Verify Connection' to authenticate")
        
        is_connected = session_status == "active" and (is_verified or not latest_request)
        
        if session and not issues:
            is_connected = True
        elif issues:
            is_connected = False
        
        statuses[profile_id] = {
            "id": profile_id,
            "is_connected": is_connected,
            "is_verified": is_verified,
            "last_verified_at": last_verified_at,
            "session_status": session_status,
            "needs_attention": len(issues) > 0,
            "issues": issues
        }
    
    return statuses


async def update_outreach_profile(
    db: AsyncSession,
    profile_id: int,
    linkedin_email: str,
    linkedin_password: str,
    linkedin_url: str
) -> Optional[models.OutreachLinkedInProfile]:
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        raise ProfileNotFoundError("Outreach profile not found")
    profile.linkedin_email = linkedin_email
    profile.linkedin_password = FERNET.encrypt(linkedin_password.encode()).decode()
    profile.linkedin_url = linkedin_url
    await db.commit()
    await db.refresh(profile)
    #profile.linkedin_password = linkedin_password
    return profile

async def update_outreach_profile_url_only(db: AsyncSession, profile_id: int, new_url: str):
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        raise ProfileNotFoundError("Outreach profile not found")
    profile.linkedin_url = new_url
    await db.commit()
    await db.refresh(profile)
    return profile

async def update_outreach_profile_email_only(db: AsyncSession, profile_id: int, new_email: str):
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        raise ProfileNotFoundError("Outreach profile not found")
    profile.linkedin_email = new_email
    await db.commit()
    await db.refresh(profile)
    return profile


async def update_outreach_profile_gohighlevel_location(
    db: AsyncSession,
    profile_id: int,
    gohighlevel_location_id: Optional[str],
) -> Optional[models.OutreachLinkedInProfile]:
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        return None
    profile.gohighlevel_location_id = gohighlevel_location_id
    await db.commit()
    await db.refresh(profile)
    return profile

async def update_outreach_profile_password_only(
    db: AsyncSession,
    profile_id: int,
    #old_password: str,
    new_password: str
) -> models.OutreachLinkedInProfile:
    profile = await get_outreach_profile_by_id(db, profile_id)
    if not profile:
        raise ProfileNotFoundError("Outreach profile not found")

    # try:
    #     decrypted_password = FERNET.decrypt(profile.linkedin_password.encode()).decode()
    # except Exception:
    #     raise DecryptionError("Failed to decrypt stored password")

    # if decrypted_password != old_password:
    #     raise ValueError("Old password does not match")

    # Encrypt and save the new password
    profile.linkedin_password = FERNET.encrypt(new_password.encode()).decode()
    await db.commit()
    await db.refresh(profile)

    return profile

async def get_outreach_profiles_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(models.OutreachLinkedInProfile).filter(models.OutreachLinkedInProfile.user_id == user_id)
    )
    return result.scalars().all()

async def get_outreach_profile_by_id(db: AsyncSession, profile_id: int):
    result = await db.execute(
        select(models.OutreachLinkedInProfile)
        .where(
            models.OutreachLinkedInProfile.id == profile_id
        )
    )
    return result.scalars().first()

async def get_outreach_profile_by_email(db: AsyncSession, email: str, user_id: int):
    result = await db.execute(
        select(models.OutreachLinkedInProfile)
        .where(
            models.OutreachLinkedInProfile.linkedin_email == email,
            models.OutreachLinkedInProfile.user_id == user_id
        )
    )
    return result.scalar_one_or_none()

async def get_outreach_profile_by_url(db: AsyncSession, url: str, user_id: int):
    result = await db.execute(
        select(models.OutreachLinkedInProfile)
        .where(
            models.OutreachLinkedInProfile.linkedin_url == url,
            models.OutreachLinkedInProfile.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


# --------------------------
# LinkedIn Session
# --------------------------
async def get_linkedin_session(db: AsyncSession, outreach_profile_id: int):
    result = await db.execute(
        select(models.LinkedInSession).filter(models.LinkedInSession.outreach_profile_id == outreach_profile_id)
    )
    return result.scalars().first()

async def save_linkedin_session(db: AsyncSession, outreach_profile_id: int, cookies: str, user_agent: str):
    session = await get_linkedin_session(db, outreach_profile_id)
    encrypted_cookies = FERNET.encrypt(cookies.encode())

    if session:
        session.cookies = encrypted_cookies.decode()
        session.user_agent = user_agent
    else:
        session = models.LinkedInSession(
            outreach_profile_id=outreach_profile_id,
            cookies=encrypted_cookies.decode(),
            user_agent=user_agent,
        )
        db.add(session)

    await db.commit()
    await db.refresh(session)
    return session


# async def get_outreach_profile_by_url(db: AsyncSession, url: str) -> Optional[models.OutreachLinkedInProfile]:
#     result = await db.execute(select(models.OutreachLinkedInProfile).filter(models.OutreachLinkedInProfile.profile_url == url))
#     return result.scalars().first()

# async def list_outreach_profiles(db: AsyncSession) -> List[models.OutreachLinkedInProfile]:
#     result = await db.execute(select(models.OutreachLinkedInProfile))
#     return result.scalars().all()

# async def get_outreach_profile_by_id(db: AsyncSession, profile_id: int) -> Optional[models.OutreachLinkedInProfile]:
#     return await db.get(models.OutreachLinkedInProfile, profile_id)

# async def get_outreach_profile_by_email(db: AsyncSession, email: str) -> Optional[models.OutreachLinkedInProfile]:
#     result = await db.execute(select(models.OutreachLinkedInProfile).filter(models.OutreachLinkedInProfile.email == email))
#     return result.scalars().first()


# --------------------------
# Target LinkedIn Profile
# --------------------------

async def get_target_profile_by_url(db: AsyncSession, profile_url: str):
    result = await db.execute(
        select(models.TargetLinkedInProfile).filter(models.TargetLinkedInProfile.profile_url == profile_url)
    )
    return result.scalars().first()



# async def create_target_profile(
#     db: AsyncSession,
#     url: str,
#     user_ids: List[int]
# ):
#     db_profile = models.TargetLinkedInProfile(profile_url=url)
#     if user_ids:
#         result = await db.execute(select(models.User).filter(models.User.id.in_(user_ids)))
#         db_profile.users = result.scalars().all()
#     db.add(db_profile)
#     await db.commit()
#     await db.refresh(db_profile)
#     return db_profile

async def create_target_profile(
    db: AsyncSession,
    outreach_profile_id: int,
    target_url: str
):
    db_profile = models.TargetLinkedInProfile(outreach_profile_id=outreach_profile_id, profile_url=target_url)
    # if user_ids:
    #     result = await db.execute(select(models.User).filter(models.User.id.in_(user_ids)))
    #     db_profile.users = result.scalars().all()
    db.add(db_profile)
    await db.commit()
    await db.refresh(db_profile)
    return db_profile

async def bulk_create_target_profiles(
    db: AsyncSession,
    outreach_profile_id: int,
    target_urls: list[str],
) -> list[models.TargetLinkedInProfile]:
    """
    Create multiple TargetLinkedInProfile records for a given outreach profile.
    Returns existing profiles if they already exist, creates new ones for new URLs.
    Returns the complete list of ORM objects (both existing and newly created).
    """
    # Remove duplicates within the provided list while preserving order and skipping blanks
    seen_urls: set[str] = set()
    unique_urls: list[str] = []
    for raw_url in target_urls:
        normalized_url = (raw_url or "").strip()
        if not normalized_url or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        unique_urls.append(normalized_url)

    if not unique_urls:
        logger.info("No target profile URLs provided after deduplication.")
        return []

    # Get existing profiles for this outreach_profile
    existing_profiles_result = await db.execute(
        select(models.TargetLinkedInProfile)
        .where(
            models.TargetLinkedInProfile.outreach_profile_id == outreach_profile_id,
            models.TargetLinkedInProfile.profile_url.in_(unique_urls)
        )
    )
    existing_profiles = existing_profiles_result.scalars().all()
    existing_urls = {profile.profile_url for profile in existing_profiles}

    # Filter out existing URLs to find new ones
    new_urls = [url for url in unique_urls if url not in existing_urls]

    # Prepare ORM objects for new profiles
    new_profiles = []
    if new_urls:
        new_profiles = [
            models.TargetLinkedInProfile(
                outreach_profile_id=outreach_profile_id,
                profile_url=url
            )
            for url in new_urls
        ]

        # Add and commit all new profiles at once
        db.add_all(new_profiles)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            logger.exception(
                "Failed to bulk insert target profiles due to integrity error.",
                extra={"outreach_profile_id": outreach_profile_id, "urls": new_urls},
            )
            raise

        # Refresh only newly added objects (they were committed successfully)
        for obj in new_profiles:
            await db.refresh(obj)

    # Combine existing and new profiles, maintaining the order of input URLs
    all_profiles = []
    url_to_profile = {profile.profile_url: profile for profile in existing_profiles + new_profiles}
    
    for url in unique_urls:
        if url in url_to_profile:
            all_profiles.append(url_to_profile[url])

    logger.info(f"Bulk create target profiles: {len(existing_profiles)} existing, {len(new_profiles)} new, {len(all_profiles)} total")
    
    return all_profiles


# --------------------------
# Target Contact Info
# --------------------------
async def get_target_contact_info(db: AsyncSession, target_profile_id: int) -> Optional[models.TargetContactInfo]:
    result = await db.execute(
        select(models.TargetContactInfo).where(models.TargetContactInfo.target_profile_id == target_profile_id)
    )
    return result.scalars().first()


async def upsert_target_contact_info(
    db: AsyncSession,
    *,
    target_profile_id: int,
    outreach_profile_id: int,
    gohighlevel_account_id: Optional[int],
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
    record = await get_target_contact_info(db, target_profile_id)
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
        record.gohighlevel_account_id = gohighlevel_account_id
    else:
        record = models.TargetContactInfo(
            target_profile_id=target_profile_id,
            outreach_profile_id=outreach_profile_id,
            gohighlevel_account_id=gohighlevel_account_id,
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

    await db.commit()
    await db.refresh(record)
    return record


async def update_contact_sync_status(
    db: AsyncSession,
    *,
    target_profile_id: int,
    sync_status: str,
    sync_error: Optional[str] = None,
    last_synced_at=None,
    ghl_contact_id: Optional[str] = None,
) -> Optional[models.TargetContactInfo]:
    record = await get_target_contact_info(db, target_profile_id)
    if not record:
        return None

    record.sync_status = sync_status
    record.sync_error = sync_error
    record.last_synced_at = last_synced_at
    if ghl_contact_id is not None:
        record.ghl_contact_id = ghl_contact_id

    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record

# --------------------------
# Campaign Lead Imports
# --------------------------
async def create_campaign_lead_import(
    db: AsyncSession,
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
    await db.commit()
    await db.refresh(lead_import)
    return lead_import


async def get_campaign_lead_import_by_import_id(
    db: AsyncSession,
    import_id: uuid.UUID,
) -> Optional[models.CampaignLeadImport]:
    result = await db.execute(
        select(models.CampaignLeadImport).where(models.CampaignLeadImport.import_id == import_id)
    )
    return result.scalars().first()


async def update_campaign_lead_import(
    db: AsyncSession,
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
    await db.commit()
    await db.refresh(lead_import)
    return lead_import


async def list_campaign_lead_imports_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 50,
) -> list[models.CampaignLeadImport]:
    result = await db.execute(
        select(models.CampaignLeadImport)
        .where(models.CampaignLeadImport.user_id == user_id)
        .order_by(models.CampaignLeadImport.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()



# async def update_target_profile(
#     db: AsyncSession,
#     profile_url: str,
#     profile_data: Optional[Dict] = None,
#     user_ids: Optional[List[int]] = None,
#     create_if_not_exists: bool = True
# ):
#     result = await db.execute(
#         select(models.TargetLinkedInProfile).filter(models.TargetLinkedInProfile.profile_url == profile_url)
#     )
#     db_profile = result.scalars().first()

#     if not db_profile and create_if_not_exists:
#         return await create_target_profile(db, profile_url, user_ids)
#     elif not db_profile:
#         raise ValueError(f"Profile with URL {profile_url} not found")

#     if profile_data:
#         for key, value in profile_data.items():
#             if hasattr(db_profile, key) and key not in ["id", "profile_url", "first_fetched_at", "modified_at"]:
#                 setattr(db_profile, key, value)
#         db_profile.modified_at = datetime.now(timezone.utc)

#     if user_ids is not None:
#         result = await db.execute(select(models.User).filter(models.User.id.in_(user_ids)))
#         db_profile.users = result.scalars().all()

#     await db.commit()
#     await db.refresh(db_profile)
#     return db_profile


async def get_target_profiles_by_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(models.TargetLinkedInProfile)
        .join(models.user_target_profiles)
        .filter(models.user_target_profiles.c.user_id == user_id)
    )
    return result.scalars().all()



# async def create_target_profile(
#     db: AsyncSession, 
#     user_id: int,
#     profile_url: str,
#     profile_data: Optional[dict] = None
# ) -> models.TargetLinkedInProfile:
#     if profile_data:
#         db_profile = models.TargetLinkedInProfile(profile_url=profile_url, profile_data=profile_data)
#     else:
#         db_profile = models.TargetLinkedInProfile(profile_url=profile_url)
    
#     user = await get_user_by_id(db, user_id)
#     if user:
#         db_profile.user = user
#         db.add(db_profile)
#         await db.commit()
#         await db.refresh(db_profile)
#         return db_profile

# async def update_target_profile(
#     db: AsyncSession,
#     user_id: int,
#     profile_url: str,
#     profile_data: Optional[dict] = None,
#     create_if_not_exists: bool = True
# ) -> models.TargetLinkedInProfile:
#     # Check if profile exists
#     result = await db.execute(
#         select(models.TargetLinkedInProfile).filter(models.TargetLinkedInProfile.profile_url == profile_url)
#     )
#     db_profile = result.scalars().first()

#     if not db_profile and create_if_not_exists:
#         # Create new profile if it doesn't exist
#         return await create_target_profile(db, user_id, profile_url)
#     elif not db_profile:
#         # Raise error if profile doesn't exist and create_if_not_exists is False
#         raise ValueError(f"Profile with URL {profile_url} not found")

#     # Update profile attributes
#     if profile_data:
#         for key, value in profile_data.items():
#             if hasattr(db_profile, key) and key not in ["id", "profile_url", "first_fetched_at", "modified_at"]:
#                 setattr(db_profile, key, value)
#         db_profile.modified_at = datetime.now(timezone.utc)

#     # Update users relationship
#     user = await get_user_by_id(db, user_id)
#     if user:
#         db_profile.user = user
#         db.add(db_profile)
#         await db.commit()
#         await db.refresh(db_profile)
#         return db_profile

# async def get_target_profile_by_url(db: AsyncSession, url: str) -> Optional[models.TargetLinkedInProfile]:
#     result = await db.execute(select(models.TargetLinkedInProfile).filter(models.TargetLinkedInProfile.profile_url == url))
#     return result.scalars().first()


# async def list_target_profiles(db: AsyncSession) -> List[models.TargetLinkedInProfile]:
#     result = await db.execute(select(models.TargetLinkedInProfile))
#     return result.scalars().all()


# async def link_user_to_target_profile(db: AsyncSession, user_id: int, profile_id: int) -> Optional[models.TargetLinkedInProfile]:
#     user = await get_user_by_id(db, user_id)
#     profile = await db.get(models.TargetLinkedInProfile, profile_id)
#     if user and profile:
#         user.target_profiles.append(profile)
#         await db.commit()
#         await db.refresh(profile)
#         return profile
#     return None





# --------------------------
# Actions
# --------------------------
# async def create_action_async(
#     db: AsyncSession,
#     user_id: int,
#     outreach_profile_id: int,
#     target_profile_id: int,
#     action_type: str,
#     status: str,
#     details: Optional[dict] = None,
# ) -> models.Action:
#     action = models.Action(
#         user_id=user_id,
#         outreach_profile_id=outreach_profile_id,
#         target_profile_id=target_profile_id,
#         action_type=action_type,
#         status=status,
#         details=details,
#     )
#     db.add(action)
#     await db.commit()
#     await db.refresh(action)
#     return action



async def list_actions_for_user(db: AsyncSession, user_id: int) -> List[models.Action]:
    result = await db.execute(select(models.Action).filter(models.Action.user_id == user_id))
    return result.scalars().all()


async def list_actions_for_target_profile(db: AsyncSession, target_profile_id: int) -> List[models.Action]:
    result = await db.execute(select(models.Action).filter(models.Action.target_profile_id == target_profile_id))
    return result.scalars().all()


async def list_actions_for_outreach_profile(db: AsyncSession, outreach_profile_id: int) -> List[models.Action]:
    result = await db.execute(select(models.Action).filter(models.Action.outreach_profile_id == outreach_profile_id))
    return result.scalars().all()


async def list_actions_for_status(db: AsyncSession, status: str) -> List[models.Action]:
    result = await db.execute(select(models.Action).filter(models.Action.status == status))
    return result.scalars().all()


async def update_action_status(db: AsyncSession, action_id: int, status: str) -> Optional[models.Action]:
    action = await db.get(models.Action, action_id)
    if not action:
        return None
    action.status = status
    action.modified_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(action)
    return action

# --------------------------
# Celery tasks
# --------------------------
async def get_task_result(db: AsyncSession, task_id: str):
    result = await db.execute(
        select(models.Action).filter(models.Action.details["task_id"].astext == task_id)
    )
    return result.scalars().first()

# --------------------------
# Chat History
# --------------------------

async def list_chat_history_for_user(db: AsyncSession, user_id: int) -> List[models.ChatHistory]:
    result = await db.execute(select(models.ChatHistory).filter(models.ChatHistory.user_id == user_id))
    return result.scalars().all()

# async def list_chat_history_for_outreach_profile(db: AsyncSession, outreach_profile_id: int) -> List[models.ChatHistory]:
#     result = await db.execute(select(models.ChatHistory).filter(models.ChatHistory.outreach_profile_id == outreach_profile_id))
#     return result.scalars().all()

# async def list_chat_history_for_target_profile(db: AsyncSession, target_profile_id: int) -> List[models.ChatHistory]:
#     result = await db.execute(select(models.ChatHistory).filter(models.ChatHistory.target_profile_id == target_profile_id))
#     return result.scalars().all()

async def list_one_chat_history(db: AsyncSession, outreach_profile_id: int, target_profile_id: int) -> List[models.ChatHistory]:
    result = await db.execute(
        select(models.ChatHistory).filter(
            models.ChatHistory.outreach_profile_id == outreach_profile_id,
            models.ChatHistory.target_profile_id == target_profile_id
        )
    )
    return result.scalars().all()

# async def create_chat_history(
#     db: AsyncSession,
#     user_id: int,
#     outreach_profile_id: int,
#     target_profile_id: int,
#     message_role: str,
#     message: str,
# ) -> models.ChatHistory:
#     chat_entry = models.ChatHistory(
#         user_id=user_id,
#         outreach_profile_id=outreach_profile_id,
#         target_profile_id=target_profile_id,
#         message_role=message_role,
#         content=message
#     )
#     db.add(chat_entry)
#     await db.commit()
#     await db.refresh(chat_entry)
#     return chat_entry



# --------------------------
# Campaign Templates
# --------------------------
async def create_campaign_template_record(
    db: AsyncSession,
    user_id: int,
    #number_of_steps: int,
    payload_steps: List[dict],
    name: Optional[str],
    description: Optional[str],
) -> dict:
    
    # Create the campaign template
    new_campaign_template = models.CampaignTemplate(
        user_id=user_id,
        name=name,
        description=description,
        number_of_steps=len(payload_steps),
        created_at=datetime.now(timezone.utc),
    )
    db.add(new_campaign_template)
    await db.flush()  # make new_campaign.id available before commit

    step_templates = []
    all_variables = []
    # Create the steps
    for step in payload_steps:
        # Extract variables from both message_template and additional_note_template
        all_step_variables = set()
        
        # Extract from message template
        if step.message_template:
            try:
                message_vars = extract_template_variables(step.message_template)
                all_step_variables.update(message_vars)
                logger.info(f"Extracted variables from message template: {message_vars}")
            except Exception as e:
                logger.error(f"Error extracting variables from message template '{step.message_template}': {e}")

        # Extract from additional note template
        if step.additional_note_template:
            try:
                note_vars = extract_template_variables(step.additional_note_template)
                all_step_variables.update(note_vars)
                logger.info(f"Extracted variables from additional note template: {note_vars}")
            except Exception as e:
                logger.error(f"Error extracting variables from additional note template '{step.additional_note_template}': {e}")

        # Convert to list for database storage (PostgreSQL ARRAY)
        variables_list = list(all_step_variables)
        logger.info(f"Final variables list for step {step.step_number}: {variables_list}")

        # Normalize delay_timestamp to ensure consistent database storage format
        normalized_delay = normalize_timedelta_to_standard_format(step.delay_timestamp)
        logger.info(f"Normalized delay_timestamp for step {step.step_number}: {normalized_delay}")

        step_templates.append(
            models.CampaignStepTemplate(
                campaign_template_id=new_campaign_template.id,
                step_number=step.step_number,
                action=step.action,
                additional_note_template=step.additional_note_template,
                delay_timestamp=normalized_delay,  # Use normalized timedelta
                message_template=step.message_template,
                variables=variables_list  # Use the properly formatted list
            )
        )
        
    db.add_all(step_templates)
    await db.commit()
    await db.refresh(new_campaign_template)

    all_variables.extend(variables_list)

    return {
        "template": new_campaign_template,
        "required_variables": all_variables
    }

async def get_required_variables_for_template(db: AsyncSession, template_id: int) -> list[str]:
    result = await db.execute(
        select(models.CampaignStepTemplate).where(models.CampaignStepTemplate.campaign_template_id == template_id)
    )

    steps = result.scalars().all()  # ✅ returns list of ORM objects

    # Collect all step.variables lists, skipping None
    all_vars = [set(step.variables or []) for step in steps]

    # Flatten and deduplicate
    variables = sorted(set().union(*all_vars)) if all_vars else []
    return variables

async def get_template_by_id(db: AsyncSession, campaign_template_id: int):
    campaign_template = await db.execute(
        select(models.CampaignTemplate).where(models.CampaignTemplate.id == campaign_template_id)
    )
    return campaign_template.scalars().first()

async def get_step_templates_by_id(db: AsyncSession, campaign_template_id: int):
    step_templates = await db.execute(
        select(models.CampaignStepTemplate)
        .where(models.CampaignStepTemplate.campaign_template_id == campaign_template_id)
        .order_by(models.CampaignStepTemplate.step_number)
    )
    return step_templates.scalars().all()

# --------------------------
# Campaign History
# --------------------------
async def bulk_create_campaign_histories_with_steps(
    db: AsyncSession,
    user_id: int,
    outreach_profile_id: int,
    campaign_template_id: int,
    target_profile_ids: list[int],
    step_templates: list,
) -> tuple[list[models.CampaignHistory], list[models.CampaignStepHistory], list[models.Action]]:
    """
    Create campaign histories, their step histories, and corresponding action records in bulk.
    Every campaign step creates an action record for tracking purposes.
    """
    # --- 1️⃣ Create CampaignHistory rows ---
    histories = [
        models.CampaignHistory(
            user_id=user_id,
            outreach_profile_id=outreach_profile_id,
            target_profile_id=target_profile_id,
            campaign_template_id=campaign_template_id,
            number_of_steps=len(step_templates),
            status="active",
            details={"message": "campaign_started_successfully"}
        )
        for target_profile_id in target_profile_ids
    ]

    db.add_all(histories)
    await db.flush()  # flush to get `id` for each history

    # --- 2️⃣ Create CampaignStepHistory and Action rows ---
    step_histories = []
    actions = []
    
    for history in histories:
        for step in step_templates:
            # Create step history record
            step_history = models.CampaignStepHistory(
                campaign_history_id=history.id,
                campaign_runtime_id=history.runtime_id,
                step_number=step.step_number,
                action=step.action,
                status="pending",
                details={"message": "step_created_successfully"}
            )
            step_histories.append(step_history)
            
            # Create corresponding action record for tracking
            action = models.Action(
                user_id=user_id,
                target_profile_id=history.target_profile_id,
                outreach_profile_id=history.outreach_profile_id,
                action_type=step.action,
                status="pending",
                details={"message": "action_created_for_campaign_step"}
            )
            actions.append(action)

    db.add_all(step_histories)
    db.add_all(actions)
    await db.commit()

    return (histories, step_histories, actions)


async def get_campaign_history_by_id(db: AsyncSession, campaign_history_id: int):
    history = await db.execute(
        select(models.CampaignHistory)
        .where(
            models.CampaignHistory.id == campaign_history_id
        )
    )
    return history.scalars().first()

async def get_campaign_steps_history_by_history_id(db: AsyncSession, campaign_history_id: int):
    steps = await db.execute(
        select(models.CampaignStepHistory)
        .where(models.CampaignStepHistory.campaign_history_id == campaign_history_id)
        .order_by(models.CampaignStepHistory.step_number)
    )
    return steps.scalars().all()

async def get_latest_campaign_step_by_history_id(db: AsyncSession, campaign_history_id: int) -> int|None:
    result = await db.execute(
        select(models.CampaignStepHistory)
        .where(models.CampaignStepHistory.campaign_history_id == campaign_history_id)
        .order_by(desc(models.CampaignStepHistory.step_number))
        .limit(1)
    )
    return result.scalar_one_or_none()

async def get_campaigns_by_user_id(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(models.CampaignHistory)
        .where(models.CampaignHistory.user_id == user_id)
        .order_by(desc(models.CampaignHistory.started_at))
    )
    return result.scalars().all()

async def get_target_profile_count_for_campaign(db: AsyncSession, campaign_history_id: int) -> int|None:
    """
    Return number of unique target profiles associated with a campaign run.
    """
    result = await db.execute(
        select(func.count(func.distinct(models.CampaignHistory.target_profile_id)))
        .where(models.CampaignHistory.campaign_history_id == campaign_history_id)
    )
    return result.scalar_one_or_none()




# async def create_campaign_history_record(
#         db: AsyncSession,
#         user_id: int,
#         outreach_profile_id: int,
#         target_profile_id: int,
#         campaign_template_id: int,
#         campaign_step: int,
#         number_of_steps: int,
#         step_templates: List[models.CampaignStepTemplate]
# ):
#     history_entry = models.CampaignHistory(
#         user_id=user_id,
#         outreach_profile_id=outreach_profile_id,
#         target_profile_id=target_profile_id,
#         campaign_template_id=campaign_template_id,
#         number_of_steps=number_of_steps,
#         status="active",
#     )
#     db.add(history_entry)
#     history_obj = await db.flush()

#         # Initialize step history entries
#         for step in step_templates:
#             db.add(
#                 models.CampaignStepHistory(
#                     campaign_history_id=history.id,
#                     step_number=step.step_number,
#                     action=step.action,
#                     status="pending",
#                 )
#             )
#         campaign_histories.append(history)

#     await db.commit()


async def list_campaign_histories_by_user(
    db: AsyncSession,
    user_id: int,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[models.CampaignHistory]:
    from sqlalchemy.orm import selectinload
    
    query = select(models.CampaignHistory).where(
        models.CampaignHistory.user_id == user_id
    ).options(
        selectinload(models.CampaignHistory.target_profile),
        selectinload(models.CampaignHistory.outreach_profile),
        selectinload(models.CampaignHistory.campaign_template),
    )
    
    if status:
        query = query.where(models.CampaignHistory.status == status)
    
    query = query.order_by(desc(models.CampaignHistory.started_at)).limit(limit).offset(offset)
    
    result = await db.execute(query)
    return result.scalars().all()


async def list_campaign_templates_by_user(
    db: AsyncSession,
    user_id: int
) -> List[models.CampaignTemplate]:
    result = await db.execute(
        select(models.CampaignTemplate)
        .where(models.CampaignTemplate.user_id == user_id)
        .order_by(desc(models.CampaignTemplate.created_at))
    )
    return result.scalars().all()


async def get_campaign_detail_with_steps(
    db: AsyncSession,
    campaign_history_id: int
) -> Optional[models.CampaignHistory]:
    result = await db.execute(
        select(models.CampaignHistory)
        .where(models.CampaignHistory.id == campaign_history_id)
        .options(
            selectinload(models.CampaignHistory.target_profile),
            selectinload(models.CampaignHistory.outreach_profile),
            selectinload(models.CampaignHistory.campaign_template)
        )
    )
    campaign = result.scalar_one_or_none()
    
    if campaign:
        step_result = await db.execute(
            select(models.CampaignStepHistory)
            .where(models.CampaignStepHistory.campaign_history_id == campaign_history_id)
            .order_by(models.CampaignStepHistory.step_number)
        )
        campaign.step_histories = step_result.scalars().all()
    
    return campaign


async def get_scheduled_tasks_by_campaign(
    db: AsyncSession,
    campaign_history_id: int
) -> List[models.ScheduledCampaignTask]:
    result = await db.execute(
        select(models.ScheduledCampaignTask)
        .where(models.ScheduledCampaignTask.campaign_history_id == campaign_history_id)
        .order_by(models.ScheduledCampaignTask.scheduled_at)
    )
    return result.scalars().all()
