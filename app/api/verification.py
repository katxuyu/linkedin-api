from typing import Generator, List, Optional, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import schemas, crud_sync, models
from app.database import SyncSessionLocal
from app.dependencies import get_current_user
from app.services.linkedin_verification import LinkedInVerificationService, ManualVerificationState

router = APIRouter(prefix="/internal/verification", tags=["verification"])


def get_sync_db() -> Generator[Session, None, None]:
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _state_to_response(state: ManualVerificationState) -> schemas.LoginCodeRequestResponse:
    return schemas.LoginCodeRequestResponse(
        id=state.request_id,
        outreach_profile_id=state.outreach_profile_id,
        target_profile_id=state.target_profile_id,
        campaign_history_id=state.campaign_history_id,
        status=state.status,
        request_type=state.request_type,
        expires_at=state.expires_at,
        remaining_seconds=state.remaining_seconds,
        pending_reason=state.pending_reason,
        status_detail=state.status_detail,
        metadata=state.metadata,
    )


def _format_code_request_details(
    request: models.LinkedInLoginCodeRequest,
    outreach: models.OutreachLinkedInProfile,
    target: Optional[models.TargetLinkedInProfile],
    attempts: List[models.LinkedInVerificationAttempt],
) -> schemas.CodeRequestDetails:
    state = ManualVerificationState.from_request(request)
    attempt_payloads = [
        schemas.LoginCodeAttemptResponse.model_validate(item) for item in attempts
    ]
    latest_attempt = attempt_payloads[0] if attempt_payloads else None
    metadata = state.metadata or request.metadata_json or None
    return schemas.CodeRequestDetails(
        id=state.request_id,
        outreach_profile_id=state.outreach_profile_id,
        outreach_email=outreach.linkedin_email,
        outreach_linkedin_url=outreach.linkedin_url,
        target_profile_id=state.target_profile_id,
        target_name=target.name if target else None,
        target_url=target.profile_url if target else None,
        campaign_history_id=state.campaign_history_id,
        status=state.status,
        request_type=state.request_type,
        expires_at=state.expires_at,
        remaining_seconds=state.remaining_seconds,
        pending_reason=state.pending_reason,
        status_detail=state.status_detail,
        resolved_at=request.resolved_at,
        last_status_at=request.last_status_at,
        two_captcha_job_id=request.two_captcha_job_id,
        metadata=metadata,
        created_at=request.created_at,
        latest_attempt=latest_attempt,
        attempts=attempt_payloads,
    )


@router.post("/requests", response_model=schemas.LoginCodeRequestResponse)
def create_login_code_request(
    payload: schemas.LoginCodeRequestCreate,
    db: Session = Depends(get_sync_db),
):
    service = LinkedInVerificationService(db)
    state = service.open_manual_verification_window(
        outreach_profile_id=payload.outreach_profile_id,
        request_type=payload.request_type,
        target_profile_id=payload.target_profile_id,
        campaign_history_id=payload.campaign_history_id,
        pending_reason=payload.pending_reason,
        ttl_seconds=payload.ttl_seconds or 1800,
        metadata=payload.metadata,
        two_captcha_job_id=payload.two_captcha_job_id,
    )
    return _state_to_response(state)


@router.get("/requests/{request_id}", response_model=schemas.LoginCodeRequestResponse)
def get_login_code_request(
    request_id: int,
    db: Session = Depends(get_sync_db),
):
    record = crud_sync.get_login_code_request_by_id(db, request_id)
    if not record:
        raise HTTPException(status_code=404, detail="Verification request not found")
    state = ManualVerificationState.from_request(record)
    return _state_to_response(state)


@router.get("/code-requests", response_model=schemas.CodeRequestListResponse)
async def list_code_requests_for_user(
    db: Session = Depends(get_sync_db),
    current_user: models.User = Depends(get_current_user),
):
    # Pending: waiting for code or submitted but not yet resolved
    pending_statuses = [
        crud_sync.LOGIN_CODE_STATUS_PENDING,
        crud_sync.LOGIN_CODE_STATUS_SUBMITTED,
    ]
    # Succeeded: verification passed
    succeeded_statuses = [
        crud_sync.LOGIN_CODE_STATUS_SUCCEEDED,
    ]
    # Errored: failed, expired (timed_out), or cancelled
    errored_statuses = [
        crud_sync.LOGIN_CODE_STATUS_FAILED,
        crud_sync.LOGIN_CODE_STATUS_TIMED_OUT,
        crud_sync.LOGIN_CODE_STATUS_CANCELLED,
    ]

    pending_records = crud_sync.list_login_code_requests_for_user(
        db,
        user_id=current_user.id,
        statuses=pending_statuses,
    )
    succeeded_records = crud_sync.list_login_code_requests_for_user(
        db,
        user_id=current_user.id,
        statuses=succeeded_statuses,
        limit=50,  # Show last 50 succeeded
    )
    errored_records = crud_sync.list_login_code_requests_for_user(
        db,
        user_id=current_user.id,
        statuses=errored_statuses,
        limit=50,  # Show last 50 errored
    )
    all_ids = {req.id for req, _, _ in pending_records + succeeded_records + errored_records}
    attempts_map = crud_sync.list_verification_attempts_for_requests(db, list(all_ids))

    pending_payload = [
        _format_code_request_details(
            request,
            outreach,
            target,
            attempts_map.get(request.id, []),
        )
        for request, outreach, target in pending_records
    ]

    succeeded_payload = [
        _format_code_request_details(
            request,
            outreach,
            target,
            attempts_map.get(request.id, []),
        )
        for request, outreach, target in succeeded_records
    ]

    errored_payload = [
        _format_code_request_details(
            request,
            outreach,
            target,
            attempts_map.get(request.id, []),
        )
        for request, outreach, target in errored_records
    ]

    return schemas.CodeRequestListResponse(
        pending=pending_payload,
        succeeded=succeeded_payload,
        errored=errored_payload,
    )


@router.post(
    "/code-requests/{request_id}/submit",
    response_model=schemas.LoginCodeAttemptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_code_request(
    request_id: int,
    payload: schemas.CodeRequestSubmitPayload,
    db: Session = Depends(get_sync_db),
    current_user: models.User = Depends(get_current_user),
):
    import json
    import asyncio
    from app.redis import get_redis_sync
    from app.services.service_manager import LinkedInMicroserviceService
    from app.settings import logger
    
    request_record = crud_sync.get_login_code_request_for_user(
        db,
        request_id=request_id,
        user_id=current_user.id,
    )
    if not request_record:
        raise HTTPException(status_code=404, detail="Verification request not found")
    if request_record.status not in (
        crud_sync.LOGIN_CODE_STATUS_PENDING,
        crud_sync.LOGIN_CODE_STATUS_SUBMITTED,
    ):
        raise HTTPException(status_code=400, detail="Verification request is not pending")

    # Record the attempt
    service = LinkedInVerificationService(db)
    attempt = service.submit_attempt(
        request_id=request_record.id,
        code_value=payload.code,
        submitted_by=payload.operator_name or current_user.email,
        submitted_by_user_id=current_user.id,
        source=payload.source or "portal",
        two_captcha_used=False,
        result=None,
        error_details=None,
        metadata=None,
    )
    
    # Get session info from Redis and submit PIN to LinkedIn
    outreach_profile_id = request_record.outreach_profile_id
    redis = get_redis_sync()
    try:
        session_data_str = redis.get(f"pending_2fa_session:{outreach_profile_id}")
        if not session_data_str:
            logger.warning(f"No pending 2FA session found for outreach_profile_id={outreach_profile_id}")
            error_msg = "No pending 2FA session found. Session may have expired. Please start a new verification."
            # Update attempt with error
            crud_sync.update_verification_attempt(
                db,
                attempt_id=attempt.id,
                result_value="failed",
                error_details=error_msg,
            )
            # Also mark request as failed
            service.resolve_request(
                request_id=request_record.id,
                status="failed",
                status_detail=error_msg,
            )
            # Refresh attempt to get updated values
            attempt = crud_sync.get_verification_attempt_by_id(db, attempt.id)
            return schemas.LoginCodeAttemptResponse.model_validate(attempt)
        
        session_data = json.loads(session_data_str)
        session_key = session_data.get("session_key")
        
        if not session_key:
            logger.error(f"Session key missing from session_data for outreach_profile_id={outreach_profile_id}")
            error_msg = "Session key missing from stored session data."
            crud_sync.update_verification_attempt(
                db,
                attempt_id=attempt.id,
                result_value="failed",
                error_details=error_msg,
            )
            # Also mark request as failed
            service.resolve_request(
                request_id=request_record.id,
                status="failed",
                status_detail=error_msg,
            )
            # Refresh attempt to get updated values
            attempt = crud_sync.get_verification_attempt_by_id(db, attempt.id)
            return schemas.LoginCodeAttemptResponse.model_validate(attempt)
        
        # Submit PIN to LinkedIn
        def _submit_pin():
            microservice = LinkedInMicroserviceService(outreach_profile_id)
            try:
                success = microservice.submit_pin(payload.code, session_key)
                return {"success": success}
            except Exception as e:
                logger.error(f"PIN submission error: {e}")
                return {"success": False, "error": str(e)}
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _submit_pin)
        
        if result.get("success"):
            # Success - update attempt and resolve request
            crud_sync.update_verification_attempt(
                db,
                attempt_id=attempt.id,
                result_value="succeeded",
                error_details=None,
            )
            service.resolve_request(
                request_id=request_record.id,
                status="succeeded",
                status_detail="PIN verified successfully via verification portal",
            )
            # Clean up Redis
            redis.delete(f"pending_2fa_session:{outreach_profile_id}")
            logger.info(f"Verification succeeded for request_id={request_id}, outreach_profile_id={outreach_profile_id}")
        else:
            # Failed - update attempt with error AND resolve request as failed
            error_msg = result.get("error", "PIN submission failed - LinkedIn rejected the code")
            crud_sync.update_verification_attempt(
                db,
                attempt_id=attempt.id,
                result_value="failed",
                error_details=error_msg,
            )
            # Also mark the request as failed since session is closed
            service.resolve_request(
                request_id=request_record.id,
                status="failed",
                status_detail=f"PIN verification failed: {error_msg}",
            )
            # Clean up Redis since the LinkedIn session is now closed
            redis.delete(f"pending_2fa_session:{outreach_profile_id}")
            logger.warning(f"Verification failed for request_id={request_id}: {error_msg}")
        
        # Refresh attempt from DB to get updated values
        attempt = crud_sync.get_verification_attempt_by_id(db, attempt.id)
        
    finally:
        redis.close()
    
    return schemas.LoginCodeAttemptResponse.model_validate(attempt)


@router.post(
    "/requests/{request_id}/status",
    response_model=schemas.LoginCodeRequestResponse,
)
def update_login_code_request_status(
    request_id: int,
    payload: schemas.LoginCodeRequestStatusUpdate,
    db: Session = Depends(get_sync_db),
):
    service = LinkedInVerificationService(db)
    state = service.resolve_request(
        request_id=request_id,
        status=payload.status,
        status_detail=payload.status_detail,
        metadata=payload.metadata,
        event_type=payload.event_type,
        event_detail=payload.event_detail,
        action_taken=payload.action_taken,
        two_captcha_used=payload.two_captcha_used,
    )
    if not state:
        raise HTTPException(status_code=404, detail="Verification request not found")
    return _state_to_response(state)


@router.post(
    "/requests/{request_id}/attempts",
    response_model=schemas.LoginCodeAttemptResponse,
)
def submit_login_code_attempt(
    request_id: int,
    payload: schemas.LoginCodeAttemptSubmit,
    db: Session = Depends(get_sync_db),
):
    service = LinkedInVerificationService(db)
    attempt = service.submit_attempt(
        request_id=request_id,
        code_value=payload.code_value,
        submitted_by=payload.submitted_by,
        submitted_by_user_id=payload.submitted_by_user_id,
        source=payload.source,
        two_captcha_used=payload.two_captcha_used,
        result=payload.result,
        error_details=payload.error_details,
        metadata=payload.metadata,
    )
    return schemas.LoginCodeAttemptResponse.model_validate(attempt)


@router.get(
    "/requests/{request_id}/attempts",
    response_model=List[schemas.LoginCodeAttemptResponse],
)
def list_login_code_attempts(
    request_id: int,
    db: Session = Depends(get_sync_db),
):
    attempts = crud_sync.list_verification_attempts(db, request_id=request_id)
    return [schemas.LoginCodeAttemptResponse.model_validate(item) for item in attempts]


@router.get(
    "/requests/{request_id}/attempts/latest",
    response_model=Optional[schemas.LoginCodeAttemptResponse],
)
def get_latest_login_code_attempt(
    request_id: int,
    db: Session = Depends(get_sync_db),
):
    attempt = crud_sync.get_latest_verification_attempt(db, request_id=request_id)
    if not attempt:
        return None
    return schemas.LoginCodeAttemptResponse.model_validate(attempt)


@router.patch(
    "/attempts/{attempt_id}",
    response_model=schemas.LoginCodeAttemptResponse,
)
def update_login_code_attempt(
    attempt_id: int,
    payload: schemas.LoginCodeAttemptUpdate,
    db: Session = Depends(get_sync_db),
):
    attempt = crud_sync.update_verification_attempt(
        db,
        attempt_id=attempt_id,
        result_value=payload.result,
        error_details=payload.error_details,
        metadata=payload.metadata,
    )
    if not attempt:
        raise HTTPException(status_code=404, detail="Verification attempt not found")
    return schemas.LoginCodeAttemptResponse.model_validate(attempt)

