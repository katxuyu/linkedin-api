from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime, timezone
from app import crud_async, database
from app.models import RegistrationKey, User, OutreachLinkedInProfile, CampaignHistory
from app.dependencies import get_current_user
from app.schemas import UserUpdateRequest, UserDetailResponse

router = APIRouter(prefix="/admin", tags=["admin"])

async def validate_registration_key(db: AsyncSession, key: str):
    result = await db.execute(select(RegistrationKey).filter(RegistrationKey.key == key))
    reg_key = result.scalars().first()
    if not reg_key or reg_key.used:
        raise HTTPException(status_code=403, detail="Invalid or used registration key")
    if reg_key.expires_at and reg_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="Expired registration key")
    return reg_key

@router.post("/registration-keys", response_model=dict)
async def generate_registration_key(
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a new registration key (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    reg_key = await crud_async.create_registration_key(db)
    if reg_key.expires_at:
        return {"registration_key": reg_key.key, "expires_at": reg_key.expires_at}
    return {"registration_key": reg_key.key}

@router.delete("/users/{user_id}", response_model=dict)
async def delete_user_account(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a specific user by ID (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    deleted = await crud_async.delete_user(db, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    delete_registration_key = await crud_async.delete_registration_key(db, user_id)
    if not delete_registration_key:
        raise HTTPException(status_code=404, detail="User's registration key not found")
    return {"status": "user_deleted", "user_id": user_id}
    
@router.get("/users", response_model=list)
async def list_all_users(
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all users (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    result = await db.execute(select(User))
    users = result.scalars().all()
    users_with_counts = []
    for user in users:
        profile_count_result = await db.execute(
            select(func.count(OutreachLinkedInProfile.id))
            .where(OutreachLinkedInProfile.user_id == user.id)
        )
        campaign_count_result = await db.execute(
            select(func.count(CampaignHistory.id))
            .where(CampaignHistory.user_id == user.id)
        )
        users_with_counts.append({
            "id": user.id,
            "email": user.email,
            "is_admin": user.is_admin,
            "created_at": user.created_at,
            "profile_count": profile_count_result.scalar() or 0,
            "campaign_count": campaign_count_result.scalar() or 0
        })
    return users_with_counts

@router.get("/users/{user_id}", response_model=UserDetailResponse)
async def get_user_by_id(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get a specific user by ID (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    user = await crud_async.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile_count_result = await db.execute(
        select(func.count(OutreachLinkedInProfile.id))
        .where(OutreachLinkedInProfile.user_id == user_id)
    )
    campaign_count_result = await db.execute(
        select(func.count(CampaignHistory.id))
        .where(CampaignHistory.user_id == user_id)
    )
    
    return UserDetailResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        created_at=user.created_at,
        profile_count=profile_count_result.scalar() or 0,
        campaign_count=campaign_count_result.scalar() or 0
    )

@router.put("/users/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: int,
    request: UserUpdateRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update a user (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    user = await crud_async.update_user(
        db,
        user_id,
        email=request.email,
        is_admin=request.is_admin
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profile_count_result = await db.execute(
        select(func.count(OutreachLinkedInProfile.id))
        .where(OutreachLinkedInProfile.user_id == user_id)
    )
    campaign_count_result = await db.execute(
        select(func.count(CampaignHistory.id))
        .where(CampaignHistory.user_id == user_id)
    )
    
    return UserDetailResponse(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        created_at=user.created_at,
        profile_count=profile_count_result.scalar() or 0,
        campaign_count=campaign_count_result.scalar() or 0
    )

@router.get("/users/{user_id}/profiles", response_model=list)
async def get_user_profiles(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all profiles for a specific user (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    user = await crud_async.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    profiles = await crud_async.get_outreach_profiles_by_user(db, user_id)
    return [
        {
            "id": profile.id,
            "linkedin_url": profile.linkedin_url,
            "linkedin_email": profile.linkedin_email,
            "account_name": profile.account_name,
            "gohighlevel_location_id": profile.gohighlevel_location_id,
            "added_at": profile.added_at
        }
        for profile in profiles
    ]

@router.get("/users/{user_id}/campaigns", response_model=list)
async def get_user_campaigns(
    user_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all campaigns for a specific user (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    user = await crud_async.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    campaigns = await crud_async.get_campaigns_by_user_id(db, user_id)
    return [
        {
            "campaign_history_id": campaign.id,
            "runtime_id": str(campaign.runtime_id),
            "started_at": campaign.started_at.isoformat(),
            "modified_at": campaign.modified_at.isoformat(),
            "status": campaign.status,
            "number_of_steps": campaign.number_of_steps,
            "finished_on_step_number": campaign.finished_on_step_number
        }
        for campaign in campaigns
    ]

@router.get("/stats", response_model=dict)
async def get_admin_stats(
    db: AsyncSession = Depends(database.get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get system statistics (admin only).
    Requires valid JWT token from admin user.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    
    # Count total users
    user_count_result = await db.execute(select(func.count(User.id)))
    total_users = user_count_result.scalar()
    
    # Count admin users
    admin_count_result = await db.execute(select(func.count(User.id)).where(User.is_admin == True))
    admin_users = admin_count_result.scalar()
    
    return {
        "total_users": total_users,
        "admin_users": admin_users,
        "regular_users": total_users - admin_users
    }