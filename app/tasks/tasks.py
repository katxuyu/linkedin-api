import time
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from app import models
from app.utils.helpers import render_message
from app.celery_app import celery_app
from typing import Optional
from app.crud_sync import (
    get_user_by_id,
    get_outreach_profile_by_id,
    create_action, 
    update_target_profile,
    create_chat_history,
    get_target_profile_by_url,
    get_target_profile_by_id,
    get_user_id_by_outreach_profile,
    update_campaign_history_status,
    update_campaign_step_history_status,
    create_action,
    create_chat_history,
    pause_all_campaigns_for_target
)
from app.database import SyncSessionLocal
from app.settings import logger, CELERY_WORKER_CHECK_INTERVAL, FERNET
# from app.services.session_manager_sync import LinkedInSessionManager
# from app.services.linkedin_service_client import LinkedInService
from app.errors import LinkedInServiceNotAvailable, LinkedInLoginFailed, DecryptionError


@celery_app.task(name="app.tasks.tasks.fetch_profile_task", bind=True, max_retries=3)
def fetch_profile_task(
    self,
    profile_data: dict,
    user_id: int,
    outreach_profile_id: int,
    target_profile_url: str
) -> None:
    current_attempt = self.request.retries + 1
    max_attempts = self.max_retries + 1
    try:
        if profile_data:
            with SyncSessionLocal() as db:
                # Update or create target profile
                db_profile = update_target_profile(
                    db=db,
                    profile_url=target_profile_url,
                    outreach_profile_id=outreach_profile_id,
                    profile_data=profile_data,
                    create_if_not_exists=True
                )
                # Log action
                create_action(
                    db,
                    user_id=user_id,
                    outreach_profile_id=outreach_profile_id,
                    target_profile_id=db_profile.id,
                    action_type="fetch_profile",
                    status="success",
                    details={"task_id": self.request.id}
                )
        else:
            with SyncSessionLocal() as db:
                db_profile = get_target_profile_by_url(db, target_profile_url, outreach_profile_id=outreach_profile_id)
                # Log action
                create_action(
                    db,
                    user_id=user_id,
                    target_profile_id=db_profile.id if db_profile else None,
                    outreach_profile_id=outreach_profile_id,
                    action_type="fetch_profile",
                    status="failed",
                    details={"task_id": self.request.id}
                )
    except Exception as e:
        logger.error(f"Fetch profile task failed {current_attempt}/{max_attempts}: {str(e)}")
        self.retry(exc=e, countdown=60)


@celery_app.task(name="app.tasks.tasks.send_connection_request_task", bind=True, max_retries=3)
def send_connection_request_task_old(
    self,
    user_id: int,
    connection_request_sent: bool,
    outreach_profile_id: int,
    target_profile_url: str,
    profile_data: Optional[dict] = None,
    message: Optional[str] = None
) -> None:
    current_attempt = self.request.retries + 1
    max_attempts = self.max_retries + 1
    try:
        if connection_request_sent:
            if profile_data:
                with SyncSessionLocal() as db:
                    # Update or create target profile
                    db_profile = update_target_profile(
                        db=db,
                        profile_url=target_profile_url,
                        outreach_profile_id=outreach_profile_id,
                        profile_data=profile_data,
                        create_if_not_exists=True
                    )
                    create_action(
                        db=db,
                        user_id=user_id,
                        target_profile_id=db_profile.id,
                        outreach_profile_id=outreach_profile_id,
                        action_type="connection_request",
                        status="success",
                        details={"task_id": self.request.id}
                    )
                    if message:
                        create_chat_history(
                            db,
                            user_id=user_id,
                            outreach_profile_id=outreach_profile_id,
                            target_profile_id=db_profile.id,
                            message_role="outbound",
                            message=message
                        )
            else:
                with SyncSessionLocal() as db:
                    db_profile = get_target_profile_by_url(
                        db,
                        target_profile_url,
                        outreach_profile_id=outreach_profile_id
                    )
                    create_action(
                        db=db,
                        user_id=user_id,
                        target_profile_id=db_profile.id if db_profile else None,
                        outreach_profile_id=outreach_profile_id,
                        action_type="connection_request",
                        status="success",
                        details={"task_id": self.request.id}
                    )
                    if message and db_profile:
                        create_chat_history(
                            db,
                            user_id=user_id,
                            outreach_profile_id=outreach_profile_id,
                            target_profile_id=db_profile.id,
                            message_role="outbound",
                            message=message
                        )
        else:
            if profile_data:
                with SyncSessionLocal() as db:
                    # Update or create target profile
                    db_profile = update_target_profile(
                        db=db,
                        profile_url=target_profile_url,
                        outreach_profile_id=outreach_profile_id,
                        profile_data=profile_data,
                        create_if_not_exists=True
                    )
                    create_action(
                        db=db,
                        user_id=user_id,
                        target_profile_id=db_profile.id,
                        outreach_profile_id=outreach_profile_id,
                        action_type="connection_request",
                        status="failed",
                        details={"task_id": self.request.id}
                    )
            else:
                with SyncSessionLocal() as db:
                    db_profile = get_target_profile_by_url(db, target_profile_url, outreach_profile_id=outreach_profile_id)
                    create_action(
                        db=db,
                        user_id=user_id,
                        target_profile_id=db_profile.id if db_profile else None,
                        outreach_profile_id=outreach_profile_id,
                        action_type="connection_request",
                        status="failed",
                        details={"task_id": self.request.id}
                    )
    except Exception as e:
        logger.error(f"Connection request task failed {current_attempt}/{max_attempts}: {str(e)}")
        self.retry(exc=e, countdown=60)


@celery_app.task(name="app.tasks.tasks.send_message_task", bind=True, max_retries=3)
def send_message_task(
    self,
    user_id: int,
    message_sent: bool,
    outreach_profile_id: int,
    target_profile_url: str,
    message: str,
    profile_data: Optional[dict]
) -> None:
    current_attempt = self.request.retries + 1
    max_attempts = self.max_retries + 1
    try:
        with SyncSessionLocal() as db:
            if profile_data:
                # Update or create target profile
                db_profile = update_target_profile(
                    db=db,
                    profile_url=target_profile_url,
                    outreach_profile_id=outreach_profile_id,
                    profile_data=profile_data,
                    create_if_not_exists=True
                )
            else:
                db_profile = get_target_profile_by_url(db, str(target_profile_url), outreach_profile_id=outreach_profile_id)
                if not db_profile:
                    raise ValueError(f"No target profile found for URL {target_profile_url}")
                
            if message_sent:
                chat_history = create_chat_history(
                    db,
                    user_id=user_id,
                    outreach_profile_id=outreach_profile_id,
                    target_profile_id=db_profile.id,
                    message_role="outbound",
                    message=message
                )
                create_action(
                    db=db,
                    user_id=user_id,
                    target_profile_id=db_profile.id,
                    outreach_profile_id=outreach_profile_id,
                    action_type="outbound_message",
                    status="success",
                    details={"task_id": self.request.id},
                    chat_history_id=chat_history.id
                )
            else:
                create_action(
                    db=db,
                    user_id=user_id,
                    target_profile_id=db_profile.id,
                    outreach_profile_id=outreach_profile_id,
                    action_type="outbound_message",
                    status="failed",
                    details={"task_id": self.request.id}
                )
    except Exception as e:
        logger.error(f"Send message task failed {current_attempt}/{max_attempts}: {str(e)}")
        self.retry(exc=e, countdown=60)
