import threading
import time
from collections import defaultdict
from typing import Optional, Dict, Any
from logger import logger

SESSION_TTL_SECONDS = 1800

class SessionMetadata:
    def __init__(self, service, status="active", created_at=None, expires_at=None):
        self.service = service
        self.status = status
        self.created_at = created_at or time.time()
        self.expires_at = expires_at or (self.created_at + SESSION_TTL_SECONDS)
    
    def is_expired(self):
        return time.time() > self.expires_at
    
    def mark_pending_2fa(self):
        self.status = "pending_2fa"
        self.expires_at = time.time() + SESSION_TTL_SECONDS
    
    def mark_active(self):
        self.status = "active"

active_sessions = {}
session_locks = defaultdict(threading.RLock)

def ensure_session(session_key):
    lock = session_locks[session_key]
    with lock:
        metadata = active_sessions.get(session_key)
        if metadata:
            if metadata.is_expired():
                logger.warning(f"[ensure_session] Session {session_key} expired, removing")
                _cleanup_session(session_key, metadata)
                return None
            logger.info(f"[ensure_session] Reusing existing session({session_key}) status={metadata.status}")
            return metadata
        logger.info(f"[ensure_session] Creating new session ({session_key})")
        metadata = SessionMetadata(service=None, status="placeholder")
        active_sessions[session_key] = metadata
        return metadata

def store_service_in_session(session_key, service):
    lock = session_locks[session_key]
    with lock:
        metadata = active_sessions.get(session_key)
        if metadata:
            metadata.service = service
            metadata.mark_active()
            logger.info(f"[store_service_in_session] Stored service for {session_key}")
        else:
            metadata = SessionMetadata(service=service, status="active")
            active_sessions[session_key] = metadata
            logger.info(f"[store_service_in_session] Created new metadata for {session_key}")

def mark_session_pending_2fa(session_key):
    lock = session_locks[session_key]
    with lock:
        metadata = active_sessions.get(session_key)
        if metadata:
            metadata.mark_pending_2fa()
            logger.info(f"[mark_session_pending_2fa] Marked {session_key} as pending_2fa")
            return True
        return False

def get_session_service(session_key):
    lock = session_locks[session_key]
    with lock:
        metadata = active_sessions.get(session_key)
        if metadata and not metadata.is_expired():
            return metadata.service
        return None

def get_session_status(session_key) -> Optional[str]:
    lock = session_locks[session_key]
    with lock:
        metadata = active_sessions.get(session_key)
        if metadata and not metadata.is_expired():
            return metadata.status
        return None

def _cleanup_session(session_key, metadata):
    if metadata and metadata.service:
        try:
            metadata.service.close()
        except Exception as e:
            logger.error(f"[_cleanup_session] Error closing service: {e}")
    active_sessions.pop(session_key, None)

def close_session(session_key):
    lock = session_locks[session_key]
    with lock:
        metadata = active_sessions.pop(session_key, None)
        if metadata:
            logger.info(f"[close_session] Closing session {session_key} with status {metadata.status}")
            if metadata.service:
                try:
                    metadata.service.close()
                    logger.info(f"[close_session] Service closed for session {session_key}")
                except Exception as e:
                    logger.error(f"[close_session] Error closing service for {session_key}: {e}")
            return True
        logger.warning(f"[close_session] Session {session_key} not found in active sessions")
        return False

def get_number_of_active_sessions():
    return len(active_sessions)