import asyncio
from app.database import get_db_context
from app import crud_async
from app.settings import PWD_CONTEXT

async def update_admin():
    async with get_db_context() as db:
        user = await crud_async.get_user_by_email(db, "enniocuteri@fluence-group.com")
        if user:
            user.password = PWD_CONTEXT.hash("Linkedin@2025")
            user.is_admin = True
            db.add(user)
            await db.commit()
            print(f"Updated user: {user.email}, is_admin: {user.is_admin}")
        else:
            print("User not found")

if __name__ == "__main__":
    asyncio.run(update_admin())





