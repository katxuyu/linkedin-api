import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from app import redis
from app.api import auth, profiles, admin, campaigns, gohighlevel, verification
from app.init_admin import create_default_admin
from app.settings import logger, REDIS_URL


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    
    # Initialize database tables
    from app.database import get_db_context
    # Old way (pre-Alembic): auto-create tables on startup
    # from app.database import Base, async_engine
    # async with async_engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.create_all)
    # Create default admin user
    async with get_db_context() as db:
        await create_default_admin(db)
    
    #global redis_client
    redis.redis_client_async = Redis.from_url(REDIS_URL)
    try:
        await redis.redis_client_async.ping()
        logger.info("Connected to Redis successfully.")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        raise

    yield  # Hand control back to FastAPI (app runs here)

    # Shutdown
    if redis.redis_client_async:
        await redis.redis_client_async.close()
        logger.info("Redis connection closed.")


app = FastAPI(title="LinkedIn Automation API", lifespan=lifespan)

# CORS configuration (can be overridden via env for debug)
default_cors_origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://localhost:8088",
    "http://127.0.0.1:8088",
]

cors_override = os.getenv("CORS_ALLOWED_ORIGINS")
allow_all_cors = os.getenv("CORS_ALLOW_ALL", "false").lower() in ("1", "true", "yes")

cors_origins = (
    [origin.strip() for origin in cors_override.split(",") if origin.strip()]
    if cors_override
    else default_cors_origins
)

app.add_middleware(
    CORSMiddleware,
    # allow all origins in dev by setting CORS_ALLOW_ALL=true, otherwise use list
    allow_origins=[] if allow_all_cors else cors_origins,
    allow_origin_regex=".*" if allow_all_cors else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(profiles.router)
app.include_router(admin.router)
app.include_router(campaigns.router)
app.include_router(gohighlevel.router)
app.include_router(verification.router)


@app.get("/")
async def root():
    return {"message": "LinkedIn Automation API"}


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker healthcheck and load balancers."""
    try:
        # Check Redis connectivity
        if redis.redis_client_async:
            await redis.redis_client_async.ping()
        return {"status": "healthy", "service": "linkedin-api"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}
