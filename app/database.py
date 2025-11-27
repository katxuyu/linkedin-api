from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from contextlib import asynccontextmanager
from app.settings import SQLALCHEMY_DATABASE_URL_ASYNC, SQLALCHEMY_DATABASE_URL_SYNC

# Async engine configuration (needed for pgbouncer/asyncpg setups)
async_connect_args = {}
if SQLALCHEMY_DATABASE_URL_ASYNC and "asyncpg" in SQLALCHEMY_DATABASE_URL_ASYNC:
    # Disable prepared statement cache to support PgBouncer transaction mode.
    async_connect_args["statement_cache_size"] = 0

# Create async engine
async_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL_ASYNC,
    echo=True,  # Optional: SQL query logging
    future=True,
    connect_args=async_connect_args,
    poolclass=NullPool if SQLALCHEMY_DATABASE_URL_ASYNC else None,
)

AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

# Sync engine with pool settings to handle Supabase connection timeouts
sync_engine = create_engine(
    SQLALCHEMY_DATABASE_URL_SYNC,
    pool_pre_ping=True,  # Test connections before using them
    pool_recycle=300,    # Recycle connections after 5 minutes
    pool_size=5,         # Base pool size
    max_overflow=10,     # Allow up to 15 total connections
)
SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)

# Base class for models
Base = declarative_base()

# Dependency
async def get_db() -> AsyncSession:
    """
    Async database session generator for FastAPI.
    """
    async with AsyncSessionLocal() as session:
        yield session

@asynccontextmanager
async def get_db_context():
    async with AsyncSessionLocal() as session:
        yield session