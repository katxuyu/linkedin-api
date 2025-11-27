from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urljoin

import requests
import sqlalchemy as sa

try:  # Optional dependency for resource metrics
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - psutil not installed
    psutil = None

from app import models
from app.crud_sync import LOGIN_CODE_STATUS_PENDING
from app.database import SyncSessionLocal
from app.redis import get_redis_sync
from app.services.linkedin_verification import LinkedInVerificationService
from app.settings import LINKEDIN_SERVICE_URL, N8N_WEBHOOK_URL

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://web:8000")
FLOWER_API_URL = os.getenv("FLOWER_API_URL", "http://flower:5555/api/workers")
SYSTEM_CHECK_TIMEOUT = float(os.getenv("STREAMLIT_SYSTEM_TIMEOUT_SECONDS", "2.5"))
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"Content-Type": "application/json"})


@contextmanager
def db_session() -> Iterator[sa.orm.Session]:
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _apply_search_filter(query, search_text: Optional[str], fields: List[Any]):
    if not search_text:
        return query
    like = f"%{search_text.lower()}%"
    clauses = []
    for field in fields:
        clauses.append(sa.func.lower(field).like(like))
    return query.filter(sa.or_(*clauses))


def _build_url(base_url: str, path: str) -> str:
    if not base_url:
        raise ValueError("Base URL is required.")
    base = base_url.rstrip("/")
    normalized_path = "/" + path.lstrip("/")
    return urljoin(base + "/", normalized_path.lstrip("/"))


def _request_json(
    method: str,
    base_url: str,
    path: str,
    *,
    token: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> Any:
    url = _build_url(base_url, path)
    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = HTTP_SESSION.request(
        method=method.upper(),
        url=url,
        json=payload,
        params=params,
        headers=headers or None,
        timeout=timeout,
    )
    if response.status_code >= 400:
        detail = ""
        try:
            detail = json.dumps(response.json())
        except Exception:
            detail = response.text
        raise RuntimeError(f"{method.upper()} {path} failed: HTTP {response.status_code} {detail}")
    if not response.content:
        return {}
    try:
        return response.json()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"Failed to decode JSON response from {path}: {exc}") from exc


def get_pending_requests(search_text: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_session() as db:
        query = (
            db.query(
                models.LinkedInLoginCodeRequest,
                models.OutreachLinkedInProfile,
                models.TargetLinkedInProfile,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInLoginCodeRequest.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetLinkedInProfile,
                models.LinkedInLoginCodeRequest.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .filter(models.LinkedInLoginCodeRequest.status == LOGIN_CODE_STATUS_PENDING)
            .order_by(models.LinkedInLoginCodeRequest.expires_at.asc())
        )

        if search_text:
            query = _apply_search_filter(
                query,
                search_text,
                [
                    models.OutreachLinkedInProfile.linkedin_email,
                    models.OutreachLinkedInProfile.linkedin_url,
                    models.TargetLinkedInProfile.name,
                ],
            )

        results = []
        now = datetime.now(timezone.utc)
        for request, outreach, target in query.all():
            remaining_seconds = max(0, int((request.expires_at - now).total_seconds()))
            results.append(
                {
                    "id": request.id,
                    "outreach_id": outreach.id,
                    "outreach_email": outreach.linkedin_email,
                    "outreach_url": outreach.linkedin_url,
                    "target_name": target.name if target else None,
                    "target_url": target.profile_url if target else None,
                    "campaign_history_id": request.campaign_history_id,
                    "pending_reason": request.pending_reason,
                    "status_detail": request.status_detail,
                    "expires_at": request.expires_at,
                    "remaining_seconds": remaining_seconds,
                }
            )
        return results


def submit_manual_code(request_id: int, code_value: str, operator_name: Optional[str]) -> int:
    with db_session() as db:
        service = LinkedInVerificationService(db)
        attempt = service.submit_attempt(
            request_id=request_id,
            code_value=code_value,
            submitted_by=operator_name or "streamlit",
            submitted_by_user_id=None,
            source="streamlit",
            two_captcha_used=False,
            result=None,
            error_details=None,
        )
        return attempt.id


def _format_timestamp(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def get_verification_history(search_text: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with db_session() as db:
        attempts_query = (
            db.query(
                models.LinkedInVerificationAttempt,
                models.LinkedInLoginCodeRequest,
                models.OutreachLinkedInProfile,
                models.TargetLinkedInProfile,
            )
            .join(
                models.LinkedInLoginCodeRequest,
                models.LinkedInVerificationAttempt.request_id == models.LinkedInLoginCodeRequest.id,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInLoginCodeRequest.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetLinkedInProfile,
                models.LinkedInLoginCodeRequest.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .order_by(models.LinkedInVerificationAttempt.submitted_at.desc())
        )

        events_query = (
            db.query(
                models.LinkedInScrapeEvent,
                models.OutreachLinkedInProfile,
                models.TargetLinkedInProfile,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInScrapeEvent.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetLinkedInProfile,
                models.LinkedInScrapeEvent.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .order_by(models.LinkedInScrapeEvent.created_at.desc())
        )

        if search_text:
            attempts_query = _apply_search_filter(
                attempts_query,
                search_text,
                [
                    models.OutreachLinkedInProfile.linkedin_email,
                    models.TargetLinkedInProfile.name,
                    models.LinkedInVerificationAttempt.submitted_by,
                ],
            )
            events_query = _apply_search_filter(
                events_query,
                search_text,
                [
                    models.OutreachLinkedInProfile.linkedin_email,
                    models.TargetLinkedInProfile.name,
                    models.LinkedInScrapeEvent.event_type,
                ],
            )

        rows: List[Dict[str, Any]] = []
        for attempt, request, outreach, target in attempts_query.limit(limit // 2).all():
            rows.append(
                {
                    "type": "attempt",
                    "outreach_email": outreach.linkedin_email,
                    "target_name": target.name if target else None,
                    "target_url": target.profile_url if target else None,
                    "detail": attempt.error_details or attempt.result or "code submitted",
                    "timestamp": _format_timestamp(attempt.submitted_at),
                    "action_taken": attempt.result,
                    "two_captcha_used": attempt.two_captcha_used,
                }
            )
        for event, outreach, target in events_query.limit(limit // 2).all():
            rows.append(
                {
                    "type": event.event_type or "event",
                    "outreach_email": outreach.linkedin_email,
                    "target_name": target.name if target else None,
                    "target_url": target.profile_url if target else None,
                    "detail": event.detail or event.action_taken,
                    "timestamp": _format_timestamp(event.created_at),
                    "action_taken": event.action_taken,
                    "two_captcha_used": event.two_captcha_used,
                }
            )

        rows.sort(key=lambda item: item["timestamp"] or "", reverse=True)
        return rows[:limit]


def get_recent_attempts(
    *,
    limit: int = 40,
    operator_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with db_session() as db:
        query = (
            db.query(
                models.LinkedInVerificationAttempt,
                models.LinkedInLoginCodeRequest,
                models.OutreachLinkedInProfile,
                models.TargetLinkedInProfile,
            )
            .join(
                models.LinkedInLoginCodeRequest,
                models.LinkedInVerificationAttempt.request_id == models.LinkedInLoginCodeRequest.id,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInLoginCodeRequest.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetLinkedInProfile,
                models.LinkedInLoginCodeRequest.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .order_by(models.LinkedInVerificationAttempt.submitted_at.desc())
        )

        if operator_filter:
            like = f"%{operator_filter.lower()}%"
            query = query.filter(
                sa.func.lower(models.LinkedInVerificationAttempt.submitted_by).like(like)
            )

        rows: List[Dict[str, Any]] = []
        for attempt, request, outreach, target in query.limit(limit).all():
            target_label = None
            if target:
                if target.name and target.profile_url:
                    target_label = f"{target.name} ({target.profile_url})"
                else:
                    target_label = target.name or target.profile_url
            rows.append(
                {
                    "attempt_id": attempt.id,
                    "request_id": request.id,
                    "outreach_email": outreach.linkedin_email,
                    "target_label": target_label or "—",
                    "submitted_by": attempt.submitted_by or "unknown",
                    "submitted_at": _format_timestamp(attempt.submitted_at),
                    "request_status": request.status,
                    "status_detail": request.status_detail,
                    "attempt_result": attempt.result,
                    "attempt_error": attempt.error_details,
                    "two_captcha_used": attempt.two_captcha_used,
                    "resolved_at": _format_timestamp(request.resolved_at),
                }
            )
        return rows


def get_target_statuses(search_text: Optional[str] = None, limit: int = 300) -> List[Dict[str, Any]]:
    with db_session() as db:
        query = (
            db.query(
                models.TargetLinkedInProfile,
                models.OutreachLinkedInProfile,
                models.TargetContactInfo,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.TargetLinkedInProfile.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetContactInfo,
                models.TargetContactInfo.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .order_by(models.TargetLinkedInProfile.modified_at.desc())
        )

        if search_text:
            query = _apply_search_filter(
                query,
                search_text,
                [
                    models.TargetLinkedInProfile.name,
                    models.TargetLinkedInProfile.profile_url,
                    models.OutreachLinkedInProfile.linkedin_email,
                ],
            )

        rows = []
        for target, outreach, contact in query.limit(limit).all():
            connection_status = "connected" if target.connected else "pending" if target.connection_pending else "not connected"
            rows.append(
                {
                    "target_name": target.name or "(unknown)",
                    "target_url": target.profile_url,
                    "outreach_email": outreach.linkedin_email,
                    "connection_status": connection_status,
                    "ghl_contact_id": contact.ghl_contact_id if contact else None,
                    "ghl_sync_status": contact.sync_status if contact else None,
                    "ghl_sync_error": contact.sync_error if contact else None,
                    "last_updated": _format_timestamp(target.modified_at),
                    "contact_info_updated": _format_timestamp(contact.updated_at) if contact else None,
                }
            )
        return rows


def _target_label(name: Optional[str], url: Optional[str]) -> str:
    if name:
        normalized = name.strip()
        if normalized and normalized.lower() not in {"welcome", "linkedin", "linkedin member", "member"}:
            return normalized
    if url:
        return url
    return "(unknown)"


def get_campaign_snapshot(limit: int = 20, *, include_all: bool = False) -> List[Dict[str, Any]]:
    with db_session() as db:
        terminal_statuses = (
            "completed",
            "success",
            "failed",
            "error",
            "errored",
            "skipped",
            "ignored",
            "cancelled",
            "rate_limited",
        )
        completed_sub = (
            db.query(
                models.CampaignStepHistory.campaign_history_id.label("campaign_history_id"),
                sa.func.count().label("completed_steps"),
                sa.func.max(models.CampaignStepHistory.modified_at).label("last_step_at"),
            )
            .filter(models.CampaignStepHistory.status.in_(terminal_statuses))
            .group_by(models.CampaignStepHistory.campaign_history_id)
            .subquery()
        )

        scheduled_sub = (
            db.query(
                models.ScheduledCampaignTask.campaign_history_id.label("campaign_history_id"),
                sa.func.count().label("scheduled_steps"),
                sa.func.min(models.ScheduledCampaignTask.scheduled_at).label("next_run_at"),
            )
            .filter(models.ScheduledCampaignTask.status == "scheduled")
            .group_by(models.ScheduledCampaignTask.campaign_history_id)
            .subquery()
        )

        query = (
            db.query(
                models.CampaignHistory,
                models.CampaignTemplate.name.label("campaign_name"),
                models.OutreachLinkedInProfile.linkedin_email.label("outreach_email"),
                models.TargetLinkedInProfile.name.label("target_name"),
                models.TargetLinkedInProfile.profile_url.label("target_url"),
                completed_sub.c.completed_steps,
                completed_sub.c.last_step_at,
                scheduled_sub.c.scheduled_steps,
                scheduled_sub.c.next_run_at,
            )
            .join(
                models.CampaignTemplate,
                models.CampaignHistory.campaign_template_id == models.CampaignTemplate.id,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.CampaignHistory.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .join(
                models.TargetLinkedInProfile,
                models.CampaignHistory.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .outerjoin(
                completed_sub,
                completed_sub.c.campaign_history_id == models.CampaignHistory.id,
            )
            .outerjoin(
                scheduled_sub,
                scheduled_sub.c.campaign_history_id == models.CampaignHistory.id,
            )
            .order_by(models.CampaignHistory.modified_at.desc())
            .limit(limit)
        )

        rows: List[Dict[str, Any]] = []
        for (
            campaign_history,
            campaign_name,
            outreach_email,
            target_name,
            target_url,
            completed_steps,
            last_step_at,
            scheduled_steps,
            next_run_at,
        ) in query.all():
            completed = int(completed_steps or 0)
            scheduled = int(scheduled_steps or 0)
            total_steps = int(campaign_history.number_of_steps or 0)
            if total_steps <= 0:
                inferred_total = completed + scheduled
                total_steps = inferred_total if inferred_total > 0 else completed
            if total_steps <= 0 and (completed or scheduled):
                total_steps = max(completed + scheduled, 1)
            progress = completed / total_steps if total_steps else 0
            pending = max(total_steps - completed, 0)
            rows.append(
                {
                    "campaign_history_id": campaign_history.id,
                    "runtime_id": str(campaign_history.runtime_id),
                    "target_profile_id": campaign_history.target_profile_id,
                    "outreach_profile_id": campaign_history.outreach_profile_id,
                    "campaign_name": campaign_name,
                    "outreach_email": outreach_email,
                    "target_name": target_name,
                    "target_url": target_url,
                    "target_label": _target_label(target_name, target_url),
                    "status": campaign_history.status,
                    "completed_steps": completed,
                    "pending_steps": pending,
                    "total_steps": total_steps,
                    "progress": progress,
                    "started_at": _format_timestamp(campaign_history.started_at),
                    "last_step_at": _format_timestamp(last_step_at or campaign_history.modified_at),
                    "next_run_at": _format_timestamp(next_run_at),
                    "queued_steps": scheduled,
                    "_modified_at_sort": campaign_history.modified_at,
                }
            )
        rows.sort(
            key=lambda item: item.get("_modified_at_sort") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        if include_all:
            for entry in rows:
                entry.pop("_modified_at_sort", None)
            return rows
        # Keep only the most recent record per outreach seat + target profile
        deduped: List[Dict[str, Any]] = []
        seen_keys: set[tuple[int, int]] = set()
        for entry in rows:
            key = (entry.get("outreach_profile_id"), entry.get("target_profile_id"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            entry.pop("_modified_at_sort", None)
            deduped.append(entry)
        return deduped


def get_campaign_failures(limit: int = 50) -> Dict[str, Any]:
    statuses = ["failed", "error", "errored"]
    with db_session() as db:
        status_counts = {
            status: count
            for status, count in (
                db.query(
                    models.CampaignStepHistory.status,
                    sa.func.count(models.CampaignStepHistory.id),
                )
                .filter(models.CampaignStepHistory.status.in_(statuses))
                .group_by(models.CampaignStepHistory.status)
                .all()
            )
        }
        failed_campaigns = (
            db.query(sa.func.count(models.CampaignHistory.id))
            .filter(models.CampaignHistory.status == "failed")
            .scalar()
            or 0
        )
        query = (
            db.query(
                models.CampaignStepHistory,
                models.CampaignHistory,
                models.TargetLinkedInProfile,
                models.OutreachLinkedInProfile,
                models.CampaignTemplate,
            )
            .join(
                models.CampaignHistory,
                models.CampaignStepHistory.campaign_history_id == models.CampaignHistory.id,
            )
            .join(
                models.TargetLinkedInProfile,
                models.CampaignHistory.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.CampaignHistory.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .join(
                models.CampaignTemplate,
                models.CampaignHistory.campaign_template_id == models.CampaignTemplate.id,
            )
            .filter(models.CampaignStepHistory.status.in_(statuses))
            .order_by(models.CampaignStepHistory.modified_at.desc())
            .limit(limit)
        )

        rows: List[Dict[str, Any]] = []
        for (
            step_history,
            campaign_history,
            target,
            outreach,
            template,
        ) in query.all():
            details = step_history.details
            if isinstance(details, dict):
                detail_text = details.get("details") or details.get("error") or json.dumps(details)
            else:
                detail_text = str(details) if details else ""
            rows.append(
                {
                    "campaign": template.name,
                    "campaign_history_id": campaign_history.id,
                    "runtime_id": str(campaign_history.runtime_id),
                    "outreach_email": outreach.linkedin_email,
                    "target_display": target.name or target.profile_url or "(unknown)",
                    "target_url": target.profile_url,
                    "step_number": step_history.step_number,
                    "action": step_history.action,
                    "status": step_history.status,
                    "details": detail_text,
                    "updated_at": _format_timestamp(step_history.modified_at),
                }
            )

        return {
            "status_counts": status_counts,
            "failed_campaigns": failed_campaigns,
            "rows": rows,
        }


def get_action_throughput(hours_back: int = 24) -> List[Dict[str, Any]]:
    end_bucket = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start_bucket = end_bucket - timedelta(hours=hours_back - 1)
    with db_session() as db:
        query = (
            db.query(
                sa.func.date_trunc("hour", models.Action.created_at).label("bucket"),
                sa.func.count().label("count"),
            )
            .filter(models.Action.created_at >= start_bucket)
            .group_by(sa.func.date_trunc("hour", models.Action.created_at))
            .order_by(sa.func.date_trunc("hour", models.Action.created_at))
        )
        counts = {
            row.bucket.replace(tzinfo=timezone.utc): row.count
            for row in query.all()
            if row.bucket is not None
        }

    buckets: List[Dict[str, Any]] = []
    cursor = start_bucket
    while cursor <= end_bucket:
        buckets.append(
            {
                "bucket": _format_timestamp(cursor),
                "count": int(counts.get(cursor, 0)),
            }
        )
        cursor += timedelta(hours=1)
    return buckets


def get_target_timelines(limit: int = 40) -> List[Dict[str, Any]]:
    with db_session() as db:
        query = (
            db.query(
                models.CampaignStepHistory,
                models.CampaignHistory,
                models.TargetLinkedInProfile,
                models.OutreachLinkedInProfile,
            )
            .join(
                models.CampaignHistory,
                models.CampaignStepHistory.campaign_history_id == models.CampaignHistory.id,
            )
            .join(
                models.TargetLinkedInProfile,
                models.CampaignHistory.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.CampaignHistory.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .order_by(models.CampaignStepHistory.modified_at.desc())
            .limit(limit)
        )

        rows: List[Dict[str, Any]] = []
        for step_history, campaign_history, target, outreach in query.all():
            detail_value = step_history.details
            if isinstance(detail_value, (dict, list)):
                try:
                    detail_text = json.dumps(detail_value)
                except TypeError:
                    detail_text = str(detail_value)
            elif detail_value is None:
                detail_text = ""
            else:
                detail_text = str(detail_value)
            rows.append(
                {
                    "campaign_history_id": campaign_history.id,
                    "runtime_id": str(campaign_history.runtime_id),
                    "outreach_email": outreach.linkedin_email,
                    "target_name": target.name or "(unknown)",
                    "target_url": target.profile_url,
                    "step_number": step_history.step_number,
                    "action": step_history.action,
                    "status": step_history.status,
                    "updated_at": _format_timestamp(step_history.modified_at),
                    "details": detail_text,
                }
            )
        return rows


def get_campaign_success_metrics() -> Dict[str, Any]:
    with db_session() as db:
        total_histories = db.query(sa.func.count(models.CampaignHistory.id)).scalar() or 0
        completed_histories = (
            db.query(sa.func.count(models.CampaignHistory.id))
            .filter(models.CampaignHistory.status == "completed")
            .scalar()
            or 0
        )
        responded = (
            db.query(sa.func.count(models.CampaignHistory.id))
            .filter(models.CampaignHistory.target_profile_responded.is_(True))
            .scalar()
            or 0
        )
        connected = (
            db.query(sa.func.count(models.TargetLinkedInProfile.id))
            .filter(models.TargetLinkedInProfile.connected.is_(True))
            .scalar()
            or 0
        )
        synced_contacts = (
            db.query(sa.func.count(models.TargetContactInfo.id))
            .filter(models.TargetContactInfo.sync_status == "synced")
            .scalar()
            or 0
        )
        pending_syncs = (
            db.query(sa.func.count(models.TargetContactInfo.id))
            .filter(models.TargetContactInfo.sync_status != "synced")
            .scalar()
            or 0
        )

    def _pct(part: int, whole: int) -> float:
        return round((part / whole) * 100, 2) if whole else 0.0

    return {
        "total_runs": total_histories,
        "completed_runs": completed_histories,
        "completed_pct": _pct(completed_histories, total_histories),
        "responses": responded,
        "response_pct": _pct(responded, total_histories),
        "connections": connected,
        "contacts_synced": synced_contacts,
        "pending_syncs": pending_syncs,
    }


def get_outreach_locks(limit: int = 50) -> Dict[str, Any]:
    try:
        client = get_redis_sync()
    except Exception as exc:  # pragma: no cover - Redis unavailable
        return {"error": str(exc), "session_locks": [], "login_code_locks": []}

    session_locks: List[Dict[str, Any]] = []
    login_code_locks: List[Dict[str, Any]] = []

    for key in client.scan_iter(match="lock:outreach:*"):
        ttl = client.ttl(key)
        session_locks.append(
            {
                "lock_key": key.decode() if isinstance(key, bytes) else key,
                "ttl_seconds": ttl,
            }
        )
        if len(session_locks) >= limit:
            break

    for key in client.scan_iter(match="login_code_lock:*"):
        ttl = client.ttl(key)
        login_code_locks.append(
            {
                "lock_key": key.decode() if isinstance(key, bytes) else key,
                "ttl_seconds": ttl,
            }
        )
        if len(login_code_locks) >= limit:
            break

    return {
        "session_locks": session_locks,
        "login_code_locks": login_code_locks,
    }


def get_celery_queue_depths(queues: Optional[List[str]] = None) -> Dict[str, int]:
    queues = queues or ["celery"]
    counts: Dict[str, int] = {}
    try:
        client = get_redis_sync()
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    for queue in queues:
        try:
            counts[queue] = int(client.llen(queue))
        except Exception:
            counts[queue] = -1
    return counts


def get_system_health() -> List[Dict[str, Any]]:
    statuses: List[Dict[str, Any]] = []

    def add_status(name: str, ok: bool, detail: str = "", latency_ms: Optional[int] = None):
        statuses.append(
            {
                "component": name,
                "status": "healthy" if ok else "degraded",
                "detail": detail,
                "latency_ms": latency_ms,
            }
        )

    # Postgres check
    try:
        with db_session() as db:
            db.execute(sa.text("SELECT 1"))
        add_status("Postgres", True)
    except Exception as exc:
        add_status("Postgres", False, str(exc))

    # Redis check
    try:
        client = get_redis_sync()
        client.ping()
        add_status("Redis", True)
    except Exception as exc:  # pragma: no cover
        add_status("Redis", False, str(exc))

    # HTTP checks
    http_checks: List[Tuple[str, str]] = [
        ("FastAPI", f"{BACKEND_BASE_URL.rstrip('/')}/openapi.json"),
        ("LinkedIn Service", f"{LINKEDIN_SERVICE_URL.rstrip('/')}/health"),
        ("Celery Flower", FLOWER_API_URL.rstrip("/")),
    ]
    for name, url in http_checks:
        start_time = datetime.now()
        try:
            resp = requests.get(url, timeout=SYSTEM_CHECK_TIMEOUT)
            latency = int((datetime.now() - start_time).total_seconds() * 1000)
            ok = resp.status_code < 400
            detail = f"HTTP {resp.status_code}"
            add_status(name, ok, detail, latency)
        except Exception as exc:
            add_status(name, False, str(exc))

    return statuses


def get_gohighlevel_account_health(expiring_within_days: int = 3) -> Dict[str, Any]:
    cutoff = datetime.now(timezone.utc) + timedelta(days=expiring_within_days)
    with db_session() as db:
        total = db.query(sa.func.count(models.GoHighLevelAccount.id)).scalar() or 0
        active = (
            db.query(sa.func.count(models.GoHighLevelAccount.id))
            .filter(models.GoHighLevelAccount.is_active.is_(True))
            .scalar()
            or 0
        )
        expiring = (
            db.query(sa.func.count(models.GoHighLevelAccount.id))
            .filter(
                models.GoHighLevelAccount.expires_at.isnot(None),
                models.GoHighLevelAccount.expires_at <= cutoff,
                models.GoHighLevelAccount.is_active.is_(True),
            )
            .scalar()
            or 0
        )
        expired = (
            db.query(sa.func.count(models.GoHighLevelAccount.id))
            .filter(
                models.GoHighLevelAccount.expires_at.isnot(None),
                models.GoHighLevelAccount.expires_at < datetime.now(timezone.utc),
            )
            .scalar()
            or 0
        )
        sample_rows = (
            db.query(
                models.GoHighLevelAccount.display_name,
                models.GoHighLevelAccount.location_id,
                models.GoHighLevelAccount.expires_at,
                models.GoHighLevelAccount.is_active,
            )
            .order_by(models.GoHighLevelAccount.updated_at.desc())
            .limit(15)
            .all()
        )
    sample = [
        {
            "display_name": row.display_name or row.location_id,
            "location_id": row.location_id,
            "expires_at": _format_timestamp(row.expires_at),
            "is_active": row.is_active,
        }
        for row in sample_rows
    ]
    return {
        "total": total,
        "active": active,
        "expiring_within_days": expiring,
        "expired": expired,
        "sample": sample,
    }


def get_n8n_status(timeout: float = 5.0) -> Dict[str, Any]:
    if not N8N_WEBHOOK_URL:
        return {"enabled": False, "detail": "N8N webhook URL not configured."}
    try:
        payload = {
            "event": "healthcheck",
            "ping": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        headers = {"X-Streamlit-Healthcheck": "1"}
        resp = requests.post(
            N8N_WEBHOOK_URL,
            json=payload,
            headers=headers,
            params={"healthcheck": "true"},
            timeout=timeout,
        )
        return {
            "enabled": True,
            "status_code": resp.status_code,
            "ok": resp.status_code < 400,
            "detail": resp.text[:200] or "POST ping sent",
        }
    except Exception as exc:  # pragma: no cover
        return {"enabled": True, "ok": False, "detail": str(exc)}


def get_n8n_webhook_events(limit: int = 200) -> List[Dict[str, Any]]:
    with db_session() as db:
        query = (
            db.query(
                models.LinkedInScrapeEvent,
                models.OutreachLinkedInProfile,
                models.TargetLinkedInProfile,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInScrapeEvent.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetLinkedInProfile,
                models.LinkedInScrapeEvent.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .filter(models.LinkedInScrapeEvent.event_type == "n8n_webhook")
            .order_by(models.LinkedInScrapeEvent.created_at.desc())
            .limit(limit)
        )
        rows: List[Dict[str, Any]] = []
        for event, outreach, target in query.all():
            rows.append(
                {
                    "timestamp": _format_timestamp(event.created_at),
                    "outreach_email": outreach.linkedin_email,
                    "target_url": target.profile_url if target else None,
                    "detail": event.detail,
                    "action_taken": event.action_taken,
                    "metadata": event.metadata_json,
                }
            )
        return rows


def get_recent_alerts(limit: int = 50) -> List[Dict[str, Any]]:
    with db_session() as db:
        query = (
            db.query(
                models.LinkedInScrapeEvent,
                models.OutreachLinkedInProfile.linkedin_email,
                models.TargetLinkedInProfile.name,
                models.TargetLinkedInProfile.profile_url,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInScrapeEvent.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetLinkedInProfile,
                models.LinkedInScrapeEvent.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .filter(
                sa.or_(
                    sa.func.lower(models.LinkedInScrapeEvent.event_type).like("%error%"),
                    sa.func.lower(models.LinkedInScrapeEvent.event_type).like("%rate%"),
                    sa.func.lower(models.LinkedInScrapeEvent.event_type).like("%captcha%"),
                    sa.func.lower(models.LinkedInScrapeEvent.event_type).like("%timeout%"),
                )
            )
            .order_by(models.LinkedInScrapeEvent.created_at.desc())
            .limit(limit)
        )

        rows: List[Dict[str, Any]] = []
        for event, outreach_email, target_name, target_url in query.all():
            rows.append(
                {
                    "event_type": event.event_type,
                    "detail": event.detail or event.action_taken,
                    "outreach_email": outreach_email,
                    "target_name": target_name,
                    "target_url": target_url,
                    "created_at": _format_timestamp(event.created_at),
                    "two_captcha_used": event.two_captcha_used,
                }
            )
        return rows


def get_manual_action_queue(limit: int = 50) -> List[Dict[str, Any]]:
    tasks: List[Dict[str, Any]] = []
    with db_session() as db:
        code_query = (
            db.query(
                models.LinkedInLoginCodeRequest,
                models.OutreachLinkedInProfile.linkedin_email,
                models.TargetLinkedInProfile.profile_url,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInLoginCodeRequest.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .outerjoin(
                models.TargetLinkedInProfile,
                models.LinkedInLoginCodeRequest.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .filter(models.LinkedInLoginCodeRequest.status == LOGIN_CODE_STATUS_PENDING)
            .order_by(models.LinkedInLoginCodeRequest.created_at.asc())
            .limit(limit // 2)
        )
        for request, outreach_email, target_url in code_query.all():
            tasks.append(
                {
                    "task_type": "verification_code",
                    "outreach_email": outreach_email,
                    "target_url": target_url,
                    "opened_at": _format_timestamp(request.created_at),
                    "status": "pending",
                    "detail": request.pending_reason or "Awaiting manual code",
                }
            )

        contact_query = (
            db.query(
                models.TargetContactInfo,
                models.TargetLinkedInProfile,
                models.OutreachLinkedInProfile,
            )
            .join(
                models.TargetLinkedInProfile,
                models.TargetContactInfo.target_profile_id == models.TargetLinkedInProfile.id,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.TargetContactInfo.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .filter(models.TargetContactInfo.sync_status != "synced")
            .order_by(models.TargetContactInfo.updated_at.desc())
            .limit(limit // 2)
        )
        for contact_info, target, outreach in contact_query.all():
            tasks.append(
                {
                    "task_type": "contact_sync",
                    "outreach_email": outreach.linkedin_email,
                    "target_url": target.profile_url,
                    "opened_at": _format_timestamp(contact_info.updated_at or contact_info.created_at),
                    "status": contact_info.sync_status,
                    "detail": contact_info.sync_error or contact_info.last_fetch_error or "Awaiting sync",
                }
            )
    tasks.sort(key=lambda item: item["opened_at"] or "", reverse=True)
    return tasks[:limit]


def get_resource_snapshot() -> Dict[str, Any]:
    snapshot: Dict[str, Any] = {
        "cpu_percent": None,
        "memory_percent": None,
        "load_avg": None,
    }
    if psutil:
        try:
            snapshot["cpu_percent"] = psutil.cpu_percent(interval=None)
            snapshot["memory_percent"] = psutil.virtual_memory().percent
        except Exception:
            pass
    try:
        snapshot["load_avg"] = os.getloadavg()
    except (AttributeError, OSError):
        snapshot["load_avg"] = None
    return snapshot


def list_outreach_profiles() -> List[Dict[str, Any]]:
    with db_session() as db:
        profiles = (
            db.query(
                models.OutreachLinkedInProfile.id,
                models.OutreachLinkedInProfile.linkedin_email,
            )
            .order_by(models.OutreachLinkedInProfile.linkedin_email.asc())
            .all()
        )
        return [
            {"id": profile.id, "linkedin_email": profile.linkedin_email}
            for profile in profiles
        ]


def create_ops_note(
    outreach_profile_id: int,
    note_text: str,
    *,
    operator_name: Optional[str] = None,
) -> int:
    with db_session() as db:
        event = models.LinkedInScrapeEvent(
            outreach_profile_id=outreach_profile_id,
            event_type="ops_note",
            detail=note_text.strip(),
            action_taken=operator_name or "streamlit",
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event.id


def get_ops_notes(limit: int = 50) -> List[Dict[str, Any]]:
    with db_session() as db:
        query = (
            db.query(
                models.LinkedInScrapeEvent,
                models.OutreachLinkedInProfile.linkedin_email,
            )
            .join(
                models.OutreachLinkedInProfile,
                models.LinkedInScrapeEvent.outreach_profile_id == models.OutreachLinkedInProfile.id,
            )
            .filter(models.LinkedInScrapeEvent.event_type == "ops_note")
            .order_by(models.LinkedInScrapeEvent.created_at.desc())
            .limit(limit)
        )
        rows: List[Dict[str, Any]] = []
        for event, outreach_email in query.all():
            rows.append(
                {
                    "note_id": event.id,
                    "outreach_email": outreach_email,
                    "detail": event.detail,
                    "author": event.action_taken,
                    "created_at": _format_timestamp(event.created_at),
                }
            )
        return rows


# --- Campaign orchestration helpers (mirror testing.ipynb flow) -----------------


def _wait_for_service(url: str, *, expect: int = 200, timeout: int = 120, interval: float = 1.0) -> Tuple[bool, str]:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            resp = HTTP_SESSION.get(url, timeout=5)
            if resp.status_code == expect:
                return True, f"HTTP {resp.status_code}"
            last_error = f"HTTP {resp.status_code} body={resp.text[:200]}"
        except Exception as exc:  # pragma: no cover - network failures
            last_error = str(exc)
        time.sleep(interval)
    return False, last_error


def check_services(base_url: str, li_service_url: str, timeout: int = 15) -> Dict[str, Any]:
    web_ok, web_detail = _wait_for_service(urljoin(base_url, "/"), timeout=timeout)
    li_ok, li_detail = _wait_for_service(urljoin(li_service_url, "/health"), timeout=timeout)
    return {
        "web": {"ok": web_ok, "detail": web_detail},
        "linkedin_service": {"ok": li_ok, "detail": li_detail},
    }


def admin_login(base_url: str, email: str, password: str) -> Dict[str, Any]:
    return _request_json(
        "POST",
        base_url,
        "/auth/login",
        payload={"email": email, "password": password},
    )


def create_registration_key(base_url: str, admin_token: str) -> str:
    data = _request_json(
        "POST",
        base_url,
        "/admin/registration-keys",
        token=admin_token,
    )
    return data.get("registration_key")


def register_user(base_url: str, email: str, password: str, registration_key: str) -> Dict[str, Any]:
    url = _build_url(base_url, "/auth/register")
    resp = HTTP_SESSION.post(
        url,
        json={"email": email, "password": password, "registration_key": registration_key},
        timeout=30,
    )
    if resp.status_code < 300:
        return {"status": "created", "data": resp.json()}
    if 400 <= resp.status_code < 500:
        return {"status": "exists", "status_code": resp.status_code, "detail": resp.text}
    raise RuntimeError(f"User registration failed: HTTP {resp.status_code} {resp.text}")


def user_login(base_url: str, email: str, password: str) -> Dict[str, Any]:
    return _request_json(
        "POST",
        base_url,
        "/auth/login",
        payload={"email": email, "password": password},
    )


def build_ghl_auth_url(base_url: str, user_token: str) -> Dict[str, Any]:
    return _request_json(
        "GET",
        base_url,
        "/gh/auth",
        token=user_token,
    )


def exchange_ghl_code(base_url: str, user_token: str, code: str, client_state: Optional[str] = None) -> Dict[str, Any]:
    payload = {"code": code}
    if client_state:
        payload["client_state"] = client_state
    return _request_json(
        "POST",
        base_url,
        "/gh/oauth/manual-exchange",
        token=user_token,
        payload=payload,
    )


def list_ghl_accounts(base_url: str, user_token: str) -> List[Dict[str, Any]]:
    data = _request_json(
        "GET",
        base_url,
        "/gh/accounts",
        token=user_token,
    )
    if isinstance(data, list):
        return data
    return []


def list_registered_outreach_profiles(
    base_url: str, user_token: str
) -> List[Dict[str, Any]]:
    data = _request_json(
        "GET",
        base_url,
        "/profiles/outreach/list",
        token=user_token,
    )
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        payload = data.get("data")
        if isinstance(payload, list):
            return payload
    return []


def find_outreach_profile_by_email(base_url: str, user_token: str, linkedin_email: str) -> Optional[Dict[str, Any]]:
    resp = _request_json(
        "GET",
        base_url,
        "/profiles/outreach/find-by-email",
        token=user_token,
        params={"linkedin_email": linkedin_email},
    )
    return resp


def register_outreach_profile(base_url: str, user_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = _build_url(base_url, "/profiles/outreach/register")
    resp = HTTP_SESSION.post(url, json=payload, headers={"Authorization": f"Bearer {user_token}"}, timeout=40)
    if resp.status_code < 300:
        return {"status": "created", "data": resp.json()}
    if resp.status_code == 403:
        existing = find_outreach_profile_by_email(base_url, user_token, payload["linkedin_email"])
        if existing:
            return {"status": "exists", "data": existing}
    raise RuntimeError(f"Outreach registration failed: HTTP {resp.status_code} {resp.text}")


def create_campaign_template(base_url: str, user_token: str, template_payload: Dict[str, Any]) -> Dict[str, Any]:
    return _request_json(
        "POST",
        base_url,
        "/campaigns/templates/create",
        token=user_token,
        payload=template_payload,
    )


def run_campaign(base_url: str, user_token: str, run_payload: Dict[str, Any]) -> Dict[str, Any]:
    return _request_json(
        "POST",
        base_url,
        "/campaigns/run",
        token=user_token,
        payload=run_payload,
        timeout=60,
    )


