"""
Campaign Scheduler Tasks

Implements Celery Beat-based campaign scheduling where each campaign step
is scheduled to execute at a specific time (datetime.now() + delay_timestamp)
rather than using sleep/wait mechanisms.
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import func
from celery.exceptions import MaxRetriesExceededError

from app.celery_app import celery_app
from app.database import SyncSessionLocal
from app import models
from app.crud_sync import (
    get_user_id_by_outreach_profile,
    get_target_profile_by_url,
    create_scheduled_campaign_task,
    update_scheduled_task_status,
    create_action,
    update_target_profile,
    create_campaign_history,
    create_campaign_step_history,
    get_campaign_history_by_id,
    cancel_scheduled_tasks_for_campaign,
)
from app.services.service_manager import LinkedInMicroserviceService
from app.tasks.campaign_watchers import (
    connection_watcher,
    incoming_message_watcher,
    _trigger_next_campaign_step,
    enqueue_contact_sync_task_if_needed,
)
from app.utils.helpers import render_message
from app.utils.locks import profile_lock
from app.utils.quotas import reserve_action_quota
from app.settings import (
    logger,
    CELERY_WORKER_CHECK_INTERVAL,
    N8N_WEBHOOK_URL,
    WATCHER_MIN_RUNTIME_SECONDS,
    CONNECTION_WATCHER_MAX_WAIT_SECONDS,
    CONNECTION_WATCHER_CHECK_INTERVAL,
    INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL,
    SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
    LINKEDIN_MAX_TOTAL_ACTIONS_PER_DAY,
    LINKEDIN_MAX_STEP_RETRIES,
    TERMINATE_CAMPAIGN_ON_MAX_RETRIES,
)

OPEN_ACTION_STATUSES = {"scheduled", "executing", "triggered_early"}


def _apply_open_action_cap(outreach_profile_id: int, desired_time: datetime) -> tuple[datetime, int]:
    """
    Ensures the outreach profile does not exceed the configured number of
    pending (scheduled/executing) actions for a given UTC day.
    Returns the (potentially shifted) execution time and number of adjustments made.
    """
    limit = LINKEDIN_MAX_TOTAL_ACTIONS_PER_DAY
    if limit <= 0:
        return desired_time, 0

    adjusted_time = desired_time
    adjustments = 0
    while True:
        day_start = adjusted_time.astimezone(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)
        with SyncSessionLocal() as db:
            pending_actions = (
                db.query(func.count(models.ScheduledCampaignTask.id))
                .join(
                    models.CampaignHistory,
                    models.CampaignHistory.id == models.ScheduledCampaignTask.campaign_history_id,
                )
                .filter(
                    models.CampaignHistory.outreach_profile_id == outreach_profile_id,
                    models.ScheduledCampaignTask.status.in_(OPEN_ACTION_STATUSES),
                    models.ScheduledCampaignTask.scheduled_at >= day_start,
                    models.ScheduledCampaignTask.scheduled_at < day_end,
                )
                .scalar()
                or 0
            )

        if pending_actions < limit:
            return adjusted_time, adjustments

def _terminate_campaign(db, campaign_history_id: int, reason: str):
    campaign_history = get_campaign_history_by_id(db, campaign_history_id)
    if not campaign_history:
        return
    cancel_scheduled_tasks_for_campaign(db, campaign_history_id)
    campaign_history.status = "failed"
    details = campaign_history.details or {}
    details["termination_reason"] = reason
    details["terminated_at"] = datetime.now(timezone.utc).isoformat()
    campaign_history.details = details
    campaign_history.modified_at = datetime.now(timezone.utc)
    db.commit()

@celery_app.task(
    name="app.tasks.campaign_scheduler.run_campaign", 
    bind=True
)
def run_campaign_with_scheduling(
    self,
    campaign_payload_dict: dict,
    campaign_step_templates_list: list,
    campaign_history_map: dict = None  # Optional: map of target_url -> campaign history info
):
    """
    Orchestrate campaign execution by scheduling individual step tasks.
    This is the entry point called from the API.
    
    Strategy:
    1. For each target profile, schedule all campaign steps
    2. Calculate execution time: datetime.now() + cumulative delay
    3. Store scheduled task IDs in database for tracking/cancellation
    
    Args:
        campaign_payload_dict: Campaign configuration
        campaign_step_templates_list: List of step templates
        campaign_history_map: Optional map of target_url -> {campaign_history_id, campaign_runtime_id, target_profile_id}
                              If provided, uses existing campaign histories instead of creating new ones.
    """
    celery_task_id = self.request.id
    logger.info(f"📌 {celery_task_id}: Campaign orchestration started")

    try:
        campaign_template_id = campaign_payload_dict.get("campaign_template_id")
        outreach_profile_id = campaign_payload_dict.get("outreach_profile_id")
        target_profiles = campaign_payload_dict.get("target_profiles")

        # Get user ID by outreach profile ID
        with SyncSessionLocal() as db:
            user_id = get_user_id_by_outreach_profile(db, outreach_profile_id)
            if not user_id:
                logger.error(f"Could not find user for outreach_profile {outreach_profile_id}")
                return {
                    "status": "failed", 
                    "error": "user_not_found"
                }
        
        scheduled_tasks_summary = []
        # Schedule tasks for each target
        for target in target_profiles:
            target_url = target["url"]
            target_variables = target["variables"]
            
            # Check if we have pre-created campaign history for this target
            existing_history = campaign_history_map.get(target_url) if campaign_history_map else None
            
            if existing_history:
                # Use existing campaign history created by the API
                campaign_history_id = existing_history["campaign_history_id"]
                campaign_runtime_id = uuid.UUID(existing_history["campaign_runtime_id"])
                target_profile_id = existing_history["target_profile_id"]
                logger.info(
                    f"📌 {celery_task_id}: Using existing campaign history {campaign_history_id} "
                    f"(runtime {campaign_runtime_id}) for {target_url}"
                )
            else:
                # Fallback: Create campaign history (legacy behavior)
                logger.warning(
                    f"📌 {celery_task_id}: No pre-created campaign history found for {target_url}, creating new one"
                )
                campaign_runtime_id = uuid.uuid4()
                
                with SyncSessionLocal() as db:
                    target_profile = get_target_profile_by_url(db, target_url, outreach_profile_id=outreach_profile_id)
                    if not target_profile:
                        # Initialize target profile with outreach_profile_id
                        update_target_profile(
                            db, 
                            profile_url=target_url, 
                            outreach_profile_id=outreach_profile_id,
                            profile_data=None
                        )
                        target_profile = get_target_profile_by_url(db, target_url, outreach_profile_id=outreach_profile_id)
                    target_profile_id = target_profile.id
                    
                    # Create campaign history record
                    campaign_history = create_campaign_history(
                        db=db,
                        user_id=user_id,
                        campaign_runtime_id=campaign_runtime_id,
                        outreach_profile_id=outreach_profile_id,
                        target_profile_id=target_profile_id,
                        campaign_template_id=campaign_template_id,
                        number_of_steps=len(campaign_step_templates_list)
                    )
                    campaign_history_id = campaign_history.id
            
            # Calculate execution times and schedule tasks
            current_time = datetime.now(timezone.utc)
            target_start_time = current_time
            
            # Schedule tasks for each step
            for step in sorted(campaign_step_templates_list, key=lambda s: s["step_number"]):
                step_number = step["step_number"]
                delay_seconds = step["delay_timestamp"]  # Already converted to seconds
                
                # Calculate when this step should execute
                execution_time = current_time + timedelta(seconds=delay_seconds)
                execution_time, push_count = _apply_open_action_cap(outreach_profile_id, execution_time)
                if push_count:
                    logger.info(
                        f"📅 Daily pending-action cap reached for outreach {outreach_profile_id}. "
                        f"Pushed step {step_number} to {execution_time.isoformat()}."
                    )
                cumulative_delay_seconds = int((execution_time - target_start_time).total_seconds())

                # Prepare task kwargs
                task_kwargs = {
                    "target_profile_id": target_profile_id,
                    "target_url": target_url,
                    "outreach_profile_id": outreach_profile_id,
                    "user_id": user_id,
                    "step": step,
                    "variables": target_variables,
                    "campaign_history_id": campaign_history_id,
                    "campaign_template_id": campaign_template_id,
                    "campaign_runtime_id": str(campaign_runtime_id),  # Convert UUID to string for JSON
                    "delay_seconds": delay_seconds
                }
                
                # Schedule the step execution task
                task_result = execute_campaign_step.apply_async(
                    kwargs=task_kwargs,
                    eta=execution_time  # Execute at this specific time
                )
                
                # Store scheduled task in database
                with SyncSessionLocal() as db:
                    # Create scheduled campaign task record in database
                    create_scheduled_campaign_task(
                        db=db,
                        target_profile_id=target_profile_id,
                        step_number=step_number,
                        celery_task_id=task_result.id,
                        task_name="execute_campaign_step",
                        scheduled_at=execution_time,
                        campaign_history_id=campaign_history_id,
                        details={
                            "target_url": target_url,
                            "step_action": step["action"],
                            "delay_seconds": delay_seconds,
                            "cumulative_delay": cumulative_delay_seconds,
                            "kwargs": task_kwargs  # Store full kwargs for re-queuing
                        }
                    )
                    # Create action record in database
                    create_action(
                        db=db,
                        user_id=user_id,
                        outreach_profile_id=outreach_profile_id,
                        target_profile_id=target_profile_id,
                        action_type="schedule_campaign",
                        status="success",
                        details={"celery_task_id": celery_task_id}
                    )

                scheduled_tasks_summary.append({
                    "target_url": target_url,
                    "step_number": step_number,
                    "action": step["action"],
                    "scheduled_at": execution_time.isoformat(),
                    "celery_task_id": task_result.id
                })
                
                logger.info(
                    f"⌚ PARENT {self.request.id}: CHILD {task_result.id}: Scheduled step {step_number} ({step['action']}) for {target_url} "
                    f"at {execution_time.isoformat()} (in {cumulative_delay_seconds}s)"
                )
                
                current_time = execution_time
        
        logger.info(f"✅ {celery_task_id}: Campaign orchestration completed. Scheduled {len(scheduled_tasks_summary)} tasks")
        
        return {
            "status": "success",
            "campaign_runtime_id": str(campaign_runtime_id),
            "parent_task_id": celery_task_id,
            "message": f"Scheduled {len(scheduled_tasks_summary)} campaign step tasks for {len(target_profiles)} targets",
            "total_targets": len(target_profiles),
            "total_steps_per_target": len(campaign_step_templates_list),
            "scheduled_tasks": scheduled_tasks_summary
        }
    except Exception as e:
        logger.error(f"❌ {celery_task_id}: Campaign orchestration failed: {e}")
        return {
            "status": "failed",
            "error": str(e)
        }

@celery_app.task(
    name="app.tasks.campaign_scheduler.execute_campaign_step",
    bind=True,
    max_retries=LINKEDIN_MAX_STEP_RETRIES,
)
def execute_campaign_step(
    self,
    target_profile_id: int,
    target_url: str,
    outreach_profile_id: int,
    user_id: int,
    step: dict,
    variables: dict,
    campaign_template_id: int,
    campaign_history_id: int,
    campaign_runtime_id: uuid.UUID,
    delay_seconds: int
):
    """
    Execute a single campaign step at the scheduled time.
    This task is triggered by Celery Beat at the calculated ETA.
    
    Args:
        step: dict with keys: step_number, action, additional_note_template, message_template, delay_timestamp
    """
    celery_task_id = self.request.id
    parent_task_id = self.request.parent_id
    step_number = step["step_number"]
    action = step["action"]
    
    logger.info(
        f"🧰 PARENT {parent_task_id}: CHILD {celery_task_id}: Executing campaign step {step_number} ({action}) "
        f"for target {target_url}"
    )
    
    quota_result = reserve_action_quota(outreach_profile_id, action)
    if not quota_result.allowed:
        wait_seconds = max(int(quota_result.retry_after_seconds or 3600), 300)
        detail = (
            f"{action} suppressed: {quota_result.reason or quota_result.quota_type} "
            f"limit ({quota_result.limit}/day) reached. Resets at "
            f"{quota_result.reset_at.isoformat() if quota_result.reset_at else 'next cycle'}."
        )
        metadata = {
            "detail": detail,
            "action": action,
            "quota_type": quota_result.quota_type,
            "limit": quota_result.limit,
            "remaining": quota_result.remaining,
            "reset_at": quota_result.reset_at.isoformat() if quota_result.reset_at else None,
        }
        logger.warning(
            f"⏳ PARENT {parent_task_id}: CHILD {celery_task_id}: Rate limit hit for outreach "
            f"{outreach_profile_id}; retrying in {wait_seconds}s."
        )
        with SyncSessionLocal() as db:
            update_scheduled_task_status(db, celery_task_id, "scheduled")
            create_action(
                db=db,
                user_id=user_id,
                outreach_profile_id=outreach_profile_id,
                target_profile_id=target_profile_id,
                action_type=action,
                status="rate_limited",
                details={
                    **metadata,
                    "celery_task_id": celery_task_id,
                    "parent_task_id": parent_task_id,
                    "campaign_history_id": campaign_history_id,
                    "campaign_runtime_id": str(campaign_runtime_id),
                    "campaign_template_id": campaign_template_id,
                    "step_number": step_number,
                },
            )
            rate_event = models.LinkedInScrapeEvent(
                outreach_profile_id=outreach_profile_id,
                target_profile_id=target_profile_id,
                campaign_history_id=campaign_history_id,
                event_type="rate_limit",
                detail=detail,
                action_taken="rescheduled",
                metadata_json=metadata,
            )
            db.add(rate_event)
            db.commit()
        raise self.retry(exc=RuntimeError("rate_limited"), countdown=wait_seconds)

    
    try:
        # Update scheduled task status to "executing"
        with SyncSessionLocal() as db:
            update_scheduled_task_status(db, celery_task_id, "executing")

        # Execute the action based on step type
        if action == "send_connection":
            result = _execute_connection_request(
                celery_task_id=celery_task_id,
                parent_task_id=parent_task_id,
                campaign_history_id=campaign_history_id,
                campaign_runtime_id=campaign_runtime_id,
                campaign_template_id=campaign_template_id,
                target_url=target_url,
                target_profile_id=target_profile_id,
                outreach_profile_id=outreach_profile_id,
                user_id=user_id,
                step=step,
                variables=variables,
                step_number=step_number,
                max_wait_seconds=delay_seconds
            )
        elif action == "send_message":
            result = _execute_send_message(
                celery_task_id,
                target_url,
                target_profile_id,
                outreach_profile_id,
                user_id,
                step,
                variables,
                campaign_history_id,
                step_number,
                max_wait_seconds=delay_seconds
            )
        else:
            logger.error(f"Unknown action type: {action}")
            result = {"status": "failed", "details": "unknown_action"}
        
        # Update scheduled task status based on result
        with SyncSessionLocal() as db:
            # Create campaign step history record in database
            campaign_step_history = create_campaign_step_history(
                db=db,
                campaign_history_id=campaign_history_id,
                campaign_runtime_id=campaign_runtime_id,
                step_number=step_number,
                action=action,
                status=result.get("status"),
                details=result.get("details")
            )
            # Create action record in database
            create_action(
                db=db,
                user_id=user_id,
                outreach_profile_id=outreach_profile_id,
                target_profile_id=target_profile_id,
                action_type=action,
                status=result.get("status"),
                details={
                    "details": result.get("details"),
                    "celery_task_id": celery_task_id,
                    "parent_task_id": parent_task_id,
                    "campaign_history_id": campaign_history_id,
                    "campaign_runtime_id": str(campaign_runtime_id),
                    "campaign_step_history_id": campaign_step_history.id,
                    "campaign_template_id": campaign_template_id,
                    "step_number": step_number
                }
            )
            if result.get("status") == "success":
                update_scheduled_task_status(
                    db, celery_task_id, "executed", 
                    executed_at=datetime.now(timezone.utc)
                )
            else:
                update_scheduled_task_status(db, celery_task_id, "failed")
            
            # Check if this is the last step in the campaign
            campaign_history = get_campaign_history_by_id(db, campaign_history_id)
            if campaign_history and step_number == campaign_history.number_of_steps:
                # Get the delay_timestamp for this last step to know when to cancel watchers
                # delay_seconds was already calculated and passed to this function
                watcher_cancel_delay = max(
                    int(delay_seconds or 0), WATCHER_MIN_RUNTIME_SECONDS
                )
                
                logger.info(
                    f"🏁 {celery_task_id}: Last step ({step_number}/{campaign_history.number_of_steps}) "
                    f"completed for campaign {campaign_history_id}. "
                    f"Scheduling watcher cancellation in {watcher_cancel_delay} seconds..."
                )
                
                # Schedule watcher cancellation AFTER the delay_timestamp period
                # This gives the target time to respond within the expected timeframe
                cancel_watchers_task.apply_async(
                    args=[target_profile_id, outreach_profile_id, campaign_history_id],
                    countdown=watcher_cancel_delay
                )
                
                # Mark campaign as completed (but watchers will be cancelled later)
                campaign_history.status = "completed"
                campaign_history.finished_at = datetime.now(timezone.utc)
                db.commit()
                
                logger.info(
                    f"✅ Campaign {campaign_history_id} marked as completed. "
                    f"Watchers will be cancelled in {watcher_cancel_delay}s if no response received."
                )
        
        logger.info(f"✅ PARENT {parent_task_id}: CHILD {celery_task_id}: Step {step_number} completed with status: {result.get('status')}")
        return result
        
    except MaxRetriesExceededError as mre:
        logger.error(
            f"❌ PARENT {parent_task_id}: CHILD {celery_task_id}: Max retries exceeded for step {step_number} ({action})."
        )
        with SyncSessionLocal() as db:
            update_scheduled_task_status(db, celery_task_id, "failed")
            create_action(
                db=db,
                user_id=user_id,
                outreach_profile_id=outreach_profile_id,
                target_profile_id=target_profile_id,
                action_type=action,
                status="failed",
                details={
                    "details": "max_retries_exceeded",
                    "celery_task_id": celery_task_id,
                    "parent_task_id": parent_task_id,
                    "campaign_history_id": campaign_history_id,
                    "campaign_runtime_id": str(campaign_runtime_id),
                    "campaign_template_id": campaign_template_id,
                    "step_number": step_number,
                    "retry_attempts": self.request.retries,
                },
            )
            if TERMINATE_CAMPAIGN_ON_MAX_RETRIES:
                _terminate_campaign(db, campaign_history_id, "max_retries_exceeded")
        return {"status": "failed", "details": "max_retries_exceeded"}

    except RuntimeError as lock_err:
        message = str(lock_err)
        if "Timeout waiting for lock" in message:
            retry_delay = SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS
            with SyncSessionLocal() as db:
                update_scheduled_task_status(db, celery_task_id, "scheduled")
            logger.warning(
                f"🔒 PARENT {parent_task_id}: CHILD {celery_task_id}: Lock contention for outreach {outreach_profile_id}. "
                f"Retrying in {retry_delay}s."
            )
            raise self.retry(exc=lock_err, countdown=retry_delay)
        raise
    except Exception as e:
        logger.error(f"❌ PARENT {parent_task_id}: CHILD {celery_task_id}: Error executing step {step_number}: {e}")
        
        # Mark task as failed
        with SyncSessionLocal() as db:
            update_scheduled_task_status(db, celery_task_id, "failed")
        
        return {"status": "failed", "details": str(e)}


def _execute_connection_request(
    celery_task_id: str,
    parent_task_id: str,
    campaign_history_id: int,
    campaign_runtime_id: uuid.UUID,
    campaign_template_id: int,
    target_url: str,
    target_profile_id: int,
    outreach_profile_id: int,
    user_id: int,
    step: dict,
    variables: dict,
    step_number: int,
    max_wait_seconds: int
) -> dict:
    """
    Execute connection request action.
    """
    # Render message template if provided
    additional_note = None
    if step.get("additional_note_template"):
        additional_note = render_message(step["additional_note_template"], variables)

    
    with profile_lock(outreach_profile_id=outreach_profile_id):
        # Create LinkedIn service
        service = LinkedInMicroserviceService(outreach_profile_id=outreach_profile_id)
        ok = service.start()
        
        # Login to LinkedIn (if not already logged in)
        if not ok:
            logger.error(f"{celery_task_id}: Failed to login to Flask microservice")
            service.close()
            return {"status": "failed", "details": "login_failed"}
        
        # Fetch profile info
        profile_data = service.fetch_profile_info(target_url)
        if not profile_data:
            logger.error(f"{celery_task_id}: Couldn't fetch profile data for {target_url}")
            service.close()
            
            return {"status": "failed", "details": "fetch_profile_failed"}
    
    # Update target profile data
    with SyncSessionLocal() as db:
        update_target_profile(
            db=db, 
            profile_url=target_url, 
            outreach_profile_id=outreach_profile_id,
            profile_data=profile_data
        )
        create_action(
            db=db,
            user_id=user_id,
            outreach_profile_id=outreach_profile_id,
            target_profile_id=target_profile_id,
            action_type="fetch_profile",
            status="success",
            details={
                "celery_task_id": celery_task_id,
                "parent_task_id": parent_task_id,
                "campaign_history_id": campaign_history_id,
                "campaign_runtime_id": str(campaign_runtime_id),
                "campaign_template_id": campaign_template_id,
                "step_number": step_number
            }
        )
    
    # Check if already connected
    if profile_data.get("connected"):
        logger.warning(f"{celery_task_id}: Already connected with {target_url}")
        with profile_lock(outreach_profile_id=outreach_profile_id):
            service.close()

        with SyncSessionLocal() as db:
            enqueue_contact_sync_task_if_needed(
                db,
                campaign_history_id,
                target_profile_id,
                outreach_profile_id,
                target_url,
            )
            _trigger_next_campaign_step(
                db,
                campaign_history_id,
                step_number + 1,
                target_profile_id,
                target_url,
                outreach_profile_id,
                user_id,
                campaign_template_id,
                campaign_runtime_id
            )
       
        return {"status": "ignored", "details": "already_connected"}
    
    # Check if connection pending
    if profile_data.get("connection_pending"):
        logger.warning(f"{celery_task_id}: Connection pending with {target_url}")
        with profile_lock(outreach_profile_id=outreach_profile_id):
            service.close()
        return {"status": "ignored", "details": "connection_pending"}

    # Send connection request
    logger.info(f"🔗 {celery_task_id}: Sending connection request to {target_url}")
    with profile_lock(outreach_profile_id=outreach_profile_id):
        request_response = service.send_connection_request(target_url, additional_note=additional_note)
        service.close()
    
    if not request_response or not request_response.get("success"):
        error_detail = (request_response or {}).get("error") or "connection_request_failed"
        logger.error(f"❌ {celery_task_id}: Failed to send connection request ({error_detail})")
        return {"status": "failed", "details": error_detail}
    
    logger.info(f"✅ {celery_task_id}: Connection request sent successfully")
    
    # Schedule connection watcher (starts immediately, checks every 5 min)
    connection_timeout = max(
        int(max_wait_seconds or 0), CONNECTION_WATCHER_MAX_WAIT_SECONDS
    )

    watcher_result = connection_watcher.apply_async(
        kwargs={
            "target_profile_id": target_profile_id,
            "target_url": target_url,
            "outreach_profile_id": outreach_profile_id,
            "campaign_history_id": campaign_history_id,
            "campaign_runtime_id": campaign_runtime_id,
            "step": step,
            "variables": variables,
            "campaign_template_id": campaign_template_id,
            "next_step_number": step_number + 1,
            "max_wait_seconds": connection_timeout,
        },
        countdown=CONNECTION_WATCHER_CHECK_INTERVAL
    )
    
    logger.info(
        f"👀 {celery_task_id}: Started connection watcher (task_id: {watcher_result.id}) "
        f"for {target_url} with max wait {connection_timeout} seconds"
    )
    
    return {"status": "success", "details": "connection_request_sent", "watcher_task_id": watcher_result.id}


def _execute_send_message(
    celery_task_id: str,
    target_url: str,
    target_profile_id: int,
    outreach_profile_id: int,
    user_id: int,
    step: dict,
    variables: dict,
    campaign_history_id: int,
    step_number: int,
    max_wait_seconds: int
) -> dict:
    """
    Execute send message action.
    """
    # Render message template
    if not step.get("message_template"):
        logger.error(f"{celery_task_id}: No message template provided for send_message action")
        return {"status": "failed", "details": "no_message_template"}
    
    message = render_message(step["message_template"], variables)

    # Ensure target profile record exists for this outreach profile
    with SyncSessionLocal() as db:
        target_record = (
            db.query(models.TargetLinkedInProfile)
            .filter(
                models.TargetLinkedInProfile.id == target_profile_id,
                models.TargetLinkedInProfile.outreach_profile_id == outreach_profile_id,
            )
            .first()
        )

    if not target_record:
        logger.warning(
            f"{celery_task_id}: Target profile {target_profile_id} not found for outreach {outreach_profile_id}; skipping message."
        )
        return {"status": "skipped", "details": "target_not_found"}

    all_messages = None
    is_connected = bool(target_record.connected)
    is_pending = bool(target_record.connection_pending)

    with profile_lock(outreach_profile_id=outreach_profile_id):
        # Create LinkedIn service
        service = LinkedInMicroserviceService(outreach_profile_id=outreach_profile_id)
        ok = service.start()

        # Login to LinkedIn (if not already logged in)
        if not ok:
            logger.error(f"{celery_task_id}: Failed to login to Flask microservice")
            service.close()
            return {"status": "failed", "details": "login_failed"}

        if not is_connected:
            logger.info(
                f"{celery_task_id}: Connection not confirmed in DB; checking LinkedIn for {target_url} before sending message"
            )
            profile_data = service.fetch_profile_info(target_url)
            if not profile_data:
                logger.error(f"{celery_task_id}: Couldn't fetch profile data for {target_url}; skipping message.")
                service.close()
                return {"status": "failed", "details": "fetch_profile_failed"}

            is_connected = bool(profile_data.get("connected"))
            is_pending = bool(profile_data.get("connection_pending"))

            now_ts = datetime.now(timezone.utc)
            with SyncSessionLocal() as db:
                target_state = (
                    db.query(models.TargetLinkedInProfile)
                    .filter(
                        models.TargetLinkedInProfile.id == target_profile_id,
                        models.TargetLinkedInProfile.outreach_profile_id == outreach_profile_id,
                    )
                    .first()
                )

                if target_state:
                    target_state.connected = is_connected
                    target_state.connection_pending = is_pending
                    target_state.last_fetched_at = now_ts
                    target_state.modified_at = now_ts
                    db.commit()
                    db.refresh(target_state)
                    logger.info(
                        f"{celery_task_id}: Updated connection status in DB for {target_url} "
                        f"(connected={is_connected}, pending={is_pending})"
                    )
                else:
                    logger.warning(
                        f"{celery_task_id}: Target profile {target_profile_id} disappeared before update; skipping message."
                    )
                    service.close()
                    return {"status": "skipped", "details": "target_not_found"}
        else:
            logger.info(
                f"{celery_task_id}: Using cached connection status from DB for {target_url} "
                f"(connected={is_connected}, pending={is_pending})"
            )

        if not is_connected:
            logger.info(
                f"{celery_task_id}: Outreach profile {outreach_profile_id} is not connected to {target_url}; skipping send_message step."
            )
            service.close()
            return {"status": "skipped", "details": "target_not_connected"}

        if is_pending:
            logger.info(
                f"{celery_task_id}: Connection request to {target_url} is still pending; skipping send_message step."
            )
            service.close()
            return {"status": "skipped", "details": "connection_pending"}

        # Send message
        logger.info(f"✉️ {celery_task_id}: Sending message to {target_url}")
        message_sent = service.send_message(target_url, message)

        if not message_sent:
            logger.error(f"❌ {celery_task_id}: Failed to send message; verifying connection state for {target_url}")
            profile_after_failure = service.fetch_profile_info(target_url)
            now_ts = datetime.now(timezone.utc)
            if profile_after_failure:
                is_connected = bool(profile_after_failure.get("connected"))
                is_pending = bool(profile_after_failure.get("connection_pending"))
                with SyncSessionLocal() as db:
                    target_state = (
                        db.query(models.TargetLinkedInProfile)
                        .filter(
                            models.TargetLinkedInProfile.id == target_profile_id,
                            models.TargetLinkedInProfile.outreach_profile_id == outreach_profile_id,
                        )
                        .first()
                    )
                    if target_state:
                        target_state.connected = is_connected
                        target_state.connection_pending = is_pending
                        target_state.last_fetched_at = now_ts
                        target_state.modified_at = now_ts
                        db.commit()
                        db.refresh(target_state)
                        logger.info(
                            f"{celery_task_id}: Refreshed connection status after failure for {target_url} "
                            f"(connected={is_connected}, pending={is_pending})"
                        )
                    else:
                        logger.warning(
                            f"{celery_task_id}: Target profile {target_profile_id} missing during failure refresh."
                        )
                if not is_connected:
                    service.close()
                    return {"status": "skipped", "details": "target_not_connected"}
            else:
                logger.warning(
                    f"{celery_task_id}: Unable to refetch profile info for {target_url} after message failure."
                )
            service.close()
            return {"status": "failed", "details": "send_message_failed"}

        logger.info(f"✅ {celery_task_id}: Message sent successfully")

        # Fetch all messages from chat to establish baseline for incoming message watcher
        logger.info(f"📥 {celery_task_id}: Fetching all messages to establish baseline for {target_url}")
        all_messages = service.get_all_messages_from_chat(target_url)
        service.close()
    
    if all_messages and all_messages is not False:
        # Store messages in ChatHistory
        with SyncSessionLocal() as db:
            # Delete existing chat history for this conversation
            db.query(models.ChatHistory).filter(
                models.ChatHistory.target_profile_id == target_profile_id,
                models.ChatHistory.outreach_profile_id == outreach_profile_id
            ).delete()
            
            chat_records: list[models.ChatHistory] = []
            skipped_messages = 0
            for msg in all_messages:
                raw_content = msg.get("content")
                if raw_content is None:
                    skipped_messages += 1
                    continue
                if isinstance(raw_content, str):
                    cleaned_content = raw_content.strip()
                else:
                    cleaned_content = str(raw_content).strip()
                if not cleaned_content:
                    skipped_messages += 1
                    continue

                chat_records.append(
                    models.ChatHistory(
                        outreach_profile_id=outreach_profile_id,
                        target_profile_id=target_profile_id,
                        message_role=msg.get("type"),
                        content=cleaned_content,
                        message_sent_at=msg.get("timestamp") if msg.get("timestamp") else None,
                    )
                )
            
            if chat_records:
                sample = []
                for rec in chat_records[:5]:
                    ts = rec.message_sent_at
                    if ts is not None and hasattr(ts, "isoformat"):
                        ts_repr = ts.isoformat()
                    else:
                        ts_repr = ts
                    sample.append(
                        {
                            "role": rec.message_role,
                            "content_preview": rec.content[:120],
                            "timestamp": ts_repr,
                        }
                    )
                logger.info(
                    "%s: Prepared %s chat record(s) for %s (sample=%s)",
                    celery_task_id,
                    len(chat_records),
                    target_url,
                    sample,
                )
                db.bulk_save_objects(chat_records)
                db.commit()
                logger.info(
                    f"💾 {celery_task_id}: Stored {len(chat_records)} messages in ChatHistory for {target_url} "
                    f"(skipped {skipped_messages} empty entries)"
                )
            else:
                logger.warning(
                    f"⚠️ {celery_task_id}: All fetched messages for {target_url} were empty; "
                    "skipping ChatHistory write."
                )
    else:
        logger.warning(f"⚠️ {celery_task_id}: Could not fetch messages for baseline, watcher may not work correctly")
    
    # Schedule incoming message watcher (starts in 5 min, checks every 5 min)
    message_watcher_timeout = max(
        int(max_wait_seconds or 0), WATCHER_MIN_RUNTIME_SECONDS
    )

    watcher_kwargs = {
        "target_profile_id": target_profile_id,
        "target_url": target_url,
        "outreach_profile_id": outreach_profile_id,
        "user_id": user_id,
        "n8n_webhook_url": N8N_WEBHOOK_URL,
        "max_wait_seconds": message_watcher_timeout,
    }

    watcher_result = incoming_message_watcher.apply_async(
        kwargs=watcher_kwargs,
        countdown=INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL
    )
    
    # Track the watcher task in database
    with SyncSessionLocal() as db:
        create_scheduled_campaign_task(
            db=db,
            target_profile_id=target_profile_id,
            step_number=step_number,  # Associate with the step that triggered it
            celery_task_id=watcher_result.id,
            task_name="incoming_message_watcher",
            scheduled_at=datetime.now(timezone.utc)
            + timedelta(seconds=INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL),
            campaign_history_id=campaign_history_id,  # Link watcher to campaign for UI visibility
            details={
                "target_url": target_url,
                "outreach_profile_id": outreach_profile_id,  # Store for filtering when cancelling
                "watcher_type": "incoming_message",
                "triggered_by_step": step_number,
                "max_wait_seconds": message_watcher_timeout,
                "started_at": datetime.now(timezone.utc).isoformat()
            }
        )
    
    logger.info(
        f"👀 {celery_task_id}: Started incoming message watcher (task_id: {watcher_result.id}) "
        f"for {target_url} with max wait {message_watcher_timeout} seconds"
    )
    
    return {"status": "success", "details": "message_sent", "watcher_task_id": watcher_result.id}


@celery_app.task(name="cancel_watchers_task", bind=True)
def cancel_watchers_task(self, target_profile_id: int, outreach_profile_id: int, campaign_history_id: int):
    """
    Celery task to cancel message watchers after the delay_timestamp period.
    
    This task is scheduled when the last campaign step completes.
    It waits for the delay_timestamp period to elapse, then:
    1. Checks if the target responded during that time
    2. If no response, cancels the message watchers
    3. If target responded, watchers were already cancelled by incoming_message_watcher
    
    Args:
        target_profile_id: ID of the target profile
        outreach_profile_id: ID of the outreach profile
        campaign_history_id: ID of the campaign history record
    """
    celery_task_id = self.request.id
    
    logger.info(
        f"⏰ {celery_task_id}: Executing scheduled watcher cancellation for "
        f"campaign {campaign_history_id}, target {target_profile_id}, outreach {outreach_profile_id}"
    )
    
    with SyncSessionLocal() as db:
        # Check if campaign is still marked as completed (not paused by incoming message)
        campaign_history = get_campaign_history_by_id(db, campaign_history_id)
        
        if not campaign_history:
            logger.warning(f"Campaign history {campaign_history_id} not found, skipping watcher cancellation")
            return {"status": "skipped", "reason": "campaign_not_found"}
        
        if campaign_history.status == "paused":
            logger.info(
                f"✅ Campaign {campaign_history_id} is paused (target responded!). "
                f"Watchers were already cancelled. Nothing to do."
            )
            return {"status": "skipped", "reason": "target_responded"}
        
        # Target didn't respond - cancel watchers
        logger.info(
            f"❌ No response received during delay period for campaign {campaign_history_id}. "
            f"Cancelling watchers..."
        )
        
        _cancel_message_watchers_for_target(db, target_profile_id, outreach_profile_id)
        
        return {"status": "success", "watchers_cancelled": True}


def _cancel_message_watchers_for_target(db, target_profile_id: int, outreach_profile_id: int):
    """
    Cancel all active incoming_message_watcher tasks for a specific target AND outreach profile.
    Called when campaign completes without receiving a response.
    
    Note: We filter by both target_profile_id AND outreach_profile_id because
    multiple outreach profiles might be running campaigns to the same target.
    """
    # Find all scheduled/executing incoming_message_watcher tasks for this target+outreach combination
    active_watchers = db.query(models.ScheduledCampaignTask).filter(
        models.ScheduledCampaignTask.target_profile_id == target_profile_id,
        models.ScheduledCampaignTask.task_name == "incoming_message_watcher",
        models.ScheduledCampaignTask.status.in_(["scheduled", "executing"])
    ).all()
    
    # Filter by outreach_profile_id from the task details
    # (We store the outreach_profile_id in the task's details or can check via campaign_history)
    filtered_watchers = [
        w for w in active_watchers
        if w.details and w.details.get("outreach_profile_id") == outreach_profile_id
    ]
    
    if not filtered_watchers:
        logger.info(
            f"No active message watchers found for target {target_profile_id} "
            f"and outreach profile {outreach_profile_id}"
        )
        return
    
    logger.info(
        f"Found {len(filtered_watchers)} active message watcher(s) for target {target_profile_id} "
        f"and outreach profile {outreach_profile_id}"
    )
    
    for watcher in filtered_watchers:
        # Revoke the Celery task
        celery_app.control.revoke(watcher.celery_task_id, terminate=True)
        
        # Update status in database
        watcher.status = "cancelled"
        watcher.details = watcher.details or {}
        watcher.details["cancelled_reason"] = "Campaign completed without response within delay period"
        watcher.details["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        
        logger.info(
            f"Cancelled watcher task {watcher.celery_task_id} for target {target_profile_id} "
            f"and outreach profile {outreach_profile_id}"
        )
    
    db.commit()
    logger.info(f"✅ Successfully cancelled {len(filtered_watchers)} message watcher(s)")

