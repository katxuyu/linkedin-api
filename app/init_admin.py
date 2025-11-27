from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app import models, crud_async, settings
from app.settings import logger

async def create_default_admin(db: AsyncSession):
    # Check if any admin exists
    result = await db.execute(select(models.User).filter(models.User.is_admin == True))
    admin = result.scalars().first()
    if admin:
        return  # already exists

    # Otherwise, create default admin
    logger.info("No admin found. Creating default admin user...")
    await crud_async.create_user(
        db,
        email=settings.DEFAULT_ADMIN_EMAIL,
        password=settings.DEFAULT_ADMIN_PASSWORD
    )

    # Mark as admin
    result = await db.execute(select(models.User).filter(models.User.email == settings.DEFAULT_ADMIN_EMAIL))
    admin_user = result.scalars().first()
    admin_user.is_admin = True
    db.add(admin_user)
    await db.commit()
    logger.info(f"Default admin created: {settings.DEFAULT_ADMIN_EMAIL}")
