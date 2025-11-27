# app/utils/locks.py
from contextlib import contextmanager
from app.redis import get_redis_sync
from app.settings import (
    logger,
    SESSION_LOCK_TIMEOUT_SECONDS,
    SESSION_LOCK_TTL_SECONDS,
    SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
)


# @contextmanager
# def profile_lock(outreach_profile_id: int, timeout_seconds: int = 600, blocking_timeout: int = 30):
#     """
#     Distributed lock to ensure only ONE LinkedIn action runs at a time
#     for a given outreach_profile_id (works across multiple worker processes).
#     """
#     redis_client = get_redis_sync()
#     lock = redis_client.lock(
#         f"lock:outreach:{outreach_profile_id}",
#         timeout=timeout_seconds,
#         blocking_timeout=blocking_timeout,
#     )
#     acquired = lock.acquire(blocking=True)
#     try:
#         if not acquired:
#             raise RuntimeError("Outreach profile is busy with another action")
#         yield
#     finally:
#         try:
#             lock.release()
#         except Exception:
#             pass



@contextmanager
def profile_lock(
    outreach_profile_id: int,
    blocking_timeout_seconds: int = SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
    ttl_seconds: int = SESSION_LOCK_TTL_SECONDS,
):
    """
    Distributed lock so only ONE LinkedIn action runs at a time for a given outreach_profile_id.
    - blocking_timeout_seconds: how long to wait to acquire the lock
    - ttl_seconds: auto-expire lock if holder dies or runs too long
    """
    r = get_redis_sync()
    lock_key = f"lock:outreach:{outreach_profile_id}"
    lock = r.lock(lock_key, timeout=ttl_seconds)  # auto-expire if a worker dies

    acquired = False
    try:
        logger.info(
            f"[lock] Waiting for {lock_key} (blocking={blocking_timeout_seconds}s, ttl={ttl_seconds}s)"
        )
        acquired = lock.acquire(blocking=True, blocking_timeout=blocking_timeout_seconds)
        if not acquired:
            raise RuntimeError(f"Timeout waiting for lock {lock_key}")
        logger.info(f"[lock] Acquired {lock_key}")
        yield
    finally:
        if acquired:
            try:
                lock.release()
                logger.info(f"[lock] Released {lock_key}")
            except Exception:
                # If already auto-released (timeout/redis restart), ignore
                logger.info(f"[lock] Auto-released or missing {lock_key}, skipping explicit release")
                pass