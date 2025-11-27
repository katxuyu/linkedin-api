"""
Campaign Watcher Tasks

Implements periodic monitoring tasks for campaigns:
1. connection_watcher - Monitors pending connection requests (interval configurable)
2. incoming_message_watcher - Monitors for new incoming messages (interval configurable)
"""

import requests
import uuid
from datetime import datetime, timezone
from sqlalchemy import and_
from typing import Optional, Dict, List, Any

from app.utils.locks import profile_lock
from app.celery_app import celery_app
from app.database import SyncSessionLocal
from app import models
from app.crud_sync import (
    get_target_profile_by_id,
    update_target_profile,
    update_scheduled_task_status,
    cancel_scheduled_tasks_for_campaign,
    get_user_id_by_outreach_profile,
    create_action,
    pause_all_campaigns_for_target,
    get_target_contact_info,
)
from app.tasks.contact_sync import (
    sync_linkedin_contact_to_gohighlevel,
    IN_PROGRESS_STATUSES,
    STATUS_SYNCED,
    STATUS_NO_ACCOUNT,
)
from app.services.service_manager import LinkedInMicroserviceService
from app.errors import LinkedInCheckpointRequired
from app.settings import (
    logger,
    CELERY_WORKER_CHECK_INTERVAL,
    CONNECTION_WATCHER_MAX_WAIT_SECONDS,
    INCOMING_MESSAGE_WATCHER_MAX_WAIT_SECONDS,
    CONNECTION_WATCHER_CHECK_INTERVAL,
    INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL,
    SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
)


def enqueue_contact_sync_task_if_needed(
    db,
    campaign_history_id: Optional[int],
    target_profile_id: int,
    outreach_profile_id: int,
    target_url: str,
):
    existing_info = get_target_contact_info(db, target_profile_id)
    if existing_info and existing_info.sync_status in (IN_PROGRESS_STATUSES | {STATUS_SYNCED, STATUS_NO_ACCOUNT}):
        logger.debug(
            "Contact sync already in progress or completed for target %s (status=%s)",
            target_profile_id,
            existing_info.sync_status,
        )
        return

    logger.info(
        "Queueing contact sync for target_profile_id=%s outreach_profile_id=%s",
        target_profile_id,
        outreach_profile_id,
    )
    sync_linkedin_contact_to_gohighlevel.delay(
        campaign_history_id=campaign_history_id,
        target_profile_id=target_profile_id,
        outreach_profile_id=outreach_profile_id,
        target_profile_url=target_url,
    )


def _normalize_timestamp_for_compare(value: Any) -> Optional[str]:
    """
    Normalize timestamps so database records (timezone-aware datetime) and scraper payloads
    (ISO strings with or without timezone) compare apples-to-apples.
    All normalized values are returned as ISO strings in UTC.
    """
    if value is None:
        return None

    parsed_dt: Optional[datetime] = None

    if isinstance(value, datetime):
        parsed_dt = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None

        # Ensure we accept both "YYYY-MM-DD HH:MM:SS" and ISO forms.
        candidate_iso = candidate.replace(" ", "T")

        try:
            parsed_dt = datetime.fromisoformat(candidate_iso)
        except ValueError:
            # Fallbacks for common formats that fromisoformat might reject.
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                try:
                    parsed_dt = datetime.strptime(candidate, fmt)
                    break
                except ValueError:
                    continue

            if parsed_dt is None:
                # Could not parse; return the trimmed string to avoid breaking comparisons completely
                return candidate_iso
    else:
        # Attempt to normalize non-string scalars by converting to string
        try:
            return _normalize_timestamp_for_compare(str(value))
        except Exception:
            return None

    if parsed_dt is None:
        return None

    if parsed_dt.tzinfo is None:
        parsed_dt = parsed_dt.replace(tzinfo=timezone.utc)

    return parsed_dt.astimezone(timezone.utc).isoformat()


@celery_app.task(
    name="app.tasks.campaign_watchers.connection_watcher", 
    bind=True
)
def connection_watcher(
    self,
    target_profile_id: int,
    target_url: str,
    outreach_profile_id: int,
    campaign_history_id: int,
    campaign_runtime_id: uuid.UUID,
    step: dict,
    variables: dict,
    campaign_template_id: int,
    next_step_number: int,
    max_wait_seconds: int = CONNECTION_WATCHER_MAX_WAIT_SECONDS
):
    """
    Monitor a target profile to detect when they accept a connection request.
    Executes at the configured interval until connection is accepted or timeout is reached.
    
    Args:
        target_profile_id: Target profile database ID
        target_url: Target LinkedIn profile URL
        outreach_profile_id: Outreach profile ID
        campaign_history_id: Campaign history ID for tracking
        next_step_number: Which step to trigger after connection accepted
        max_wait_seconds: Maximum time to wait for connection (default 1 day)
    """
    try:
        celery_task_id = self.request.id
        logger.info(f"{celery_task_id}: Connection watcher checking {target_url}...")
        
        # Check if we've exceeded max wait time
        with SyncSessionLocal() as db:
            scheduled_task = db.query(models.ScheduledCampaignTask).filter(
                models.ScheduledCampaignTask.celery_task_id == celery_task_id
            ).first()
            
            if scheduled_task:
                elapsed_time = (datetime.now(timezone.utc) - scheduled_task.created_at).total_seconds()
                if elapsed_time > max_wait_seconds:
                    logger.warning(
                        f"⚠️ {celery_task_id}: Connection watcher timeout reached for {target_url} "
                        f"({elapsed_time}s > {max_wait_seconds}s)"
                    )
                    update_scheduled_task_status(db, celery_task_id, "timeout")
                    
                    # Create timeout action
                    user_id = get_user_id_by_outreach_profile(db, outreach_profile_id)
                    if user_id:
                        create_action(
                            db, 
                            user_id, 
                            outreach_profile_id, 
                            target_profile_id,
                            "connection_watcher", 
                            "timeout",
                            details={
                                "celery_task_id": celery_task_id,
                                "elapsed_seconds": elapsed_time,
                                "max_wait_seconds": max_wait_seconds
                            }
                        )
                    
                    return {"status": "timeout", "elapsed_seconds": elapsed_time}
        
    
        # Step 1: Check database first (fast check)
        with SyncSessionLocal() as db:
            target_profile = get_target_profile_by_id(db, target_profile_id)
            
            if not target_profile:
                logger.error(f"{celery_task_id}: Target profile {target_profile_id} not found")
                return {"status": "error", "reason": "target_not_found"}
            
            # If already connected in DB, proceed to next step
            if target_profile.connected:
                logger.info(f"{celery_task_id}: ✅ Connection accepted (found in DB) for {target_url}")
                
                # Unschedule this watcher (mark as executed)
                update_scheduled_task_status(
                    db, celery_task_id, "executed", 
                    executed_at=datetime.now(timezone.utc)
                )
                enqueue_contact_sync_task_if_needed(
                    db,
                    campaign_history_id,
                    target_profile_id,
                    outreach_profile_id,
                    target_url,
                )

                # Trigger next campaign step
                _trigger_next_campaign_step(
                    db, 
                    campaign_history_id, 
                    next_step_number, 
                    target_profile_id, 
                    target_url, 
                    outreach_profile_id, 
                    user_id, 
                    campaign_template_id, 
                    campaign_runtime_id
                )
                
                return {"status": "connected", "source": "database"}
        
        # Step 2: Not connected in DB - fetch fresh data from LinkedIn
        logger.info(f"{celery_task_id}: Not connected in DB, fetching from LinkedIn...")
        
        
        try:
            with profile_lock(outreach_profile_id):
                service = LinkedInMicroserviceService(outreach_profile_id=outreach_profile_id)
                ok = service.start()
                if not ok:
                    logger.error(f"{celery_task_id}: Failed to login to Flask microservice")
                    service.close()
                    return {"status": "error", "reason": "login_failed"}
                
                # Fetch profile info
                profile_data = service.fetch_profile_info(target_url)
                service.close()
            
            if not profile_data:
                logger.warning(f"{celery_task_id}: Could not fetch profile data for {target_url}")
                
                # Reschedule for next check (daily by default)
                connection_watcher.apply_async(
                    kwargs={
                        "target_profile_id": target_profile_id,
                        "target_url": target_url,
                        "outreach_profile_id": outreach_profile_id,
                        "campaign_history_id": campaign_history_id,
                        "campaign_runtime_id": campaign_runtime_id,
                        "step": step,
                        "variables": variables,
                        "campaign_template_id": campaign_template_id,
                        "next_step_number": next_step_number,
                        "max_wait_seconds": max_wait_seconds,
                    },
                    countdown=CONNECTION_WATCHER_CHECK_INTERVAL
                )
                
                return {"status": "pending", "rescheduled": True, "reason": "fetch_failed"}
            
            # Update target profile with fresh data
            with SyncSessionLocal() as db:
                update_target_profile(
                    db, 
                    profile_url=target_url, 
                    outreach_profile_id=outreach_profile_id,
                    profile_data=profile_data
                )
                
                # Check if connected
                if profile_data.get("connected"):
                    logger.info(f"{celery_task_id}: ✅ Connection accepted (found on LinkedIn) for {target_url}")
                    
                    # Unschedule this watcher
                    update_scheduled_task_status(
                        db, 
                        celery_task_id, 
                        "executed",
                        executed_at=datetime.now(timezone.utc)
                    )
                    enqueue_contact_sync_task_if_needed(
                        db,
                        campaign_history_id,
                        target_profile_id,
                        outreach_profile_id,
                        target_url,
                    )

                    # Log action
                    user_id = get_user_id_by_outreach_profile(db, outreach_profile_id)
                    if user_id:
                        create_action(
                            db, 
                            user_id, 
                            outreach_profile_id, 
                            target_profile_id,
                            "connection_accepted", 
                            "success",
                            details={
                                "celery_task_id": celery_task_id
                            }
                        )
                    
                    # Trigger next campaign step
                    _trigger_next_campaign_step(
                        db, 
                        campaign_history_id, 
                        next_step_number, 
                        target_profile_id, 
                        target_url, 
                        outreach_profile_id, 
                        user_id, 
                        campaign_template_id, 
                        campaign_runtime_id
                    )
                    
                    return {"status": "connected", "source": "linkedin"}
                else:
                    # Still pending - reschedule for next check
                    logger.info(
                        f"{celery_task_id}: Connection still pending for {target_url}, "
                        f"rechecking in {CONNECTION_WATCHER_CHECK_INTERVAL} seconds..."
                    )
                    
                    connection_watcher.apply_async(
                        kwargs={
                            "target_profile_id": target_profile_id,
                            "target_url": target_url,
                            "outreach_profile_id": outreach_profile_id,
                            "campaign_history_id": campaign_history_id,
                            "campaign_runtime_id": campaign_runtime_id,
                            "step": step,
                            "variables": variables,
                            "campaign_template_id": campaign_template_id,
                            "next_step_number": next_step_number,
                            "max_wait_seconds": max_wait_seconds,
                        },
                        countdown=CONNECTION_WATCHER_CHECK_INTERVAL
                    )
                    
                    return {"status": "pending", "rescheduled": True}
                    
        except RuntimeError as lock_err:
            if "Timeout waiting for lock" in str(lock_err):
                with SyncSessionLocal() as db:
                    update_scheduled_task_status(db, celery_task_id, "scheduled")
                logger.warning(
                    f"{celery_task_id}: Outreach {outreach_profile_id} busy, retrying connection watcher in "
                    f"{SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS}s."
                )
                connection_watcher.apply_async(
                    kwargs={
                        "target_profile_id": target_profile_id,
                        "target_url": target_url,
                        "outreach_profile_id": outreach_profile_id,
                        "campaign_history_id": campaign_history_id,
                        "campaign_runtime_id": campaign_runtime_id,
                        "step": step,
                        "variables": variables,
                        "campaign_template_id": campaign_template_id,
                        "next_step_number": next_step_number,
                        "max_wait_seconds": max_wait_seconds,
                    },
                    countdown=SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
                )
                return {"status": "locked", "rescheduled": True}
            raise
        except RuntimeError as lock_err:
            if "Timeout waiting for lock" in str(lock_err):
                with SyncSessionLocal() as db:
                    update_scheduled_task_status(db, celery_task_id, "scheduled")
                logger.warning(
                    f"{celery_task_id}: Outreach {outreach_profile_id} busy, retrying connection watcher in "
                    f"{SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS}s."
                )
                connection_watcher.apply_async(
                    kwargs={
                        "target_profile_id": target_profile_id,
                        "target_url": target_url,
                        "outreach_profile_id": outreach_profile_id,
                        "campaign_history_id": campaign_history_id,
                        "campaign_runtime_id": campaign_runtime_id,
                        "step": step,
                        "variables": variables,
                        "campaign_template_id": campaign_template_id,
                        "next_step_number": next_step_number,
                        "max_wait_seconds": max_wait_seconds,
                    },
                    countdown=SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS
                )
                return {"status": "locked", "rescheduled": True}
            raise
        except LinkedInCheckpointRequired as checkpoint_exc:
            logger.warning(
                f"{celery_task_id}: Manual checkpoint required for outreach {outreach_profile_id} "
                f"while checking {target_url}: {checkpoint_exc}"
            )
            with SyncSessionLocal() as db:
                update_scheduled_task_status(db, celery_task_id, "failed")
                user_id = get_user_id_by_outreach_profile(db, outreach_profile_id)
                if user_id:
                    create_action(
                        db,
                        user_id,
                        outreach_profile_id,
                        target_profile_id,
                        "connection_watcher",
                        "manual_checkpoint_required",
                        details={
                            "celery_task_id": celery_task_id,
                            "target_url": target_url,
                            "message": str(checkpoint_exc),
                        },
                    )
            return {
                "status": "manual_checkpoint_required",
                "requires_manual_action": True,
                "message": str(checkpoint_exc),
            }
        except Exception as e:
            logger.error(f"{celery_task_id}: Error in connection watcher: {e}")
            logger.info(
                f"🔄 {celery_task_id}: Rescheduling connection watcher for {target_url} "
                f"in {CONNECTION_WATCHER_CHECK_INTERVAL} seconds..."
            )
            # Reschedule despite error
            connection_watcher.apply_async(
                kwargs={
                    "target_profile_id": target_profile_id,
                    "target_url": target_url,
                    "outreach_profile_id": outreach_profile_id,
                    "campaign_history_id": campaign_history_id,
                    "campaign_runtime_id": campaign_runtime_id,
                    "step": step,
                    "variables": variables,
                    "campaign_template_id": campaign_template_id,
                    "next_step_number": next_step_number,
                    "max_wait_seconds": max_wait_seconds,
                },
                countdown=CONNECTION_WATCHER_CHECK_INTERVAL
            )
            
            return {"status": "error", "error": str(e), "rescheduled": True}

    except Exception as e:
        logger.error(f"❌ {celery_task_id}: Definitively failed in connection watcher: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(
    name="app.tasks.campaign_watchers.incoming_message_watcher", 
    bind=True
)
def incoming_message_watcher(
    self,
    target_profile_id: int,
    target_url: str,
    outreach_profile_id: int,
    # campaign_history_id: int,
    user_id: int,
    n8n_webhook_url: Optional[str] = None,
    max_wait_seconds: int = INCOMING_MESSAGE_WATCHER_MAX_WAIT_SECONDS
):
    """
    Monitor a chat for new incoming messages.
    Executes at the configured interval to check for new messages from target.
    When new incoming message detected:
    1. Pause all campaigns for this target
    2. Trigger n8n webhook for autonomous chat continuation
    
    Args:
        target_profile_id: Target profile database ID
        target_url: Target LinkedIn profile URL
        outreach_profile_id: Outreach profile ID
        campaign_history_id: Campaign history ID
        user_id: User ID
        n8n_webhook_url: Optional webhook URL for n8n integration
        max_wait_seconds: Maximum time to wait before timing out (default 10 days)
    """
    celery_task_id = self.request.id
    logger.info(f"{celery_task_id}: Incoming message watcher checking {target_url}...")
    
    try:
        # Check if we've exceeded max wait time
        with SyncSessionLocal() as db:
            scheduled_task = db.query(models.ScheduledCampaignTask).filter(
                models.ScheduledCampaignTask.celery_task_id == celery_task_id
            ).first()
            
            if scheduled_task:
                elapsed_time = (datetime.now(timezone.utc) - scheduled_task.created_at).total_seconds()
                if elapsed_time > max_wait_seconds:
                    logger.warning(
                        f"⚠️ {celery_task_id}: Message watcher timeout reached for {target_url} "
                        f"({elapsed_time}s > {max_wait_seconds}s)"
                    )
                    update_scheduled_task_status(db, celery_task_id, "timeout")
                    
                    # Create timeout action
                    create_action(
                        db, 
                        user_id, 
                        outreach_profile_id, 
                        target_profile_id,
                        "incoming_message_watcher", 
                        "timeout",
                        details={
                            "celery_task_id": celery_task_id,
                            "elapsed_seconds": elapsed_time,
                            "max_wait_seconds": max_wait_seconds
                        }
                    )
                    
                    return {"status": "timeout", "elapsed_seconds": elapsed_time}
        
        try:
            with profile_lock(outreach_profile_id):
                # Fetch all messages from chat
                service = LinkedInMicroserviceService(outreach_profile_id=outreach_profile_id)
                ok = service.start()
                if not ok:
                    logger.error(f"{celery_task_id}: Failed to login to Flask microservice")
                    service.close()
                    return {"status": "error", "reason": "login_failed"}
                
                logger.info(f"{celery_task_id}: Fetching messages from {target_url}...")
                all_messages = service.get_all_messages_from_chat(target_url)
                service.close()
            
            if all_messages:
                # Instrumentation: log timestamp value types for diagnostics
                ts_types = {}
                for m in all_messages:
                    t = type(m.get("timestamp")).__name__
                    ts_types[t] = ts_types.get(t, 0) + 1
                logger.info(f"{celery_task_id}: Timestamp type counts {ts_types}")
            
            if not all_messages or all_messages is False:
                logger.error(f"❌ {celery_task_id}: Could not fetch messages for {target_url}")
                logger.info(
                    f"🔄 {celery_task_id}: Rescheduling incoming message watcher for {target_url} "
                    f"in {INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL} seconds..."
                )
                
                # Reschedule for next check
                incoming_message_watcher.apply_async(
                    kwargs={
                        "target_profile_id": target_profile_id,
                        "target_url": target_url,
                        "outreach_profile_id": outreach_profile_id,
                        "user_id": user_id,
                        "n8n_webhook_url": n8n_webhook_url,
                        "max_wait_seconds": max_wait_seconds,
                    },
                    countdown=INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL
                )
                
                return {"status": "pending", "rescheduled": True, "reason": "fetch_failed"}
            
            # Compare with database to find new messages
            with SyncSessionLocal() as db:
                # Get existing chat history
                existing_messages = db.query(models.ChatHistory).filter(
                    and_(
                        models.ChatHistory.target_profile_id == target_profile_id,
                        models.ChatHistory.outreach_profile_id == outreach_profile_id
                    )
                ).all()
                
            # Create set of existing message timestamps + content for comparison
            existing_message_set = {
                (
                    _normalize_timestamp_for_compare(msg.message_sent_at),
                    msg.content,
                    msg.message_role,
                )
                for msg in existing_messages
            }
            
            # Check for new incoming messages
            new_incoming_messages = []
            
            for message in all_messages:
                timestamp_raw = message.get("timestamp")
                normalized_timestamp = _normalize_timestamp_for_compare(timestamp_raw)
                content = message.get("content")
                msg_type = message.get("type")
                
                if msg_type == "sent":
                    continue
                
                message_tuple = (normalized_timestamp, content, msg_type)
                
                # If message not in existing set, it's new
                if message_tuple not in existing_message_set and content:
                    new_incoming_messages.append(message)
            
            actual_incoming = new_incoming_messages

            last_message_type = all_messages[-1].get("type") if all_messages else None

            if last_message_type == "received":
                logger.info(
                    f"{celery_task_id}: Last message came from target; proceeding with watcher actions."
                )
            else:
                logger.info(
                    f"{celery_task_id}: Last message type is '{last_message_type}'; relying on DB comparison for new inbound detection."
                )
            
            if actual_incoming:
                logger.info(
                    f"{celery_task_id}: 🔔 Detected {len(actual_incoming)} new incoming message(s) "
                    f"from {target_url}"
                )
            
                with SyncSessionLocal() as db:
                    # Delete all chat history records for this target profile
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
                            f"{celery_task_id}: Stored {len(chat_records)} chat message(s) "
                            f"for {target_url} (skipped {skipped_messages} empty entries)"
                        )
                    else:
                        logger.warning(
                            f"{celery_task_id}: All fetched messages for {target_url} were empty; "
                            "skipping ChatHistory write."
                        )
                    
                    # Pause all active campaigns for this target
                    paused_campaigns = pause_all_campaigns_for_target(
                        db, target_profile_id, reason="Target responded"
                    )
                    logger.info(f"{celery_task_id}: Paused {len(paused_campaigns)} campaigns for {target_url}")
                    
                    # Cancel all scheduled tasks for affected campaigns
                    for campaign in paused_campaigns:
                        cancel_scheduled_tasks_for_campaign(db, campaign.id)
                    
                    # Trigger n8n webhook if provided
                    n8n_result = None
                    if n8n_webhook_url:
                        # Get target profile info from database for context
                        target_profile = db.query(models.TargetLinkedInProfile).filter(
                            models.TargetLinkedInProfile.id == target_profile_id
                        ).first()
                            
                        n8n_result = _trigger_n8n_webhook(
                            n8n_webhook_url,
                            target_url,
                            target_profile_id,
                            outreach_profile_id,
                            user_id,
                            actual_incoming,
                            all_messages,  # Pass complete chat history
                            target_profile  # Pass profile info for AI context
                        )
                
                    action_status = "success"
                    action_details = {
                        "celery_task_id": celery_task_id,
                        "message_count": len(actual_incoming),
                        "campaigns_paused": len(paused_campaigns),
                        "webhook_triggered": bool(n8n_webhook_url),
                    }
                    if n8n_result and n8n_result.get("status") != "success":
                        action_status = "partial_error"
                        action_details["n8n_result"] = n8n_result

                    # Create action log
                    create_action(
                        db, user_id, outreach_profile_id, target_profile_id,
                        "incoming_message_detected", action_status,
                        details=action_details,
                    )
                    
                    # Unschedule this watcher
                    update_scheduled_task_status(
                        db, celery_task_id, "executed",
                        executed_at=datetime.now(timezone.utc)
                    )
                    
                return {
                    "status": "message_detected",
                    "new_messages": len(actual_incoming),
                    "campaigns_paused": len(paused_campaigns),
                    "webhook_triggered": bool(n8n_webhook_url),
                    "webhook_status": n8n_result if n8n_result else None,
                }
            else:
                # No new messages - reschedule
                logger.info(
                    f"{celery_task_id}: No new incoming messages for {target_url}, "
                    f"rechecking in {INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL} seconds..."
                )
                
                incoming_message_watcher.apply_async(
                    kwargs={
                        "target_profile_id": target_profile_id,
                        "target_url": target_url,
                        "outreach_profile_id": outreach_profile_id,
                        "user_id": user_id,
                        "n8n_webhook_url": n8n_webhook_url,
                        "max_wait_seconds": max_wait_seconds,
                    },
                    countdown=INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL
                )
                
                return {"status": "no_new_messages", "rescheduled": True}
                    
        except Exception as e:
            logger.error(f"❌ {celery_task_id}: Error in incoming message watcher: {e}")
            logger.info(
                f"🔄 {celery_task_id}: Rescheduling incoming message watcher for {target_url} "
                f"in {INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL} seconds..."
            )
            
            # Reschedule despite error
            incoming_message_watcher.apply_async(
                kwargs={
                    "target_profile_id": target_profile_id,
                    "target_url": target_url,
                    "outreach_profile_id": outreach_profile_id,
                    "user_id": user_id,
                    "n8n_webhook_url": n8n_webhook_url,
                    "max_wait_seconds": max_wait_seconds,
                },
                countdown=INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL
            )
            
            return {"status": "error", "error": str(e), "rescheduled": True}
    
    except Exception as e:
        logger.error(f"❌ {celery_task_id}: Definitively failed in incoming message watcher: {e}")
        return {"status": "error", "error": str(e)}

def _trigger_next_campaign_step(
    db,
    campaign_history_id: int,
    next_step_number: int,
    target_profile_id: int,
    target_url: str,
    outreach_profile_id: int,
    user_id: int,
    campaign_template_id: int,
    campaign_runtime_id: uuid.UUID
):
    """
    Trigger the next scheduled campaign step immediately.
    Called when connection is accepted.
    
    This revokes the scheduled task and re-queues it to run now.
    """
    try:
        # Local import to avoid circular dependency during module import
        from app.tasks.campaign_scheduler import execute_campaign_step

        # Find the next scheduled step
        next_step_task = db.query(models.ScheduledCampaignTask).filter(
            and_(
                models.ScheduledCampaignTask.campaign_history_id == campaign_history_id,
                models.ScheduledCampaignTask.target_profile_id == target_profile_id,
                models.ScheduledCampaignTask.step_number == next_step_number,
                models.ScheduledCampaignTask.status == "scheduled"
            )
        ).first()
    
        if not next_step_task:
            logger.warning(
                f"No scheduled task found for campaign {campaign_history_id}, "
                f"step {next_step_number}"
            )
            return
        
        logger.info(
            f"Triggering next step {next_step_number} immediately for {target_url} "
            f"(was scheduled for {next_step_task.scheduled_at})"
        )
    
        # Option 1: Revoke the existing task and update its ETA to run now
        # This tells Celery to cancel the scheduled task and re-add it to the queue immediately
        celery_app.control.revoke(next_step_task.celery_task_id, terminate=False)
        logger.info(f"Revoked task because of the next step trigger: {next_step_task.celery_task_id}")

        # # Get the AsyncResult to access the task's stored arguments
        # from celery.result import AsyncResult
        # task_result = AsyncResult(next_step_task.celery_task_id, app=celery_app)
        
        # Retrieve the task details from the backend
        # Note: This requires the task to be stored with its arguments
        # We'll need to trigger it with the stored details from our DB
        task_details = next_step_task.details or {}
        
        # Re-queue the task to run immediately (no eta = run now)
        new_task = execute_campaign_step.apply_async(
            kwargs=task_details.get("kwargs", {}),
            countdown=0  # Run immediately
        )
        
        # Update the task record with new task ID and status
        next_step_task.celery_task_id = new_task.id
        next_step_task.status = "triggered_early"
        next_step_task.scheduled_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Re-queued step {next_step_number} with new task ID: {new_task.id}")

    except Exception as e:
        logger.error(f"❌ Definitively failed in _trigger_next_campaign_step: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(name="send_ai_response", bind=True)
def send_ai_response(
    self,
    target_profile_id: int,
    target_url: str,
    outreach_profile_id: int,
    user_id: int,
    ai_message: str
):
    """
    Send AI-generated response back to the target profile.
    
    This task is called by n8n after it generates an AI response
    to an incoming message from the target.
    
    Args:
        target_profile_id: ID of the target profile
        target_url: LinkedIn URL of the target
        outreach_profile_id: ID of the outreach profile to send from
        user_id: ID of the user
        ai_message: The AI-generated message to send
    """
    celery_task_id = self.request.id
    
    logger.info(
        f"🤖 {celery_task_id}: Sending AI response to {target_url} "
        f"from outreach profile {outreach_profile_id}"
    )

    try:
        with profile_lock(outreach_profile_id):
            service = LinkedInMicroserviceService(outreach_profile_id=outreach_profile_id)
            ok = service.start()
            if not ok:
                logger.error(f"{celery_task_id}: Failed to login to Flask microservice")
                service.close()
                return {"status": "error", "reason": "login_failed"}
            
            # Send the AI-generated message
            message_sent = service.send_message(target_url, ai_message)
            
            if not message_sent:
                logger.error(f"❌ {celery_task_id}: Failed to send AI message to {target_url}")
                service.close()
                return {"status": "failed", "reason": "message_send_failed"}
        
            logger.info(f"✅ {celery_task_id}: AI message sent successfully to {target_url}")
            
            # Fetch updated chat history and store in database
            all_messages = service.get_all_messages_from_chat(target_url)
            service.close()
        
        if all_messages and all_messages is not False:
            with SyncSessionLocal() as db:
                # Delete existing chat history for this conversation
                db.query(models.ChatHistory).filter(
                    models.ChatHistory.target_profile_id == target_profile_id,
                    models.ChatHistory.outreach_profile_id == outreach_profile_id
                ).delete()
                
                # Bulk insert all messages
                chat_records = [
                    models.ChatHistory(
                        outreach_profile_id=outreach_profile_id,
                        target_profile_id=target_profile_id,
                        message_role=msg.get("type"),
                        content=msg.get("content"),
                        message_sent_at=msg.get("timestamp")
                    )
                    for msg in all_messages
                ]
                db.bulk_save_objects(chat_records)
                db.commit()
                
                logger.info(f"💾 {celery_task_id}: Updated ChatHistory with {len(all_messages)} messages")
        else:
            logger.warning(f"⚠️ {celery_task_id}: Could not fetch updated chat history")
        
        return {
            "status": "success",
            "message_sent": True,
            "chat_history_updated": bool(all_messages)
        }
        
    except RuntimeError as lock_err:
        if "Timeout waiting for lock" in str(lock_err):
            logger.warning(
                f"{celery_task_id}: Outreach {outreach_profile_id} busy; retrying AI response in "
                f"{SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS}s."
            )
            raise self.retry(exc=lock_err, countdown=SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS)
        raise
    except Exception as e:
        logger.error(f"❌ {celery_task_id}: Error sending AI response: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {"status": "error", "error": str(e)}


def _trigger_n8n_webhook(
    webhook_url: str,
    target_url: str,
    target_profile_id: int,
    outreach_profile_id: int,
    user_id: int,
    new_messages: List[Dict],
    chat_history: List[Dict],  # Complete conversation history
    target_profile = None  # Optional: TargetLinkedInProfile model instance
):
    """
    Trigger n8n webhook to continue autonomous chat.
    
    Includes the Celery task endpoint that n8n should call back
    to send the AI-generated response.
    
    Also includes target profile information and complete chat history
    to provide rich context for AI response generation.
    
    Args:
        webhook_url: n8n webhook URL
        target_url: LinkedIn URL of the target
        target_profile_id: Database ID of target
        outreach_profile_id: Database ID of outreach profile
        user_id: Database ID of user (needed for send_ai_response callback)
        new_messages: List of new incoming messages
        chat_history: Complete conversation history (all messages)
        target_profile: Optional TargetLinkedInProfile model with profile info
    """
    def _log_event(detail: str, action: str, metadata: Optional[Dict[str, Any]] = None):
        try:
            with SyncSessionLocal() as db:
                event = models.LinkedInScrapeEvent(
                    outreach_profile_id=outreach_profile_id,
                    target_profile_id=target_profile_id,
                    event_type="n8n_webhook",
                    detail=detail,
                    action_taken=action,
                    metadata_json=metadata or {},
                )
                db.add(event)
                db.commit()
        except Exception as exc:  # pragma: no cover - logging only
            logger.warning(f"⚠️ Failed to persist n8n webhook event: {exc}")

    try:
        # Build target profile data with context for AI
        target_data = {
            "id": target_profile_id,
            "url": target_url
        }
        
        # Add profile info if available (for AI context)
        if target_profile:
            target_data.update({
                "name": target_profile.name,
                "lastname": target_profile.lastname,
                "title": target_profile.title,
                "location": target_profile.location,
                "about": target_profile.about,
                "connected": target_profile.connected,
                "connection_pending": target_profile.connection_pending
            })
        
        normalized_new_messages = []
        for msg in new_messages:
            raw_ts = msg.get("timestamp")
            normalized_ts = raw_ts.isoformat() if isinstance(raw_ts, datetime) else raw_ts
            logger.info(
                "Preparing n8n new_message payload entry",
                extra={
                    "target_url": target_url,
                    "content_preview": (msg.get("content") or "")[:120],
                    "raw_timestamp": raw_ts,
                    "normalized_timestamp": normalized_ts,
                    "timestamp_type": type(raw_ts).__name__,
                },
            )
            normalized_new_messages.append(
                {
                    "sender": msg.get("sender"),
                    "content": msg.get("content"),
                    "timestamp": normalized_ts,
                }
            )

        payload = {
            "event": "incoming_message_detected",
            "target_profile": target_data,
            "outreach_profile_id": outreach_profile_id,
            "user_id": user_id,  # Needed for n8n to call send_ai_response task
            "new_messages": normalized_new_messages,
            "chat_history": [
                {
                    "sender": msg.get("sender"),
                    "content": msg.get("content"),
                    "timestamp": (
                        msg.get("timestamp").isoformat()
                        if isinstance(msg.get("timestamp"), datetime)
                        else msg.get("timestamp")
                    ),
                    "type": msg.get("type")  # "sent" or "received"
                }
                for msg in chat_history
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            # Include task info for n8n to call back
            "callback": {
                "task_name": "send_ai_response",
                "description": "Call this Celery task to send AI response back to target"
            }
        }

        logger.info(
            "Triggering n8n webhook",
            extra={
                "target_url": target_url,
                "new_message_count": len(normalized_new_messages),
                "chat_history_count": len(chat_history),
            },
        )
        
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=10
        )
        
        metadata = {
            "target_url": target_url,
            "outreach_profile_id": outreach_profile_id,
            "user_id": user_id,
            "webhook_url": webhook_url,
            "new_message_count": len(normalized_new_messages),
        }

        if response.status_code == 200:
            logger.info(f"✅ Successfully triggered n8n webhook for {target_url}")
            _log_event(
                detail=f"success (HTTP {response.status_code})",
                action=response.text[:200],
                metadata=metadata,
            )
            return {"status": "success", "status_code": response.status_code}
        else:
            logger.warning(
                f"⚠️ n8n webhook returned status {response.status_code} for {target_url}"
            )
            _log_event(
                detail=f"failure (HTTP {response.status_code})",
                action=response.text[:200],
                metadata=metadata,
            )
            return {
                "status": "error",
                "status_code": response.status_code,
                "response_body": response.text[:1000],
            }
            
    except Exception as e:
        logger.error(f"❌ Failed to trigger n8n webhook: {e}")
        _log_event(
            detail="error during webhook trigger",
            action=str(e),
            metadata={
                "target_url": target_url,
                "webhook_url": webhook_url,
                "new_message_count": len(new_messages or []),
            },
        )
        return {"status": "exception", "error": str(e)}

