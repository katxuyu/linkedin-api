from redis.asyncio import Redis as RedisAsync
from redis import Redis as RedisSync
from contextvars import ContextVar
from app.settings import REDIS_URL, logger

redis_client_async_var: ContextVar[RedisAsync | None] = ContextVar("redis_client_async_var", default=None)
redis_client_sync: RedisSync | None = None  # keep sync global for Celery locking

LOGIN_CODE_LOCK_TTL_SECONDS = 30 * 60


async def get_redis_async() -> RedisAsync:
    client = redis_client_async_var.get()
    if client is None:
        client = RedisAsync.from_url(REDIS_URL)
        try:
            await client.ping()
            logger.info("Lazy init: Redis (async) connected.")
        except Exception as e:
            logger.error(f"Redis async lazy connection failed: {e}")
            raise
        redis_client_async_var.set(client)
    return client


def get_redis_sync() -> RedisSync:
    global redis_client_sync
    if redis_client_sync is None:
        redis_client_sync = RedisSync.from_url(REDIS_URL)
        try:
            redis_client_sync.ping()
            logger.info("Lazy init: Redis (sync) connected.")
        except Exception as e:
            logger.error(f"Redis sync lazy connection failed: {e}")
            raise
    return redis_client_sync


def _login_code_lock_key(outreach_profile_id: int) -> str:
    return f"login_code_lock:{outreach_profile_id}"


def acquire_login_code_lock(outreach_profile_id: int, ttl_seconds: int | None = None) -> bool:
    client = get_redis_sync()
    ttl = ttl_seconds or LOGIN_CODE_LOCK_TTL_SECONDS
    return bool(client.set(_login_code_lock_key(outreach_profile_id), "1", nx=True, ex=ttl))


def refresh_login_code_lock(outreach_profile_id: int, ttl_seconds: int | None = None) -> None:
    client = get_redis_sync()
    ttl = ttl_seconds or LOGIN_CODE_LOCK_TTL_SECONDS
    client.expire(_login_code_lock_key(outreach_profile_id), ttl)


def release_login_code_lock(outreach_profile_id: int) -> None:
    client = get_redis_sync()
    client.delete(_login_code_lock_key(outreach_profile_id))


def get_login_code_lock_ttl(outreach_profile_id: int) -> int:
    client = get_redis_sync()
    return client.ttl(_login_code_lock_key(outreach_profile_id))