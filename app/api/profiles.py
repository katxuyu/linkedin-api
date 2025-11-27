from fastapi import APIRouter, Depends, HTTPException, Query
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis
from datetime import datetime, timezone, timedelta
from typing import List
from app import schemas, crud_async, database
from app.models import User, OutreachLinkedInProfile
from app.dependencies import get_current_user, get_redis
from app.tasks.tasks import fetch_profile_task, send_connection_request_task_old, send_message_task
from app.services.service_manager import LinkedInMicroserviceService
from app.errors import (
    LinkedInServiceNotAvailable,
    LinkedInLoginFailed,
    LinkedIn2FARequired,
    LinkedInCheckpointRequired,
)
from app.settings import FERNET, logger

router = APIRouter(prefix="/profiles", tags=["profiles"])

async def fetch_target_profiles_info(
    redis: Redis,
    user: User,
    outreach_profile: OutreachLinkedInProfile,
    target_profile_urls: list[str],
):
    """
    Reusable logic to fetch multiple LinkedIn target profiles.
    Can be called from both the API endpoint and the campaign runner.
    """

    rate_limit_key = f"user:{user.id}:profile_fetches:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    count = await redis.get(rate_limit_key)
    count = int(count) if count else 0
    if count + len(target_profile_urls) > 100:
        raise HTTPException(status_code=429, detail="Daily profile fetch limit exceeded")

    def _fetch_profiles():
        service = LinkedInMicroserviceService(outreach_profile.id)
        try:
            if not service.start():
                raise LinkedInLoginFailed("Failed to start LinkedIn service")
            
            results = []
            for url in target_profile_urls:
                try:
                    profile_data = service.fetch_profile_info(str(url))
                    if profile_data:
                        results.append(profile_data)
                        fetch_profile_task.delay(
                            profile_data,
                            user.id,
                            outreach_profile.id,
                            str(url)
                        )
                except Exception as e:
                    logger.error(f"Failed to fetch profile {url}: {e}")
            
            service.close()
            return results
        except Exception as e:
            logger.error(f"Service error: {e}")
            service.close()
            raise

    loop = asyncio.get_running_loop()
    try:
        results = await loop.run_in_executor(None, _fetch_profiles)
        for _ in results:
            await redis.incr(rate_limit_key)
        await redis.expire(rate_limit_key, 86400)
        return results
    except LinkedInLoginFailed:
        raise HTTPException(status_code=401, detail="LinkedIn login failed")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LinkedIn service unavailable: {e}")

# ------------------------------------
# Outreach LinkedIn Profiles Endpoints
# ------------------------------------
@router.post("/outreach/register", response_model=schemas.OutreachProfileCreateResponse)
async def register_outreach_profile(
    request: schemas.OutreachProfileCreateRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Register a single outreach LinkedIn profile for the user and verify connection.
    """
    outreach_profile = await crud_async.get_outreach_profile_by_url(db, str(request.linkedin_url), user.id)
    if outreach_profile:
        raise HTTPException(status_code=403, detail="Outreach profile already registered")
    
    gohighlevel_location_id = request.gohighlevel_location_id

    try:
        outreach_profile = await crud_async.create_outreach_profile(
            db,
            user_id=user.id,
            linkedin_email=request.linkedin_email,
            linkedin_password=request.linkedin_password,
            linkedin_url=str(request.linkedin_url),
            account_name=request.account_name,
            gohighlevel_location_id=gohighlevel_location_id,
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        # Handle database integrity errors (e.g., duplicate URL for same user)
        from sqlalchemy.exc import IntegrityError
        error_str = str(e)
        if isinstance(e, IntegrityError) or (hasattr(e, 'orig') and 'duplicate key' in error_str.lower()):
            # Check if it's a duplicate URL issue for this user
            if 'linkedin_url' in error_str.lower() or 'uq_user_linkedin_url' in error_str.lower():
                raise HTTPException(status_code=403, detail="You have already registered this LinkedIn profile")
        # Re-raise other exceptions with proper error message
        logger.exception(f"Error creating outreach profile: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create outreach profile: {error_str}")
    
    def _verify_and_save_connection():
        service = LinkedInMicroserviceService(outreach_profile.id)
        try:
            if not service.start():
                return {"success": False, "error": "Failed to start LinkedIn service"}
            
            profile_info = service.fetch_profile_info(outreach_profile.linkedin_url)
            
            if profile_info:
                service.close()
                return {"success": True, "profile_info": profile_info}
            else:
                service.close()
                return {"success": False, "error": "Failed to fetch profile info"}
                
        except LinkedIn2FARequired as e:
            logger.info(f"2FA required during registration for profile {outreach_profile.id}")
            return {
                "success": False, 
                "error": "2FA_REQUIRED",
                "session_key": e.session_key,
                "expires_at": e.expires_at
            }
        except Exception as e:
            error_str = str(e)
            logger.error(f"Verification connection error during registration: {e}")
            service.close()
            return {"success": False, "error": error_str}
    
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _verify_and_save_connection)
    
    if not result["success"]:
        error_msg = result.get("error", "Unknown error")
        if error_msg == "2FA_REQUIRED":
            from fastapi import Response
            import json
            from app.services.service_manager import open_manual_verification
            
            session_key = result.get("session_key")
            expires_at = result.get("expires_at")
            
            verification_payload = open_manual_verification(
                outreach_profile_id=outreach_profile.id,
                session_key=session_key,
                expires_at=expires_at,
                pending_reason="2FA code required during profile registration",
                request_type="profile_verification"
            )
            
            profile_response = schemas.OutreachProfileCreateResponse.model_validate(outreach_profile)
            response_data = {
                "detail": "2FA_REQUIRED",
                "requires_2fa": True,
                **verification_payload,
                **profile_response.model_dump(mode='json')
            }
            return Response(
                content=json.dumps(response_data),
                status_code=428,
                media_type="application/json"
            )
        logger.warning(f"Profile registered but verification failed: {error_msg}")
    
    return schemas.OutreachProfileCreateResponse.model_validate(outreach_profile)


@router.post("/outreach/{id}/verify-connection")
async def verify_outreach_profile_connection(
    id: int,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Start verification of LinkedIn profile connection.
    Returns immediately with 200 OK - actual processing happens in background.
    Frontend should poll /verify-connection-status for result.
    """
    import threading
    import json
    
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")

    # Check if there's already a verification in progress
    existing_status = await redis.get(f"verify_connection_status:{id}")
    if existing_status:
        existing_data = json.loads(existing_status)
        if existing_data.get("status") == "processing":
            logger.info(f"[verify-connection] Already processing for profile {id}")
            return {"status": "processing", "message": "Verification already in progress. Poll /verify-connection-status for result."}

    # Store initial processing status
    await redis.setex(
        f"verify_connection_status:{id}",
        300,  # 5 minute TTL
        json.dumps({"status": "processing", "message": "Starting LinkedIn verification..."})
    )
    
    profile_id = profile.id
    profile_url = profile.linkedin_url
    
    def _process_connection_in_background():
        from app.redis import get_redis_sync
        
        logger.info(f"[verify-connection-bg] Starting background verification for profile {profile_id}")
        
        r = get_redis_sync()
        redis_key = f"verify_connection_status:{profile_id}"
        
        service = LinkedInMicroserviceService(profile_id)
        try:
            if not service.start():
                r.setex(redis_key, 300, json.dumps({
                    "status": "error",
                    "message": "Failed to start LinkedIn service"
                }))
                r.close()
                return
            
            profile_info = service.fetch_profile_info(profile_url)
            
            if profile_info:
                service.close()
                r.setex(redis_key, 300, json.dumps({
                    "status": "connected",
                    "message": "Connection verified and session saved"
                }))
                logger.info(f"[verify-connection-bg] Successfully verified profile {profile_id}")
                
                # Clear any old failed/pending login code requests so the status shows clean
                from app.database import SyncSessionLocal
                from app.crud_sync import resolve_all_pending_login_code_requests
                try:
                    with SyncSessionLocal() as sync_db:
                        resolve_all_pending_login_code_requests(
                            sync_db,
                            outreach_profile_id=profile_id,
                            status="succeeded",
                            status_detail="Verified via app approval"
                        )
                except Exception as cleanup_err:
                    logger.warning(f"[verify-connection-bg] Failed to cleanup old requests: {cleanup_err}")
            else:
                service.close()
                r.setex(redis_key, 300, json.dumps({
                    "status": "error",
                    "message": "Failed to fetch profile info"
                }))
                
        except LinkedIn2FARequired as e:
            twofa_type = getattr(e, "twofa_type", "2fa_pin_required")
            logger.info(f"[verify-connection-bg] 2FA required ({twofa_type}) for profile {profile_id}")

            if twofa_type in ("2fa_app_approval", "2fa_app"):
                expires_at = e.expires_at or (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
                r.setex(redis_key, 300, json.dumps({
                    "status": "2fa_app_approval",
                    "error_type": "2fa_app_approval",
                    "message": "Check your LinkedIn app and tap 'Yes' to approve the sign-in request.",
                    "expires_at": expires_at,
                    "session_key": e.session_key  # Store session key for polling
                }))
            else:
                from app.services.service_manager import open_manual_verification
                
                verification_payload = open_manual_verification(
                    outreach_profile_id=profile_id,
                    session_key=e.session_key,
                    expires_at=e.expires_at,
                    pending_reason="2FA code required during connection verification",
                    request_type="profile_verification"
                )
                
                r.setex(redis_key, 300, json.dumps({
                    "status": "2fa_required",
                    "requires_2fa": True,
                    **verification_payload
                }))
        except LinkedInCheckpointRequired as checkpoint_exc:
            logger.warning(f"[verify-connection-bg] Checkpoint action required for profile {profile_id}: {checkpoint_exc}")
            message = str(checkpoint_exc) or "LinkedIn requires additional verification."
            error_type = getattr(checkpoint_exc, "error_type", "checkpoint_action_required") or "checkpoint_action_required"
            checkpoint_context = getattr(checkpoint_exc, "checkpoint_context", None)
            try:
                service.close()
            except Exception:
                pass
            r.setex(redis_key, 1800, json.dumps({
                "status": error_type,
                "error_type": error_type,
                "message": message,
                "requires_manual_action": True,
                "checkpoint_context": checkpoint_context,
            }))
        except Exception as e:
            error_str = str(e)
            logger.error(f"[verify-connection-bg] Error: {e}")
            try:
                service.close()
            except:
                pass
            
            # Parse specific error types for better user feedback
            if "2fa_app_approval" in error_str.lower() or "2FA_APP_APPROVAL" in error_str:
                # LinkedIn App approval required (push notification)
                # Use 5 minute TTL for app approval
                from datetime import datetime, timezone, timedelta
                expires_at = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
                # Try to extract session_key from the exception if available
                session_key_for_approval = getattr(e, 'session_key', None) if hasattr(e, 'session_key') else None
                r.setex(redis_key, 300, json.dumps({
                    "status": "2fa_app_approval",
                    "error_type": "2fa_app_approval",
                    "message": "Check your LinkedIn app and tap 'Yes' to approve the sign-in request.",
                    "expires_at": expires_at,
                    "session_key": session_key_for_approval
                }))
            elif "2fa_pin_required" in error_str.lower() or "2FA_PIN_REQUIRED" in error_str:
                # PIN code required (traditional 2FA)
                r.setex(redis_key, 300, json.dumps({
                    "status": "2fa_pin_required",
                    "error_type": "2fa_pin_required",
                    "message": "Please enter the verification code sent to your email or phone."
                }))
            elif "account_restricted" in error_str.lower() or "ACCOUNT_RESTRICTED" in error_str:
                r.setex(redis_key, 300, json.dumps({
                    "status": "error",
                    "error_type": "account_restricted",
                    "message": "Your LinkedIn account may be temporarily restricted. Please log in to LinkedIn manually to verify your account status."
                }))
            elif "invalid_credentials" in error_str.lower() or "INVALID_CREDENTIALS" in error_str:
                r.setex(redis_key, 300, json.dumps({
                    "status": "error",
                    "error_type": "invalid_credentials",
                    "message": "The LinkedIn email or password is incorrect. Please update your credentials."
                }))
            elif "captcha_failed" in error_str.lower() or "CAPTCHA_FAILED" in error_str:
                r.setex(redis_key, 300, json.dumps({
                    "status": "error",
                    "error_type": "captcha_failed",
                    "message": "LinkedIn's captcha verification failed. Please try again in a few minutes."
                }))
            elif "checkpoint_action_required" in error_str.lower():
                r.setex(redis_key, 1800, json.dumps({
                    "status": "checkpoint_action_required",
                    "error_type": "checkpoint_action_required",
                    "message": "LinkedIn requires additional verification. Please log in to LinkedIn manually to continue.",
                    "requires_manual_action": True
                }))
            elif "checkpoint_unknown" in error_str.lower():
                r.setex(redis_key, 1800, json.dumps({
                    "status": "checkpoint_unknown",
                    "error_type": "checkpoint_unknown",
                    "message": "LinkedIn presented an unknown challenge. Please log in manually to resolve.",
                    "requires_manual_action": True
                }))
            elif "401" in error_str or "unauthorized" in error_str.lower():
                r.setex(redis_key, 300, json.dumps({
                    "status": "error",
                    "error_type": "auth_failed",
                    "message": "LinkedIn authentication failed. This may be due to invalid credentials, account restrictions, or security challenges."
                }))
            else:
                r.setex(redis_key, 300, json.dumps({
                    "status": "error",
                    "error_type": "unknown",
                    "message": f"Failed to connect to LinkedIn: {error_str}"
                }))
        
        r.close()
        logger.info(f"[verify-connection-bg] Background processing complete for profile {profile_id}")

    # Start background thread and return immediately
    thread = threading.Thread(target=_process_connection_in_background, daemon=True)
    thread.start()
    
    logger.info(f"[verify-connection] Returning 200 OK immediately, processing in background")
    return {"status": "processing", "message": "Verification started. Poll /verify-connection-status for result."}


@router.get("/outreach/{id}/verify-connection-status")
async def get_verify_connection_status(
    id: int,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Poll for the result of verify-connection operation.
    
    For app approval (push notification 2FA), this endpoint will actively
    check the microservice to see if the user has approved/rejected.
    """
    import json
    
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")
    
    status_data = await redis.get(f"verify_connection_status:{id}")
    if not status_data:
        return {"status": "none", "message": "No verification in progress"}
    
    result = json.loads(status_data)
    
    # If app approval pending, actively check the microservice for status
    if result.get("status") == "2fa_app_approval":
        session_key = result.get("session_key")
        if session_key:
            try:
                from app.services.linkedin_service_client import LinkedInMicroserviceClient
                client = LinkedInMicroserviceClient()
                approval_result = client.check_app_approval(session_key)
                
                logger.info(f"[verify-connection-status] App approval check for profile {id}: {approval_result.get('status')}")
                
                if approval_result.get("status") == "approved":
                    # User approved! Update profile and return success
                    from app.database import SyncSessionLocal
                    with SyncSessionLocal() as sync_db:
                        # Update profile with new cookies if available
                        cookies = approval_result.get("cookies")
                        user_agent = approval_result.get("user_agent")
                        if cookies:
                            crud_sync.update_outreach_profile(
                                sync_db, id,
                                linkedin_cookies=cookies,
                                user_agent=user_agent,
                                is_connected=True,
                                connection_status="connected"
                            )
                        else:
                            crud_sync.update_outreach_profile(
                                sync_db, id,
                                is_connected=True,
                                connection_status="connected"
                            )
                        
                        # Resolve any pending login code requests
                        resolve_all_pending_login_code_requests(sync_db, id)
                        
                        sync_db.commit()
                    
                    # Clear the status
                    await redis.delete(f"verify_connection_status:{id}")
                    
                    return {
                        "status": "connected",
                        "message": "Successfully authenticated! LinkedIn sign-in approved."
                    }
                
                elif approval_result.get("status") == "rejected":
                    # User rejected the request
                    await redis.delete(f"verify_connection_status:{id}")
                    return {
                        "status": "error",
                        "error_type": "app_approval_rejected",
                        "message": approval_result.get("message", "Sign-in request was denied. Please try again.")
                    }
                
                elif approval_result.get("status") == "expired":
                    # Session expired
                    await redis.delete(f"verify_connection_status:{id}")
                    return {
                        "status": "error",
                        "error_type": "session_expired",
                        "message": "Session expired. Please start a new verification."
                    }
                
                elif approval_result.get("status") == "state_changed":
                    # LinkedIn changed to PIN mode
                    await redis.delete(f"verify_connection_status:{id}")
                    return {
                        "status": "error",
                        "error_type": "state_changed",
                        "message": "LinkedIn is now asking for a PIN code. Please restart verification."
                    }
                
                elif approval_result.get("status") == "checkpoint_action_required":
                    await redis.delete(f"verify_connection_status:{id}")
                    checkpoint_context = approval_result.get("checkpoint_context") or approval_result.get("context")
                    return {
                        "status": "checkpoint_action_required",
                        "error_type": "checkpoint_action_required",
                        "message": approval_result.get("message", "LinkedIn requires additional verification."),
                        "checkpoint_context": checkpoint_context,
                        "requires_manual_action": True,
                    }
                
                # Still pending - return the current status with updated message
                return {
                    "status": "2fa_app_approval",
                    "message": approval_result.get("message", "Waiting for approval on LinkedIn app..."),
                    "expires_at": result.get("expires_at"),
                    "session_key": session_key
                }
                
            except Exception as e:
                logger.warning(f"[verify-connection-status] Error checking app approval: {e}")
                # Return the cached status if we can't check the microservice
                return result
        
        # No session key - just return the cached status
        return result
    
    # If 2FA required, return 428 status code for frontend to show modal
    if result.get("status") == "2fa_required":
        # Clear the status so it doesn't keep returning 2FA
        await redis.delete(f"verify_connection_status:{id}")
        raise HTTPException(
            status_code=428,
            detail=result
        )
    
    # Manual checkpoint statuses - clear and surface directly
    if result.get("status") in ("checkpoint_action_required", "checkpoint_unknown"):
        await redis.delete(f"verify_connection_status:{id}")
        return result
    
    # If completed (success or error), clear the status
    if result.get("status") in ["connected", "error"]:
        await redis.delete(f"verify_connection_status:{id}")
    
    return result


@router.post("/outreach/{id}/verify-pin")
async def verify_outreach_profile_pin(
    id: int,
    request: schemas.VerifyPinRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Submit a PIN/verification code for 2FA during profile verification.
    Returns immediately with 200 OK - actual processing happens in background.
    Frontend should poll for status updates.
    """
    import threading
    import json
    
    logger.info(f"[verify-pin] Received PIN verification request for profile {id}")
    
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")
    
    session_data_str = await redis.get(f"pending_2fa_session:{id}")
    if not session_data_str:
        raise HTTPException(status_code=400, detail="No pending 2FA session found")
    
    session_data = json.loads(session_data_str)
    session_key = session_data.get("session_key")
    verification_request_id = session_data.get("verification_request_id")
    
    logger.info(f"[verify-pin] Found session for profile {id}, request_id={verification_request_id}")
    
    # Immediately mark request as "submitted"
    if verification_request_id:
        from app.services.linkedin_verification import LinkedInVerificationService
        from app.database import SyncSessionLocal
        with SyncSessionLocal() as sync_db:
            verification_service = LinkedInVerificationService(sync_db)
            verification_service.resolve_request(
                request_id=verification_request_id,
                status="submitted",
                status_detail="PIN submitted, processing..."
            )

    # Capture values for background thread
    pin_value = request.pin
    operator_name = request.operator_name or user.email
    user_id = user.id
    profile_id = profile.id
    redis_key = f"pending_2fa_session:{id}"

    def _process_pin_in_background():
        """Process PIN submission in background thread."""
        from app.services.linkedin_verification import LinkedInVerificationService
        from app.database import SyncSessionLocal
        from app.redis import get_redis_sync
        
        logger.info(f"[verify-pin-bg] Starting background PIN processing for profile {profile_id}")
        
        final_status = "failed"
        final_detail = "Unknown error"
        
        try:
            # Submit PIN to LinkedIn
            service = LinkedInMicroserviceService(profile_id)
            logger.info(f"[verify-pin-bg] Calling linkedin-service submit_pin")
            success = service.submit_pin(pin_value, session_key)
            logger.info(f"[verify-pin-bg] linkedin-service returned: success={success}")
            
            if success:
                final_status = "succeeded"
                final_detail = "PIN verified successfully"
            else:
                final_status = "failed"
                final_detail = "PIN verification failed: LinkedIn rejected the code"
                
        except Exception as e:
            logger.error(f"[verify-pin-bg] PIN submission error: {e}")
            final_status = "failed"
            final_detail = f"PIN verification error: {str(e)}"
        
        # Update database with result
        try:
            with SyncSessionLocal() as sync_db:
                verification_service = LinkedInVerificationService(sync_db)
                verification_service.submit_attempt(
                    request_id=verification_request_id,
                    code_value=pin_value,
                    submitted_by=operator_name,
                    submitted_by_user_id=user_id,
                    source="modal",
                    two_captcha_used=False,
                    result=final_status,
                    error_details=final_detail if final_status == "failed" else None,
                    metadata=None,
                )
                verification_service.resolve_request(
                    request_id=verification_request_id,
                    status=final_status,
                    status_detail=final_detail
                )
            logger.info(f"[verify-pin-bg] Updated request {verification_request_id} to {final_status}")
        except Exception as e:
            logger.error(f"[verify-pin-bg] Failed to update request status: {e}")
        
        # Clean up Redis
        try:
            r = get_redis_sync()
            r.delete(redis_key)
            r.close()
            logger.info(f"[verify-pin-bg] Deleted Redis session {redis_key}")
        except Exception as e:
            logger.error(f"[verify-pin-bg] Failed to delete Redis session: {e}")
        
        logger.info(f"[verify-pin-bg] Background processing complete for profile {profile_id}")

    # Start background thread and return immediately
    thread = threading.Thread(target=_process_pin_in_background, daemon=True)
    thread.start()
    
    logger.info(f"[verify-pin] Returning 200 OK immediately, processing in background")
    return {"status": "processing", "message": "PIN submitted, check status for result"}


# Keep backward compatibility - old endpoint behavior
@router.post("/outreach/{id}/verify-pin-sync")
async def verify_outreach_profile_pin_sync(
    id: int,
    request: schemas.VerifyPinRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Synchronous PIN verification - waits for result (for backward compatibility).
    """
    import json
    
    logger.info(f"[verify-pin-sync] Received PIN verification request for profile {id}")
    
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")
    
    session_data_str = await redis.get(f"pending_2fa_session:{id}")
    if not session_data_str:
        raise HTTPException(status_code=400, detail="No pending 2FA session found")
    
    session_data = json.loads(session_data_str)
    session_key = session_data.get("session_key")
    verification_request_id = session_data.get("verification_request_id")
    
    # Mark as submitted
    if verification_request_id:
        from app.services.linkedin_verification import LinkedInVerificationService
        from app.database import SyncSessionLocal
        with SyncSessionLocal() as sync_db:
            verification_service = LinkedInVerificationService(sync_db)
            verification_service.resolve_request(
                request_id=verification_request_id,
                status="submitted",
                status_detail="PIN submitted, awaiting verification..."
            )

    # Submit PIN synchronously
    service = LinkedInMicroserviceService(profile.id)
    try:
        success = service.submit_pin(request.pin, session_key)
        final_status = "succeeded" if success else "failed"
        final_detail = "PIN verified successfully" if success else "PIN verification failed"
    except Exception as e:
        final_status = "failed"
        final_detail = str(e)
    
    # Update status
    if verification_request_id:
        from app.services.linkedin_verification import LinkedInVerificationService
        from app.database import SyncSessionLocal
        with SyncSessionLocal() as sync_db:
            verification_service = LinkedInVerificationService(sync_db)
            verification_service.resolve_request(
                request_id=verification_request_id,
                status=final_status,
                status_detail=final_detail
            )
    
    # Clean up Redis
    await redis.delete(f"pending_2fa_session:{id}")
    
    if final_status == "succeeded":
        return {"status": "success", "message": "PIN verified successfully"}
    else:
        logger.warning(f"[verify-pin] Verification failed for profile {id}: {final_detail}")
        raise HTTPException(status_code=400, detail=f"Failed to verify PIN: {final_detail}")


@router.post("/outreach/{id}/cancel-2fa")
async def cancel_2fa_session(
    id: int,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Cancel a pending 2FA session.
    """
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")
    
    import json
    session_data_str = await redis.get(f"pending_2fa_session:{id}")
    if not session_data_str:
        return {"status": "success", "message": "No pending session to cancel"}
    
    session_data = json.loads(session_data_str)
    session_key = session_data.get("session_key")
    verification_request_id = session_data.get("verification_request_id")

    def _cancel_session():
        service = LinkedInMicroserviceService(profile.id)
        try:
            success = service.cancel_pending_session(session_key)
            return {"success": success}
        except Exception as e:
            logger.error(f"Session cancellation error: {e}")
            return {"success": False, "error": str(e)}

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _cancel_session)
    
    await redis.delete(f"pending_2fa_session:{id}")
    
    if verification_request_id:
        from app.services.linkedin_verification import LinkedInVerificationService
        from app.database import SyncSessionLocal
        with SyncSessionLocal() as sync_db:
            verification_service = LinkedInVerificationService(sync_db)
            verification_service.resolve_request(
                request_id=verification_request_id,
                status="cancelled",
                status_detail="User cancelled 2FA verification"
            )
    
    return {"status": "success", "message": "2FA session cancelled"}



@router.get("/outreach/list", response_model=List[schemas.OutreachProfileListResponse])
async def list_outreach_profiles(
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    List all outreach profiles registered by the user.
    """
    profiles = await crud_async.get_outreach_profiles_by_user(db, user.id)
    return profiles

@router.get("/outreach/find-by-email", response_model=schemas.OutreachProfileListResponse)
async def find_outreach_profile_by_email(
    linkedin_email: str = Query(..., description="LinkedIn email to search for"),
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Find an outreach profile by LinkedIn email for the current user.
    """
    profile = await crud_async.get_outreach_profile_by_email(db, linkedin_email, user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile

@router.get("/outreach/find-by-url", response_model=schemas.OutreachProfileListResponse)
async def find_outreach_profile_by_url(
    linkedin_url: str = Query(..., description="LinkedIn URL to search for"),
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Find an outreach profile by LinkedIn URL for the current user.
    """
    profile = await crud_async.get_outreach_profile_by_url(db, linkedin_url, user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile

@router.put("/outreach/update/url/{id}", response_model=schemas.OutreachProfileCreateResponse)
async def update_outreach_profile_url(
    id: int,
    request: schemas.UpdateLinkedInUrlRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")

    if str(profile.linkedin_url) != str(request.old_linkedin_url):
        raise HTTPException(status_code=409, detail="Old profile URL does not match")
    
    if str(profile.linkedin_url) == str(request.new_linkedin_url):
        raise HTTPException(status_code=409, detail="Profile URL already exists")

    profile = await crud_async.update_outreach_profile_url_only(
        db, id, str(request.new_linkedin_url)
    )
    return profile

@router.put("/outreach/update/email/{id}", response_model=schemas.OutreachProfileCreateResponse)
async def update_outreach_profile_email(
    id: int,
    request: schemas.UpdateLinkedInEmailRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")

    if profile.linkedin_email == request.new_linkedin_email:
        raise HTTPException(status_code=409, detail="Outreach profile email already exists")

    if profile.linkedin_email != request.old_linkedin_email:
        raise HTTPException(status_code=400, detail="Old email does not match")

    profile = await crud_async.update_outreach_profile_email_only(
        db, id, request.new_linkedin_email
    )
    return profile

@router.put("/outreach/update/password/{id}", response_model=schemas.OutreachProfileCreateResponse)
async def update_outreach_profile_password(
    id: int,
    request: schemas.UpdateLinkedInPasswordRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")
    
    # decrypt stored password to compare with old password provided
    old_decrypted_password = FERNET.decrypt(profile.linkedin_password.encode()).decode()

    if str(old_decrypted_password) == str(request.new_linkedin_password):
        raise HTTPException(status_code=409, detail="Password already set to this value")
    
    if old_decrypted_password != request.old_linkedin_password:
        raise HTTPException(status_code=409, detail="Old password does not match")

    # store new password encrypted
    profile = await crud_async.update_outreach_profile_password_only(
        db, id, request.new_linkedin_password
    )
    return profile


@router.patch(
    "/outreach/{id}/gohighlevel-location",
    response_model=schemas.OutreachProfileCreateResponse,
)
async def update_outreach_profile_gohighlevel_location(
    id: int,
    request: schemas.OutreachProfileGoHighLevelUpdate,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")

    gohighlevel_location_id = request.gohighlevel_location_id

    updated = await crud_async.update_outreach_profile_gohighlevel_location(
        db, id, gohighlevel_location_id
    )
    return schemas.OutreachProfileCreateResponse.model_validate(updated)


@router.delete("/outreach/{id}", response_model=schemas.OutreachProfileDeleteResponse)
async def delete_outreach_profile(
    id: int,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Delete an outreach profile.
    """
    success = await crud_async.delete_outreach_profile(db, id, user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Outreach profile not found or not owned")
    
    return {"id": id, "status": "success", "message": "Profile deleted successfully"}


@router.put("/outreach/{id}", response_model=schemas.OutreachProfileCreateResponse)
async def update_outreach_profile(
    id: int,
    request: schemas.OutreachProfileUpdateRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Update an outreach profile (all fields).
    """
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")

    # Convert request to dict and filter None values
    update_data = request.model_dump(exclude_unset=True)
    
    updated_profile = await crud_async.update_outreach_profile_all_fields(db, id, update_data)
    if not updated_profile:
        raise HTTPException(status_code=500, detail="Failed to update profile")
        
    return schemas.OutreachProfileCreateResponse.model_validate(updated_profile)


@router.get("/outreach/{id}/stats", response_model=schemas.OutreachProfileStatsResponse)
async def get_outreach_profile_stats(
    id: int,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Get usage statistics for an outreach profile.
    """
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")
        
    stats = await crud_async.get_outreach_profile_stats(db, id)
    return stats


@router.get("/outreach/{id}/status", response_model=schemas.OutreachProfileStatusResponse)
async def get_outreach_profile_status(
    id: int,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Get health status for an outreach profile.
    Also checks Redis for active verification state (app approval, etc.)
    """
    import json
    
    profile = await crud_async.get_outreach_profile_by_id(db, id)
    if not profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned")
    
    # Check Redis for active verification state first
    redis_status = await redis.get(f"verify_connection_status:{id}")
    if redis_status:
        redis_data = json.loads(redis_status)
        redis_status_value = redis_data.get("status")
        
        # If we just successfully connected, return clean status
        if redis_status_value == "connected":
            return {
                "id": id,
                "is_connected": True,
                "is_verified": True,
                "last_verified_at": None,
                "session_status": "active",
                "needs_attention": False,
                "issues": []
            }
        
        # If app approval is pending, show that instead of old DB state
        if redis_status_value == "2fa_app_approval":
            return {
                "id": id,
                "is_connected": False,
                "is_verified": False,
                "last_verified_at": None,
                "session_status": "pending_approval",
                "needs_attention": True,
                "issues": ["LinkedIn App approval required - check your phone and tap 'Yes' to approve"]
            }
        
        # If processing, show that
        if redis_status_value == "processing":
            return {
                "id": id,
                "is_connected": False,
                "is_verified": False,
                "last_verified_at": None,
                "session_status": "verifying",
                "needs_attention": False,
                "issues": ["Verification in progress..."]
            }
        
        if redis_status_value in ("checkpoint_action_required", "checkpoint_unknown"):
            message = redis_data.get("message") or "LinkedIn requires manual verification."
            return {
                "id": id,
                "is_connected": False,
                "is_verified": False,
                "last_verified_at": None,
                "session_status": "manual_verification",
                "needs_attention": True,
                "issues": [message]
            }
    
    # Fall back to database status
    status = await crud_async.get_outreach_profile_status(db, id)
    return status


@router.get("/outreach/status/bulk", response_model=schemas.OutreachProfileStatusBulkResponse)
async def get_outreach_profiles_status_bulk(
    profile_ids: str = Query(..., description="Comma-separated list of profile IDs"),
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
    redis: Redis = Depends(get_redis)
):
    """
    Get health status for multiple outreach profiles in a single request.
    Also checks Redis for active verification state (app approval, etc.)
    """
    import json
    
    try:
        ids = [int(id.strip()) for id in profile_ids.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid profile IDs format")
    
    profiles = await crud_async.get_outreach_profiles_by_user(db, user.id)
    user_profile_ids = {p.id for p in profiles}
    
    requested_ids = [id for id in ids if id in user_profile_ids]
    
    if not requested_ids:
        return {"statuses": {}}
    
    # Get database statuses first
    statuses = await crud_async.get_outreach_profiles_status_bulk(db, requested_ids)
    
    # Override with Redis status where applicable
    for profile_id in requested_ids:
        redis_status = await redis.get(f"verify_connection_status:{profile_id}")
        if redis_status:
            redis_data = json.loads(redis_status)
            redis_status_value = redis_data.get("status")
            
            # If we just successfully connected, return clean status
            if redis_status_value == "connected":
                statuses[profile_id] = {
                    "id": profile_id,
                    "is_connected": True,
                    "is_verified": True,
                    "last_verified_at": None,
                    "session_status": "active",
                    "needs_attention": False,
                    "issues": []
                }
            # If app approval is pending, show that instead of old DB state
            elif redis_status_value == "2fa_app_approval":
                statuses[profile_id] = {
                    "id": profile_id,
                    "is_connected": False,
                    "is_verified": False,
                    "last_verified_at": None,
                    "session_status": "pending_approval",
                    "needs_attention": True,
                    "issues": ["LinkedIn App approval required - check your phone and tap 'Yes' to approve"]
                }
            # If processing, show that
            elif redis_status_value == "processing":
                statuses[profile_id] = {
                    "id": profile_id,
                    "is_connected": False,
                    "is_verified": False,
                    "last_verified_at": None,
                    "session_status": "verifying",
                    "needs_attention": False,
                    "issues": ["Verification in progress..."]
                }
            elif redis_status_value in ("checkpoint_action_required", "checkpoint_unknown"):
                message = redis_data.get("message") or "LinkedIn requires manual verification."
                statuses[profile_id] = {
                    "id": profile_id,
                    "is_connected": False,
                    "is_verified": False,
                    "last_verified_at": None,
                    "session_status": "manual_verification",
                    "needs_attention": True,
                    "issues": [message]
                }
    
    return {"statuses": statuses}


# ------------------------------------
# Target LinkedIn Profiles Endpoints
# ------------------------------------
@router.post("/target/fetch-info", response_model=list | dict)
async def fetch_info(
    request: schemas.FetchProfilesRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(database.get_db),
):
    outreach_profile = await crud_async.get_outreach_profile_by_id(db, request.outreach_profile_id)
    if not outreach_profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if outreach_profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile owned")

    all_profiles_data = await fetch_target_profiles_info(
        redis=redis,
        user=user,
        outreach_profile=outreach_profile,
        target_profile_urls=request.target_profile_urls,
    )

    return all_profiles_data if len(all_profiles_data) > 1 else all_profiles_data[0]


@router.post("/target/connect", response_model=dict)
async def send_connection_request(
    request: schemas.ConnectionRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Queue tasks to send connection requests to multiple LinkedIn profiles.
    """
    rate_limit_key = f"user:{user.id}:connection_requests:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    count = await redis.get(rate_limit_key)
    count = int(count) if count else 0
    if count > 50:
        raise HTTPException(status_code=429, detail="Daily connection request limit reached")
    
    outreach_profile = await crud_async.get_outreach_profile_by_id(db, request.outreach_profile_id)
    if not outreach_profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if outreach_profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile owned")
    
    target_profile = await crud_async.get_target_profile_by_url(db, str(request.target_profile_url))
    
    def _send_connection():
        service = LinkedInMicroserviceService(outreach_profile.id)
        try:
            if not service.start():
                raise LinkedInLoginFailed("Failed to start LinkedIn service")
            
            profile_data = service.fetch_profile_info(str(request.target_profile_url))
            if not profile_data:
                service.close()
                return {"status": "connection_request_failed", "reason": "Target profile info can't be found"}
            
            if profile_data.get('connected'):
                service.close()
                return {"status": "connection_request_failed", "reason": "Target profile already connected"}
            
            if profile_data.get('connection_pending'):
                service.close()
                return {"status": "connection_request_failed", "reason": "Connection request already sent"}
            
            success = service.send_connection_request(str(request.target_profile_url), request.message)
            service.close()
            
            send_connection_request_task_old.delay(
                user.id,
                success,
                outreach_profile.id,
                str(request.target_profile_url),
                profile_data if not target_profile else None,
                request.message
            )
            
            if success:
                return {"status": "connection_request_success"}
            else:
                return {"status": "connection_request_failed", "reason": "Failed to send connection request"}
        except LinkedIn2FARequired:
            raise
        except Exception as e:
            logger.error(f"Connection request error: {e}")
            service.close()
            raise

    if not target_profile or (not target_profile.connected and not target_profile.connection_pending):
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, _send_connection)
            if result["status"] == "connection_request_success":
                await redis.incr(rate_limit_key)
                await redis.expire(rate_limit_key, 86400)
            return result
        except LinkedInLoginFailed:
            raise HTTPException(status_code=401, detail="LinkedIn login failed")
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"LinkedIn service unavailable: {e}")
    elif target_profile.connected:
        return {"status": "connection_request_failed", "reason": "Target profile already connected"}
    else:
        return {"status": "connection_request_failed", "reason": "Connection request already sent"}


@router.post("/target/message", response_model=dict)
async def send_message(
    request: schemas.MessageRequest,
    user: schemas.UserResponse = Depends(get_current_user),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Queue a task to send a message to a single LinkedIn profile.
    """
    rate_limit_key = f"user:{user.id}:messages:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    count = await redis.get(rate_limit_key)
    count = int(count) if count else 0
    if count >= 50:
        raise HTTPException(status_code=429, detail="Daily message limit reached")
    
    outreach_profile = await crud_async.get_outreach_profile_by_id(db, request.outreach_profile_id)
    if not outreach_profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if outreach_profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile owned")
    
    target_profile = await crud_async.get_target_profile_by_url(db, str(request.target_profile_url))
    
    if target_profile:
        if not target_profile.connected and not target_profile.can_message:
            return {"status": "send_message_failed", "reason": "Target profile not connected"}
        if target_profile.connection_pending:
            return {"status": "send_message_failed", "reason": "Target profile connection request pending"}
    
    def _send_message():
        service = LinkedInMicroserviceService(outreach_profile.id)
        try:
            if not service.start():
                raise LinkedInLoginFailed("Failed to start LinkedIn service")
            
            profile_data = service.fetch_profile_info(str(request.target_profile_url))
            if not profile_data:
                service.close()
                return {"status": "send_message_failed", "reason": "Target profile info can't be found"}
            
            if not profile_data.get('connected') and not profile_data.get('can_message'):
                service.close()
                return {"status": "send_message_failed", "reason": "Target profile not connected"}
            
            if profile_data.get('connection_pending'):
                service.close()
                return {"status": "send_message_failed", "reason": "Target profile connection request pending"}
            
            success = service.send_message(str(request.target_profile_url), request.message)
            service.close()
            
            send_message_task.delay(
                user.id,
                success,
                outreach_profile.id,
                str(request.target_profile_url),
                request.message,
                profile_data if not target_profile else None
            )
            
            if success:
                return {"status": "send_message_success"}
            else:
                return {"status": "send_message_failed", "reason": "Failed to send message"}
        except LinkedIn2FARequired:
            raise
        except Exception as e:
            logger.error(f"Send message error: {e}")
            service.close()
            raise
    
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, _send_message)
        if result["status"] == "send_message_success":
            await redis.incr(rate_limit_key)
            await redis.expire(rate_limit_key, 86400)
        return result
    except LinkedInLoginFailed:
        raise HTTPException(status_code=401, detail="LinkedIn login failed")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LinkedIn service unavailable: {e}")


@router.get("/target/list", response_model=List[schemas.TargetProfileResponse])
async def list_target_profiles(
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    List all target profiles for the user.
    """
    profiles = await crud_async.get_target_profiles_by_user(db, user.id)
    return profiles

@router.get("/target/find-by-url", response_model=schemas.TargetProfileResponse)
async def find_outreach_profile_by_url(
    linkedin_url: str = Query(..., description="LinkedIn URL to search for"),
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db)
):
    """
    Find a target profile by LinkedIn URL for the current user.
    """
    profile = await crud_async.get_outreach_profile_by_url(db, linkedin_url, user.id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile

