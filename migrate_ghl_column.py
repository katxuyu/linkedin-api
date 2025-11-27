import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.settings import SQLALCHEMY_DATABASE_URL_ASYNC

async def migrate_ghl_column():
    engine = create_async_engine(SQLALCHEMY_DATABASE_URL_ASYNC)
    
    async with engine.begin() as conn:
        # 1. Migrate outreach_profiles
        await conn.execute(text("""
            ALTER TABLE outreach_profiles 
            DROP COLUMN IF EXISTS gohighlevel_account_id CASCADE;
        """))
        await conn.execute(text("""
            ALTER TABLE outreach_profiles 
            ADD COLUMN IF NOT EXISTS gohighlevel_location_id VARCHAR;
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_outreach_profiles_gohighlevel_location_id 
            ON outreach_profiles(gohighlevel_location_id);
        """))
        
        # 2. Migrate target_contact_info
        await conn.execute(text("""
            ALTER TABLE target_contact_info 
            DROP COLUMN IF EXISTS gohighlevel_account_id CASCADE;
        """))
        await conn.execute(text("""
            ALTER TABLE target_contact_info 
            ADD COLUMN IF NOT EXISTS gohighlevel_location_id VARCHAR;
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_target_contact_info_gohighlevel_location_id 
            ON target_contact_info(gohighlevel_location_id);
        """))
        
        print("Successfully migrated outreach_profiles and target_contact_info to use gohighlevel_location_id")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate_ghl_column())
