from datetime import datetime, timezone
import json

from app import models
from app.celery_app import celery_app
from app.crud_sync import (
    LOGIN_CODE_STATUS_PENDING,
    LOGIN_CODE_STATUS_TIMED_OUT,
)
from app.database import SyncSessionLocal
from app.services.linkedin_verification import LinkedInVerificationService
from app.services.service_manager import LinkedInMicroserviceService
from app.redis import get_redis_sync
from app.settings import logger


@celery_app.task(name="app.tasks.login_code_cleanup.expire_pending_requests")
def expire_pending_login_code_requests():
    """
    Periodically mark expired manual verification requests as timed out
    and clean up any pending 2FA sessions.
    """
    with SyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        pending_records = (
            db.query(models.LinkedInLoginCodeRequest)
            .filter(
                models.LinkedInLoginCodeRequest.status == LOGIN_CODE_STATUS_PENDING,
                models.LinkedInLoginCodeRequest.expires_at < now,
            )
            .all()
        )
        if not pending_records:
            return {"expired": 0, "sessions_cancelled": 0}

        service = LinkedInVerificationService(db)
        redis = get_redis_sync()
        expired = 0
        sessions_cancelled = 0
        
        for record in pending_records:
            service.resolve_request(
                request_id=record.id,
                status=LOGIN_CODE_STATUS_TIMED_OUT,
                status_detail="Expired without manual code (cleanup).",
                event_type="timeout",
                event_detail="Auto-cleanup timed out pending verification request.",
                action_taken="rescheduled",
            )
            expired += 1
            
            session_key = f"pending_2fa_session:{record.outreach_profile_id}"
            session_data_str = redis.get(session_key)
            if session_data_str:
                try:
                    session_data = json.loads(session_data_str)
                    microservice_session_key = session_data.get("session_key")
                    if microservice_session_key:
                        try:
                            microservice = LinkedInMicroserviceService(record.outreach_profile_id)
                            microservice.cancel_pending_session(microservice_session_key)
                            sessions_cancelled += 1
                        except Exception as e:
                            logger.error(f"Failed to cancel microservice session {microservice_session_key}: {e}")
                    redis.delete(session_key)
                except Exception as e:
                    logger.error(f"Failed to process pending 2FA session for profile {record.outreach_profile_id}: {e}")

        redis.close()
        logger.info("Expired %s pending manual verification requests and cancelled %s sessions.", expired, sessions_cancelled)
        return {"expired": expired, "sessions_cancelled": sessions_cancelled}




