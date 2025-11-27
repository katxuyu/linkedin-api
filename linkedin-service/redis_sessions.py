"""
Redis-based session storage for linkedin-service.

Architecture:
- Redis stores session METADATA (status, expires_at, created_at, profile_info)
- Memory stores the actual browser SERVICE instance (cannot be serialized)
- Both are kept in sync - Redis is the source of truth for metadata
- Single worker is still required because Playwright browsers can't be shared

Benefits:
- Sessions persist across container restarts
- Clear session state visible to other services
- Foundation for horizontal scaling (multiple instances, each with own browser)
"""

import json
import os
import time
import threading
from collections import defaultdict
from typing import Optional, Dict, Any
from logger import logger

# Try to import redis, fall back to in-memory if not available
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, falling back to in-memory only")

SESSION_TTL_SECONDS = 1800  # 30 minutes
REDIS_KEY_PREFIX = "linkedin_session:"

# Redis connection (lazy initialized)
_redis_client = None
_redis_lock = threading.Lock()


def get_redis_client():
    """Get or create Redis client with lazy initialization."""
    global _redis_client
    
    if not REDIS_AVAILABLE:
        return None
    
    if _redis_client is not None:
        try:
            _redis_client.ping()
            return _redis_client
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning("Redis connection lost, reconnecting...")
            _redis_client = None
    
    with _redis_lock:
        if _redis_client is None:
            redis_url = os.environ.get('REDIS_URL')
            redis_host = os.environ.get('REDIS_HOST', 'redis')
            redis_port = int(os.environ.get('REDIS_PORT', 6379))
            redis_password = os.environ.get('REDIS_PASSWORD')
            redis_db = int(os.environ.get('REDIS_DB', 1))  # Use DB 1 for linkedin-service
            
            try:
                if redis_url:
                    _redis_client = redis.from_url(redis_url, decode_responses=True)
                else:
                    _redis_client = redis.Redis(
                        host=redis_host,
                        port=redis_port,
                        password=redis_password,
                        db=redis_db,
                        decode_responses=True,
                        socket_connect_timeout=5,
                        socket_timeout=5,
                        retry_on_timeout=True,
                    )
                _redis_client.ping()
                logger.info(f"Redis connected: {redis_host}:{redis_port} db={redis_db}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                _redis_client = None
    
    return _redis_client


class SessionMetadata:
    """Session metadata that can be stored in both memory and Redis."""
    
    def __init__(self, service=None, status="active", created_at=None, expires_at=None, 
                 profile_id=None, email=None, extra_data=None):
        self.service = service  # Browser instance - NOT serializable
        self.status = status
        self.created_at = created_at or time.time()
        self.expires_at = expires_at or (self.created_at + SESSION_TTL_SECONDS)
        self.profile_id = profile_id
        self.email = email
        self.extra_data = extra_data or {}
    
    def is_expired(self):
        return time.time() > self.expires_at
    
    def mark_pending_2fa(self):
        self.status = "pending_2fa"
        self.expires_at = time.time() + SESSION_TTL_SECONDS
    
    def mark_active(self):
        self.status = "active"
    
    def to_redis_dict(self) -> Dict[str, Any]:
        """Convert to dict for Redis storage (excludes non-serializable service)."""
        # Redis hset doesn't accept None values - use empty string or skip
        result = {
            "status": self.status or "unknown",
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "extra_data": json.dumps(self.extra_data) if self.extra_data else "{}",
        }
        # Only include optional fields if they have values
        if self.profile_id is not None:
            result["profile_id"] = str(self.profile_id)
        if self.email is not None:
            result["email"] = self.email
        return result
    
    @classmethod
    def from_redis_dict(cls, data: Dict[str, Any], service=None) -> "SessionMetadata":
        """Create from Redis data, optionally attaching a service instance."""
        extra_data = data.get("extra_data", "{}")
        if isinstance(extra_data, str):
            try:
                extra_data = json.loads(extra_data)
            except:
                extra_data = {}
        
        return cls(
            service=service,
            status=data.get("status", "unknown"),
            created_at=float(data.get("created_at", time.time())),
            expires_at=float(data.get("expires_at", time.time() + SESSION_TTL_SECONDS)),
            profile_id=data.get("profile_id"),
            email=data.get("email"),
            extra_data=extra_data,
        )


# In-memory storage for browser instances (cannot be stored in Redis)
_memory_sessions: Dict[str, SessionMetadata] = {}
_session_locks = defaultdict(threading.RLock)


def _redis_key(session_key: str) -> str:
    """Generate Redis key for a session."""
    return f"{REDIS_KEY_PREFIX}{session_key}"


def _sync_to_redis(session_key: str, metadata: SessionMetadata):
    """Sync session metadata to Redis."""
    r = get_redis_client()
    if r is None:
        return
    
    try:
        key = _redis_key(session_key)
        ttl = max(1, int(metadata.expires_at - time.time()))
        r.hset(key, mapping=metadata.to_redis_dict())
        r.expire(key, ttl)
        logger.debug(f"[Redis] Synced session {session_key} (ttl={ttl}s)")
    except Exception as e:
        logger.error(f"[Redis] Failed to sync session {session_key}: {e}")


def _delete_from_redis(session_key: str):
    """Delete session from Redis."""
    r = get_redis_client()
    if r is None:
        return
    
    try:
        r.delete(_redis_key(session_key))
        logger.debug(f"[Redis] Deleted session {session_key}")
    except Exception as e:
        logger.error(f"[Redis] Failed to delete session {session_key}: {e}")


def _load_from_redis(session_key: str) -> Optional[Dict[str, Any]]:
    """Load session metadata from Redis."""
    r = get_redis_client()
    if r is None:
        return None
    
    try:
        data = r.hgetall(_redis_key(session_key))
        if data:
            logger.debug(f"[Redis] Loaded session {session_key}")
            return data
    except Exception as e:
        logger.error(f"[Redis] Failed to load session {session_key}: {e}")
    
    return None


def ensure_session(session_key: str) -> Optional[SessionMetadata]:
    """
    Ensure a session exists. Creates placeholder if needed.
    Checks both memory and Redis for existing sessions.
    """
    lock = _session_locks[session_key]
    with lock:
        # Check memory first
        metadata = _memory_sessions.get(session_key)
        if metadata:
            if metadata.is_expired():
                logger.warning(f"[ensure_session] Session {session_key} expired, removing")
                _cleanup_session(session_key, metadata)
                return None
            logger.info(f"[ensure_session] Reusing existing session({session_key}) status={metadata.status}")
            return metadata
        
        # Check Redis for persisted metadata
        redis_data = _load_from_redis(session_key)
        if redis_data:
            expires_at = float(redis_data.get("expires_at", 0))
            if time.time() < expires_at:
                # Session exists in Redis but not in memory (service restart)
                # Create metadata without service - caller will need to re-authenticate
                logger.info(f"[ensure_session] Found session {session_key} in Redis, but no browser instance")
                # Don't restore - the browser is gone, need fresh start
                _delete_from_redis(session_key)
        
        # Create new placeholder session
        logger.info(f"[ensure_session] Creating new session ({session_key})")
        metadata = SessionMetadata(service=None, status="placeholder")
        _memory_sessions[session_key] = metadata
        _sync_to_redis(session_key, metadata)
        return metadata


def store_service_in_session(session_key: str, service, profile_id=None, email=None):
    """Store the browser service instance in the session."""
    lock = _session_locks[session_key]
    with lock:
        metadata = _memory_sessions.get(session_key)
        if metadata:
            metadata.service = service
            metadata.profile_id = profile_id
            metadata.email = email
            metadata.mark_active()
            logger.info(f"[store_service_in_session] Stored service for {session_key}")
        else:
            metadata = SessionMetadata(
                service=service, 
                status="active",
                profile_id=profile_id,
                email=email,
            )
            _memory_sessions[session_key] = metadata
            logger.info(f"[store_service_in_session] Created new metadata for {session_key}")
        
        _sync_to_redis(session_key, metadata)


def mark_session_pending_2fa(session_key: str) -> bool:
    """Mark session as waiting for 2FA code."""
    lock = _session_locks[session_key]
    with lock:
        metadata = _memory_sessions.get(session_key)
        if metadata:
            metadata.mark_pending_2fa()
            _sync_to_redis(session_key, metadata)
            logger.info(f"[mark_session_pending_2fa] Marked {session_key} as pending_2fa")
            return True
        return False


def get_session_service(session_key: str):
    """Get the browser service instance for a session."""
    lock = _session_locks[session_key]
    with lock:
        metadata = _memory_sessions.get(session_key)
        if metadata and not metadata.is_expired():
            return metadata.service
        return None


def get_session_status(session_key: str) -> Optional[str]:
    """Get session status (checks both memory and Redis)."""
    lock = _session_locks[session_key]
    with lock:
        # Check memory first (has the actual browser)
        metadata = _memory_sessions.get(session_key)
        if metadata and not metadata.is_expired():
            return metadata.status
        
        # Check Redis as fallback (might have persisted status)
        redis_data = _load_from_redis(session_key)
        if redis_data:
            expires_at = float(redis_data.get("expires_at", 0))
            if time.time() < expires_at:
                return redis_data.get("status")
        
        return None


def get_session_metadata(session_key: str) -> Optional[SessionMetadata]:
    """Get full session metadata."""
    lock = _session_locks[session_key]
    with lock:
        metadata = _memory_sessions.get(session_key)
        if metadata and not metadata.is_expired():
            return metadata
        return None


def _cleanup_session(session_key: str, metadata: SessionMetadata):
    """Internal cleanup - close browser and remove from storage."""
    if metadata and metadata.service:
        try:
            metadata.service.close()
        except Exception as e:
            logger.error(f"[_cleanup_session] Error closing service: {e}")
    
    _memory_sessions.pop(session_key, None)
    _delete_from_redis(session_key)


def close_session(session_key: str) -> bool:
    """Close a session - cleanup browser and remove from storage."""
    lock = _session_locks[session_key]
    with lock:
        metadata = _memory_sessions.pop(session_key, None)
        if metadata:
            logger.info(f"[close_session] Closing session {session_key} with status {metadata.status}")
            if metadata.service:
                try:
                    metadata.service.close()
                    logger.info(f"[close_session] Service closed for session {session_key}")
                except Exception as e:
                    logger.error(f"[close_session] Error closing service for {session_key}: {e}")
            _delete_from_redis(session_key)
            return True
        
        # Also clean Redis even if not in memory
        _delete_from_redis(session_key)
        logger.warning(f"[close_session] Session {session_key} not found in active sessions")
        return False


def get_number_of_active_sessions() -> int:
    """Get count of active sessions in memory."""
    return len(_memory_sessions)


def get_all_sessions_info() -> Dict[str, Dict[str, Any]]:
    """Get info about all active sessions (for debugging/monitoring)."""
    result = {}
    for key, metadata in _memory_sessions.items():
        if not metadata.is_expired():
            result[key] = {
                "status": metadata.status,
                "has_service": metadata.service is not None,
                "expires_at": metadata.expires_at,
                "ttl_seconds": max(0, int(metadata.expires_at - time.time())),
                "profile_id": metadata.profile_id,
                "email": metadata.email,
            }
    return result


def cleanup_expired_sessions():
    """Remove all expired sessions from memory and Redis."""
    expired_keys = []
    for key, metadata in list(_memory_sessions.items()):
        if metadata.is_expired():
            expired_keys.append(key)
    
    for key in expired_keys:
        lock = _session_locks[key]
        with lock:
            metadata = _memory_sessions.pop(key, None)
            if metadata:
                _cleanup_session(key, metadata)
                logger.info(f"[cleanup_expired_sessions] Removed expired session {key}")
    
    return len(expired_keys)


# Initialize Redis connection on module load
def init_redis():
    """Initialize Redis connection (call on startup)."""
    client = get_redis_client()
    if client:
        logger.info("Redis session storage initialized")
    else:
        logger.warning("Redis not available - using in-memory only (sessions won't persist across restarts)")

