import asyncio
from app.database import get_db_context
from app import crud_async
from app.settings import PWD_CONTEXT

async def create_admin_user():
    email = "enniocuteri@fluence-group.com"
    password = "Linkedin@2025"
    
    async with get_db_context() as db:
        user = await crud_async.get_user_by_email(db, email)
        if user:
            user.is_admin = True
            user.password = PWD_CONTEXT.hash(password)
            db.add(user)
            await db.commit()
            print(f"Updated existing user: {email}, is_admin: {user.is_admin}")
        else:
            user = await crud_async.create_user(db, email, password)
            user.is_admin = True
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"Created new admin user: {email}, is_admin: {user.is_admin}")

if __name__ == "__main__":
    asyncio.run(create_admin_user())

