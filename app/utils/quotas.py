from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from app.redis import get_redis_sync
from app.settings import (
    LINKEDIN_MAX_CONNECTIONS_PER_DAY,
    LINKEDIN_MAX_MESSAGES_PER_DAY,
)


@dataclass
class QuotaResult:
    allowed: bool
    quota_type: Optional[str] = None
    reason: Optional[str] = None
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_at: Optional[datetime] = None
    retry_after_seconds: Optional[int] = None


def _next_midnight_utc(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow


def _quota_key(outreach_profile_id: int, quota_name: str, day_suffix: str) -> str:
    return f"quota:{outreach_profile_id}:{day_suffix}:{quota_name}"


def reserve_action_quota(outreach_profile_id: int, action_type: str) -> QuotaResult:
    """
    Reserve a quota slot for the given outreach profile and action type.

    Returns a QuotaResult with allowed=False when a limit is hit.
    """
    now = datetime.now(timezone.utc)
    reset_at = _next_midnight_utc(now)
    reset_ts = int(reset_at.timestamp())
    date_suffix = now.strftime("%Y%m%d")
    redis_client = get_redis_sync()

    quota_checks = []
    if action_type == "send_connection":
        quota_checks.append(
            ("connections", LINKEDIN_MAX_CONNECTIONS_PER_DAY, "connection_limit")
        )
    if action_type == "send_message":
        quota_checks.append(("messages", LINKEDIN_MAX_MESSAGES_PER_DAY, "message_limit"))
    # Remove quotas that are disabled (<=0)
    quota_checks = [item for item in quota_checks if item[1] > 0]
    if not quota_checks:
        return QuotaResult(allowed=True)

    applied_quotas: Dict[str, Dict[str, Optional[int]]] = {}
    for quota_name, limit, reason in quota_checks:
        key = _quota_key(outreach_profile_id, quota_name, date_suffix)
        current_value = redis_client.incr(key)
        if current_value == 1:
            redis_client.expireat(key, reset_ts)

        if current_value > limit:
            redis_client.decr(key)
            # Roll back previously reserved quotas
            for data in applied_quotas.values():
                redis_client.decr(data["key"])

            retry_seconds = max(int((reset_at - now).total_seconds()), 60)
            return QuotaResult(
                allowed=False,
                quota_type=quota_name,
                reason=reason,
                limit=limit,
                remaining=0,
                reset_at=reset_at,
                retry_after_seconds=retry_seconds,
            )

        applied_quotas[quota_name] = {
            "key": key,
            "value": current_value,
            "limit": limit,
            "reason": reason,
        }

    # For reporting, use the most specific quota (connections/messages) when available
    preferred_order = ["connections", "messages"]
    chosen_name = next(
        (name for name in preferred_order if name in applied_quotas),
        next(iter(applied_quotas.keys())),
    )
    chosen_data = applied_quotas[chosen_name]
    chosen_limit = chosen_data["limit"]
    current_value = chosen_data["value"] or 0

    remaining = max(chosen_limit - current_value, 0) if chosen_limit else None
    return QuotaResult(
        allowed=True,
        quota_type=chosen_name,
        limit=chosen_limit,
        remaining=remaining,
        reset_at=reset_at,
        retry_after_seconds=int((reset_at - now).total_seconds()),
    )

