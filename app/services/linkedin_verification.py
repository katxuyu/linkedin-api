from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from app import models
from app.crud_sync import (
    create_login_code_request,
    update_login_code_request_status,
    record_verification_attempt,
    create_scrape_event,
    get_login_code_request_by_id,
    get_pending_login_code_request_for_outreach,
    LOGIN_CODE_STATUS_PENDING,
    LOGIN_CODE_STATUS_SUBMITTED,
    TERMINAL_LOGIN_CODE_STATUSES,
    DEFAULT_LOGIN_CODE_TTL_SECONDS,
)
from app.redis import (
    acquire_login_code_lock,
    refresh_login_code_lock,
    release_login_code_lock,
    get_login_code_lock_ttl,
)
from app.settings import logger


@dataclass
class ManualVerificationState:
    request_id: int
    outreach_profile_id: int
    target_profile_id: Optional[int]
    campaign_history_id: Optional[int]
    status: str
    request_type: str
    expires_at: datetime
    remaining_seconds: int
    pending_reason: Optional[str]
    status_detail: Optional[str]
    metadata: Dict[str, Any]

    @classmethod
    def from_request(cls, request: models.LinkedInLoginCodeRequest) -> "ManualVerificationState":
        now = datetime.now(timezone.utc)
        remaining = max(0, int((request.expires_at - now).total_seconds()))
        return cls(
            request_id=request.id,
            outreach_profile_id=request.outreach_profile_id,
            target_profile_id=request.target_profile_id,
            campaign_history_id=request.campaign_history_id,
            status=request.status,
            request_type=request.request_type,
            expires_at=request.expires_at,
            remaining_seconds=remaining,
            pending_reason=request.pending_reason,
            status_detail=request.status_detail,
            metadata=(request.metadata_json or {}).copy(),
        )

    @property
    def is_expired(self) -> bool:
        return self.remaining_seconds <= 0


class LinkedInVerificationService:
    """
    Orchestrates manual verification flows shared between Celery workers,
    FastAPI endpoints, and the LinkedIn microservice.
    """

    def __init__(self, db: Session):
        self.db = db

    def _ensure_lock(self, outreach_profile_id: int, ttl_seconds: int) -> bool:
        if acquire_login_code_lock(outreach_profile_id, ttl_seconds=ttl_seconds):
            return True
        existing = get_pending_login_code_request_for_outreach(self.db, outreach_profile_id)
        if existing:
            logger.info(
                "Lock already held for outreach_profile_id=%s (request_id=%s)",
                outreach_profile_id,
                existing.id,
            )
            return False
        # stale lock - release and reacquire
        logger.warning("Stale login-code lock detected for outreach_profile_id=%s, releasing.", outreach_profile_id)
        release_login_code_lock(outreach_profile_id)
        return acquire_login_code_lock(outreach_profile_id, ttl_seconds=ttl_seconds)

    def open_manual_verification_window(
        self,
        *,
        outreach_profile_id: int,
        request_type: str = "login",
        target_profile_id: Optional[int] = None,
        campaign_history_id: Optional[int] = None,
        pending_reason: Optional[str] = None,
        ttl_seconds: int = DEFAULT_LOGIN_CODE_TTL_SECONDS,
        metadata: Optional[Dict[str, Any]] = None,
        two_captcha_job_id: Optional[str] = None,
    ) -> ManualVerificationState:
        lock_acquired = self._ensure_lock(outreach_profile_id, ttl_seconds)
        record = create_login_code_request(
            self.db,
            outreach_profile_id=outreach_profile_id,
            request_type=request_type,
            target_profile_id=target_profile_id,
            campaign_history_id=campaign_history_id,
            pending_reason=pending_reason,
            ttl_seconds=ttl_seconds,
            metadata=metadata,
            two_captcha_job_id=two_captcha_job_id,
        )
        if lock_acquired:
            logger.info(
                "Manual verification request created request_id=%s outreach_profile_id=%s",
                record.id,
                outreach_profile_id,
            )
        return ManualVerificationState.from_request(record)

    def refresh_window(self, request_id: int, ttl_seconds: int = DEFAULT_LOGIN_CODE_TTL_SECONDS) -> Optional[int]:
        request = get_login_code_request_by_id(self.db, request_id)
        if not request:
            return None
        refresh_login_code_lock(request.outreach_profile_id, ttl_seconds=ttl_seconds)
        return get_login_code_lock_ttl(request.outreach_profile_id)

    def submit_attempt(
        self,
        *,
        request_id: int,
        code_value: Optional[str],
        submitted_by: Optional[str],
        submitted_by_user_id: Optional[int],
        source: str,
        two_captcha_used: bool = False,
        result: Optional[str] = None,
        error_details: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> models.LinkedInVerificationAttempt:
        update_login_code_request_status(
            self.db,
            request_id=request_id,
            status=LOGIN_CODE_STATUS_SUBMITTED,
            status_detail="Awaiting worker processing",
        )
        attempt = record_verification_attempt(
            self.db,
            request_id=request_id,
            source=source,
            submitted_by=submitted_by,
            submitted_by_user_id=submitted_by_user_id,
            code_value=code_value,
            result=result,
            error_details=error_details,
            two_captcha_used=two_captcha_used,
            metadata=metadata,
        )
        logger.info(
            "Verification attempt recorded request_id=%s attempt_id=%s source=%s",
            request_id,
            attempt.id,
            source,
        )
        return attempt

    def resolve_request(
        self,
        *,
        request_id: int,
        status: str,
        status_detail: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        event_detail: Optional[str] = None,
        action_taken: Optional[str] = None,
        event_type: Optional[str] = None,
        two_captcha_used: bool = False,
    ) -> Optional[ManualVerificationState]:
        record = update_login_code_request_status(
            self.db,
            request_id=request_id,
            status=status,
            status_detail=status_detail,
            metadata=metadata,
        )
        if not record:
            return None

        if status in TERMINAL_LOGIN_CODE_STATUSES:
            release_login_code_lock(record.outreach_profile_id)
            if event_type:
                create_scrape_event(
                    self.db,
                    outreach_profile_id=record.outreach_profile_id,
                    event_type=event_type,
                    target_profile_id=record.target_profile_id,
                    campaign_history_id=record.campaign_history_id,
                    login_code_request_id=record.id,
                    detail=event_detail,
                    action_taken=action_taken,
                    two_captcha_used=two_captcha_used,
                    metadata=metadata,
                )
        return ManualVerificationState.from_request(record)


__all__ = [
    "LinkedInVerificationService",
    "ManualVerificationState",
]

