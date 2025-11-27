import re
import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Set, List, Optional
from app.database import get_db, SyncSessionLocal
from app.tasks.campaign_scheduler import run_campaign_with_scheduling
from app.crud_async import (
    get_outreach_profile_by_id, get_template_by_id, get_step_templates_by_id, 
    create_campaign_template_record, get_campaign_history_by_id, get_campaign_steps_history_by_history_id,
    get_latest_campaign_step_by_history_id, bulk_create_target_profiles, bulk_create_campaign_histories_with_steps,
    get_required_variables_for_template, create_campaign_lead_import, get_campaign_lead_import_by_import_id,
    list_campaign_histories_by_user, list_campaign_templates_by_user,
    get_campaign_detail_with_steps, get_scheduled_tasks_by_campaign
)
from app.crud_sync import (
    update_campaign_history_status,
    cancel_scheduled_tasks_for_campaign,
    get_campaign_history_by_id as get_campaign_history_by_id_sync,
)
from app.models import CampaignTemplate, CampaignStepTemplate, CampaignHistory, CampaignStepHistory
from app.schemas import (
    CampaignTemplateCreateRequest,
    CampaignTemplateCreateResponse,
    RunCampaignRequest,
    UserResponse,
    CampaignStatusResponse,
    PauseCampaignResponse,
    LeadImportRequest,
    LeadImportTriggerResponse,
    LeadImportStatusResponse,
    LeadImportPreviewRequest,
    LeadImportPreviewResponse,
    CampaignHistoryResponse,
    CampaignTemplateResponse,
    CampaignDetailResponse,
    CampaignStepHistoryResponse,
    ScheduledTaskResponse,
)
from app.dependencies import get_current_user
from app.settings import FERNET, logger
from app.celery_app import celery_app
from datetime import datetime, timezone
from app.tasks.lead_importer import run_lead_import
from app.services.lead_importer import LeadImportService

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

@router.get("/list", response_model=List[CampaignHistoryResponse])
async def list_campaigns(
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    logger.info(f"[Campaigns API] list_campaigns called - user_id: {user.id}, status: {status}, limit: {limit}, offset: {offset}")
    campaigns = await list_campaign_histories_by_user(db, user.id, status, limit, offset)
    logger.info(f"[Campaigns API] Found {len(campaigns)} campaigns for user {user.id}")
    
    response_campaigns = []
    for campaign in campaigns:
        campaign_dict = {
            "campaign_history_id": campaign.id,
            "runtime_id": campaign.runtime_id,
            "user_id": campaign.user_id,
            "outreach_profile_id": campaign.outreach_profile_id,
            "target_profile_id": campaign.target_profile_id,
            "campaign_template_id": campaign.campaign_template_id,
            "number_of_steps": campaign.number_of_steps,
            "status": campaign.status,
            "started_at": campaign.started_at,
            "modified_at": campaign.modified_at,
            "finished_on_step_number": campaign.finished_on_step_number,
            "target_profile_responded": campaign.target_profile_responded,
            "details": campaign.details,
        }
        
        if hasattr(campaign, 'target_profile') and campaign.target_profile:
            campaign_dict["target_profile_url"] = campaign.target_profile.profile_url
        
        if hasattr(campaign, 'outreach_profile') and campaign.outreach_profile:
            campaign_dict["outreach_profile_email"] = campaign.outreach_profile.linkedin_email
        
        if hasattr(campaign, 'campaign_template') and campaign.campaign_template:
            campaign_dict["template_name"] = campaign.campaign_template.name
        
        response_campaigns.append(CampaignHistoryResponse(**campaign_dict))
    
    return response_campaigns


@router.get("/templates/list", response_model=List[CampaignTemplateResponse])
async def list_templates(
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    templates = await list_campaign_templates_by_user(db, user.id)
    return templates


@router.get("/{campaign_history_id}", response_model=CampaignDetailResponse)
async def get_campaign_detail(
    campaign_history_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    logger.info(f"[Campaigns API] get_campaign_detail called - campaign_history_id: {campaign_history_id}, user_id: {user.id}")
    campaign = await get_campaign_detail_with_steps(db, campaign_history_id)
    
    if not campaign:
        logger.warning(f"[Campaigns API] Campaign {campaign_history_id} not found")
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    logger.info(f"[Campaigns API] Campaign {campaign_history_id} found - campaign.user_id: {campaign.user_id}, request.user_id: {user.id}")
    if campaign.user_id != user.id:
        logger.error(f"[Campaigns API] Authorization failed - campaign.user_id ({campaign.user_id}) != user.id ({user.id})")
        raise HTTPException(status_code=403, detail="Campaign not owned by user")
    
    campaign_dict = {
        "campaign_history_id": campaign.id,
        "runtime_id": campaign.runtime_id,
        "user_id": campaign.user_id,
        "outreach_profile_id": campaign.outreach_profile_id,
        "target_profile_id": campaign.target_profile_id,
        "campaign_template_id": campaign.campaign_template_id,
        "number_of_steps": campaign.number_of_steps,
        "status": campaign.status,
        "started_at": campaign.started_at,
        "modified_at": campaign.modified_at,
        "finished_on_step_number": campaign.finished_on_step_number,
        "target_profile_responded": campaign.target_profile_responded,
        "details": campaign.details,
        "step_histories": campaign.step_histories if hasattr(campaign, 'step_histories') else [],
    }
    
    if hasattr(campaign, 'target_profile') and campaign.target_profile:
        campaign_dict["target_profile_url"] = campaign.target_profile.profile_url
    
    if hasattr(campaign, 'outreach_profile') and campaign.outreach_profile:
        campaign_dict["outreach_profile_email"] = campaign.outreach_profile.linkedin_email
    
    if hasattr(campaign, 'campaign_template') and campaign.campaign_template:
        campaign_dict["template_name"] = campaign.campaign_template.name
    
    return CampaignDetailResponse(**campaign_dict)


@router.get("/{campaign_history_id}/scheduled-tasks", response_model=List[ScheduledTaskResponse])
async def get_scheduled_tasks(
    campaign_history_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    logger.info(f"[Campaigns API] get_scheduled_tasks called - campaign_history_id: {campaign_history_id}, user_id: {user.id}")
    campaign = await get_campaign_history_by_id(db, campaign_history_id)
    
    if not campaign:
        logger.warning(f"[Campaigns API] Campaign {campaign_history_id} not found")
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    logger.info(f"[Campaigns API] Campaign {campaign_history_id} found - campaign.user_id: {campaign.user_id}, request.user_id: {user.id}")
    if campaign.user_id != user.id:
        logger.error(f"[Campaigns API] Authorization failed - campaign.user_id ({campaign.user_id}) != user.id ({user.id})")
        raise HTTPException(status_code=403, detail="Campaign not owned by user")
    
    tasks = await get_scheduled_tasks_by_campaign(db, campaign_history_id)
    logger.info(f"[Campaigns API] Found {len(tasks)} scheduled tasks for campaign {campaign_history_id}")
    return tasks


@router.post("/templates/create", response_model=CampaignTemplateCreateResponse)
async def create_campaign_template(
    payload: CampaignTemplateCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    new_campaign_template_response = await create_campaign_template_record(
        db,
        user.id,
        payload.steps,
        payload.name if payload.name else None,
        payload.description if payload.description else None
    )

    new_campaign_template = new_campaign_template_response.get("template", None)
    required_variables = new_campaign_template_response.get("required_variables", None)

    return CampaignTemplateCreateResponse(
        id=new_campaign_template.id,
        name=new_campaign_template.name if new_campaign_template.name else None,
        variables=required_variables if required_variables else None
    )

@router.get("/templates/{template_id}/steps")
async def get_template_steps(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    """
    Get the steps of a campaign template.
    """
    template = await get_template_by_id(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    if template.user_id != user.id:
        raise HTTPException(status_code=403, detail="Template not owned by user")
    
    steps = await get_step_templates_by_id(db, template_id)
    
    return {
        "template_id": template_id,
        "steps": [
            {
                "step_number": step.step_number,
                "action": step.action,
                "delay_days": step.delay_days,
                "message_template": step.message_template,
                "variables": step.variables
            }
            for step in steps
        ]
    }


@router.post("/verify-targets-connection")
async def verify_targets_connection(
    outreach_profile_id: int,
    target_urls: List[str],
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    """
    Verify if target profiles are connected to the outreach profile.
    Used to validate send-message-only campaigns.
    """
    from app.services.service_manager import LinkedInMicroserviceService
    import asyncio
    
    outreach_profile = await get_outreach_profile_by_id(db, outreach_profile_id)
    if not outreach_profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if outreach_profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile not owned by user")
    
    def _check_connections():
        results = []
        service = LinkedInMicroserviceService(outreach_profile_id)
        
        try:
            if not service.start():
                return {"error": "Failed to start LinkedIn service", "results": []}
            
            for target_url in target_urls:
                try:
                    profile_info = service.fetch_profile_info(target_url)
                    is_connected = profile_info.get("connected", False) if profile_info else False
                    is_pending = profile_info.get("connection_pending", False) if profile_info else False
                    results.append({
                        "url": target_url,
                        "connected": is_connected,
                        "pending": is_pending,
                        "name": profile_info.get("name", "") if profile_info else ""
                    })
                except Exception as e:
                    logger.error(f"Error checking connection for {target_url}: {e}")
                    results.append({
                        "url": target_url,
                        "connected": False,
                        "pending": False,
                        "error": str(e)
                    })
            
            service.close()
            return {"results": results}
            
        except Exception as e:
            logger.error(f"Error in connection check: {e}")
            try:
                service.close()
            except:
                pass
            return {"error": str(e), "results": results}
    
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _check_connections)
    
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    
    return {
        "status": "success",
        "results": result["results"],
        "all_connected": all(r.get("connected", False) for r in result["results"])
    }


@router.post("/run", response_model=dict)
async def run_campaign(
    payload: RunCampaignRequest,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):  
    # Verify that outreach profile exists
    outreach_profile = await get_outreach_profile_by_id(db, payload.outreach_profile_id)
    if not outreach_profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if outreach_profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile owned")

    # Verify that the campaign template exists
    campaign_template = await get_template_by_id(db, payload.campaign_template_id)
    if not campaign_template:
        raise HTTPException(status_code=404, detail="Campaign template not found")

    # Verify that step templates exist
    step_templates = await get_step_templates_by_id(db, payload.campaign_template_id)
    if not step_templates:
        raise HTTPException(status_code=400, detail="No steps found for this campaign template")
    
    # Validate that all target profiles have the required variables
    try:
        required_vars = await get_required_variables_for_template(db, payload.campaign_template_id)
        for target_profile in payload.target_profiles:
            if target_profile.variables:
                missing_vars = [var for var in required_vars if var not in target_profile.variables]
                if missing_vars:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Target profile {target_profile.url} is missing required variables: {missing_vars}"
                    )
            else:
                if required_vars:  # Only check if there are required variables
                    raise HTTPException(
                        status_code=400,
                        detail=f"Target profile {target_profile.url} is missing all required variables: {required_vars}"
                    )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"Error validating variables: {str(e)}")
    
    # Initialize target profiles in the DB
    all_target_urls = [profile.url for profile in payload.target_profiles]
    created_target_profiles = await bulk_create_target_profiles(db, payload.outreach_profile_id, all_target_urls)
    target_profile_ids = [profile.id for profile in created_target_profiles]
    
    # Check if target profiles were created successfully
    if not target_profile_ids:
        raise HTTPException(status_code=500, detail="Failed to create target profiles")

    campaign_histories, campaign_step_histories, actions = await bulk_create_campaign_histories_with_steps(
        db, 
        user.id, 
        payload.outreach_profile_id,
        payload.campaign_template_id,
        target_profile_ids,
        step_templates
    )

    # Convert objects to JSON-serializable format for Celery
    payload_dict = payload.model_dump()
    
    # Build a mapping of target URL -> campaign history info for Celery
    # This ensures Celery uses the already-created campaign histories
    campaign_history_map = {}
    for ch in campaign_histories:
        # Get the target URL from the target_profile
        target_profile = next(
            (tp for tp in created_target_profiles if tp.id == ch.target_profile_id), 
            None
        )
        if target_profile:
            campaign_history_map[target_profile.profile_url] = {
                "campaign_history_id": ch.id,
                "campaign_runtime_id": str(ch.runtime_id),
                "target_profile_id": ch.target_profile_id,
            }
    
    step_templates_list = [
        {
            "id": step.id,
            "campaign_template_id": step.campaign_template_id,
            "step_number": step.step_number,
            "action": step.action,
            "additional_note_template": step.additional_note_template,
            "delay_timestamp": step.delay_timestamp.total_seconds(),  # Convert to seconds
            "message_template": step.message_template,
            "variables": step.variables
        }
        for step in step_templates
    ]

    run_campaign_with_scheduling.delay(
        payload_dict,
        step_templates_list,
        campaign_history_map  # Pass the existing campaign history IDs
    )
    
    # Check if campaign histories were created successfully
    if not campaign_histories:
        raise HTTPException(status_code=500, detail="Failed to create campaign histories")
    
    return {
        "status": "success",
        "message": f"Campaign with ID {campaign_histories[0].runtime_id} started for {len(target_profile_ids)} target profiles."
    }
    

@router.post("/import-search", response_model=LeadImportTriggerResponse)
async def import_leads_from_search(
    payload: LeadImportRequest,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    outreach_profile = await get_outreach_profile_by_id(db, payload.outreach_profile_id)
    if not outreach_profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if outreach_profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile owned")

    campaign_template = await get_template_by_id(db, payload.campaign_template_id)
    if not campaign_template:
        raise HTTPException(status_code=404, detail="Campaign template not found")
    if campaign_template.user_id != user.id:
        raise HTTPException(status_code=403, detail="Campaign template owned")

    step_templates = await get_step_templates_by_id(db, payload.campaign_template_id)
    if not step_templates:
        raise HTTPException(status_code=400, detail="Campaign template has no steps defined")

    lead_import = await create_campaign_lead_import(
        db,
        user_id=user.id,
        outreach_profile_id=payload.outreach_profile_id,
        campaign_template_id=payload.campaign_template_id,
        search_url=str(payload.search_url),
        requested_lead_count=payload.max_results,
        search_filters=payload.search_filters,
    )

    run_lead_import.delay(str(lead_import.import_id))

    return LeadImportTriggerResponse(
        import_id=lead_import.import_id,
        status=lead_import.status,
        requested_lead_count=lead_import.requested_lead_count,
    )


@router.post("/import-search/preview", response_model=LeadImportPreviewResponse)
async def preview_leads_from_search(
    payload: LeadImportPreviewRequest,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    outreach_profile = await get_outreach_profile_by_id(db, payload.outreach_profile_id)
    if not outreach_profile:
        raise HTTPException(status_code=404, detail="Outreach profile not found")
    if outreach_profile.user_id != user.id:
        raise HTTPException(status_code=403, detail="Outreach profile owned")

    try:
        targets = LeadImportService.preview_leads(
            outreach_profile.id,
            str(payload.search_url),
            payload.max_results,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pylint: disable=broad-except
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return LeadImportPreviewResponse(
        total=len(targets),
        targets=targets,
    )


@router.get("/import-search/{import_id}", response_model=LeadImportStatusResponse)
async def get_lead_import_status(
    import_id: str,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user),
):
    try:
        import_uuid = uuid.UUID(import_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid import_id format")

    lead_import = await get_campaign_lead_import_by_import_id(db, import_uuid)
    if not lead_import:
        raise HTTPException(status_code=404, detail="Lead import not found")
    if lead_import.user_id != user.id:
        raise HTTPException(status_code=403, detail="Lead import owned")

    return LeadImportStatusResponse(
        import_id=lead_import.import_id,
        status=lead_import.status,
        search_url=lead_import.search_url,
        requested_lead_count=lead_import.requested_lead_count,
        total_extracted=lead_import.total_extracted,
        total_imported=lead_import.total_imported,
        error=lead_import.error,
        created_at=lead_import.created_at,
        started_at=lead_import.started_at,
        finished_at=lead_import.finished_at,
    )


@router.get("/status/{campaign_history_id}", response_model=CampaignStatusResponse)
async def get_campaign_status(
    campaign_history_id: int, 
    db: AsyncSession = Depends(get_db), 
    user: UserResponse = Depends(get_current_user)
):
    history = await get_campaign_history_by_id(db, campaign_history_id)
    if not history:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.id != history.user_id:
        raise HTTPException(status_code=403, detail="Campaign not owned")
    
    # steps = await get_campaign_steps_history_by_history_id(db, campaign_history_id)
    latest_recorded_step = await get_latest_campaign_step_by_history_id(db, campaign_history_id)
    return CampaignStatusResponse(
        started_at=history.started_at,
        modified_at=history.modified_at,
        status=history.status,
        latest_step=latest_recorded_step,
        total_steps=history.number_of_steps,
        details=history.details
    )


def _cancel_message_watchers_for_campaign(db, campaign_history_id: int, target_profile_id: int, outreach_profile_id: int) -> int:
    from app import models
    
    active_watchers = db.query(models.ScheduledCampaignTask).filter(
        models.ScheduledCampaignTask.target_profile_id == target_profile_id,
        models.ScheduledCampaignTask.task_name == "incoming_message_watcher",
        models.ScheduledCampaignTask.status.in_(["scheduled", "executing"])
    ).all()
    
    filtered_watchers = [
        w for w in active_watchers
        if w.details and w.details.get("outreach_profile_id") == outreach_profile_id
    ]
    
    if not filtered_watchers:
        logger.info(
            f"No active message watchers found for campaign {campaign_history_id}, "
            f"target {target_profile_id}, and outreach profile {outreach_profile_id}"
        )
        return 0
    
    cancelled_count = 0
    for watcher in filtered_watchers:
        try:
            celery_app.control.revoke(watcher.celery_task_id, terminate=True)
            watcher.status = "cancelled"
            watcher.details = watcher.details or {}
            watcher.details["cancelled_reason"] = "Campaign paused by user"
            watcher.details["cancelled_at"] = datetime.now(timezone.utc).isoformat()
            cancelled_count += 1
            logger.info(
                f"Cancelled watcher task {watcher.celery_task_id} for campaign {campaign_history_id}"
            )
        except Exception as e:
            logger.error(f"Failed to cancel watcher {watcher.celery_task_id}: {e}")
    
    db.commit()
    logger.info(f"Cancelled {cancelled_count} message watcher(s) for campaign {campaign_history_id}")
    return cancelled_count


@router.post("/pause/{campaign_history_id}", response_model=PauseCampaignResponse)
async def pause_campaign(
    campaign_history_id: int,
    db: AsyncSession = Depends(get_db),
    user: UserResponse = Depends(get_current_user)
):
    history = await get_campaign_history_by_id(db, campaign_history_id)
    if not history:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if user.id != history.user_id:
        raise HTTPException(status_code=403, detail="Campaign not owned")
    
    if history.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause campaign with status '{history.status}'. Only active campaigns can be paused."
        )
    
    with SyncSessionLocal() as sync_db:
        cancelled_tasks_count = cancel_scheduled_tasks_for_campaign(sync_db, campaign_history_id)
        
        cancelled_watchers_count = _cancel_message_watchers_for_campaign(
            sync_db,
            campaign_history_id,
            history.target_profile_id,
            history.outreach_profile_id
        )
        
        update_campaign_history_status(
            sync_db,
            campaign_history_id,
            "paused",
            details={
                **(history.details or {}),
                "paused_at": datetime.now(timezone.utc).isoformat(),
                "paused_by": user.id,
                "cancelled_tasks_count": cancelled_tasks_count,
                "cancelled_watchers_count": cancelled_watchers_count
            }
        )
    
    return PauseCampaignResponse(
        status="success",
        message=f"Campaign {campaign_history_id} has been paused successfully",
        campaign_history_id=campaign_history_id,
        cancelled_tasks_count=cancelled_tasks_count,
        cancelled_watchers_count=cancelled_watchers_count
    )
