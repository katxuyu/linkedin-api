"""
Celery task to fetch LinkedIn contact information and push it to GoHighLevel.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
import re
from typing import Any, Dict, Optional, Tuple

from celery import states

from app.celery_app import celery_app
from app.database import SyncSessionLocal
from app.errors import (
    GoHighLevelApiError,
    GoHighLevelAuthError,
    GoHighLevelRetryableError,
)
from app.services.gohighlevel import GoHighLevelService
from app.services.service_manager import LinkedInMicroserviceService
from app.settings import (
    LINKEDIN_CONTACT_SYNC_TAG,
    SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
    logger,
)
from app.utils.locks import profile_lock
from app import crud_sync
from app import models


# -----------------------------
# Status helpers/constants
# -----------------------------
STATUS_PENDING_FETCH = "pending_fetch"
STATUS_PENDING_SYNC = "pending_sync"
STATUS_SYNCED = "synced"
STATUS_FETCH_FAILED = "fetch_failed"
STATUS_SYNC_FAILED = "sync_failed"
STATUS_RETRY = "retry"
STATUS_NO_ACCOUNT = "no_account"

IN_PROGRESS_STATUSES = {
    STATUS_PENDING_FETCH,
    STATUS_PENDING_SYNC,
    STATUS_RETRY,
}


@celery_app.task(
    name="app.tasks.contact_sync.sync_linkedin_contact_to_gohighlevel",
    bind=True,
    autoretry_for=(GoHighLevelRetryableError,),
    retry_kwargs={"max_retries": 5, "countdown": 300},
    retry_backoff=True,
    retry_backoff_max=1800,
)
def sync_linkedin_contact_to_gohighlevel(
    self,
    *,
    campaign_history_id: Optional[int],
    target_profile_id: int,
    outreach_profile_id: int,
    target_profile_url: str,
) -> Dict[str, Any]:
    """
    Fetch LinkedIn contact info for the target and upsert into GoHighLevel.
    """
    task_id = self.request.id
    logger.info(
        "%s: Starting contact sync (campaign_history_id=%s, target_profile_id=%s, outreach_profile_id=%s)",
        task_id,
        campaign_history_id,
        target_profile_id,
        outreach_profile_id,
    )

    with SyncSessionLocal() as db:
        existing = crud_sync.get_target_contact_info(db, target_profile_id)
        if existing and existing.sync_status == STATUS_SYNCED:
            logger.info(
                "%s: Contact info already synced for target_profile_id=%s; skipping",
                task_id,
                target_profile_id,
            )
            return {"status": "already_synced"}

        outreach_profile = crud_sync.get_outreach_profile_by_id(db, outreach_profile_id)
        if not outreach_profile:
            logger.error(
                "%s: Outreach profile %s not found; aborting contact sync",
                task_id,
                outreach_profile_id,
            )
            return {"status": "error", "reason": "outreach_profile_not_found"}

        gohighlevel_location_id = (
            existing.gohighlevel_location_id if existing and existing.gohighlevel_location_id else None
        )
        if gohighlevel_location_id is None and outreach_profile.gohighlevel_location_id:
            gohighlevel_location_id = outreach_profile.gohighlevel_location_id

        user_id = outreach_profile.user_id
        if gohighlevel_location_id is None and user_id is not None:
            default_account = crud_sync.get_default_gohighlevel_account(db, user_id)
            if default_account:
                gohighlevel_location_id = default_account.location_id

        if gohighlevel_location_id is None:
            logger.warning(
                "%s: No GoHighLevel location available for outreach_profile_id=%s; skipping sync",
                task_id,
                outreach_profile_id,
            )
            _ensure_contact_record(
                db=db,
                target_profile_id=target_profile_id,
                outreach_profile_id=outreach_profile_id,
                gohighlevel_location_id=None,
                sync_status=STATUS_NO_ACCOUNT,
                sync_error="No GoHighLevel location associated with outreach profile",
            )
            return {"status": "skipped", "reason": "no_gohighlevel_location"}

        _ensure_contact_record(
            db=db,
            target_profile_id=target_profile_id,
            outreach_profile_id=outreach_profile_id,
            gohighlevel_location_id=gohighlevel_location_id,
            sync_status=STATUS_PENDING_FETCH,
            sync_error=None,
        )

    try:
        contact_payload = _fetch_contact_info(
            outreach_profile_id=outreach_profile_id,
            target_profile_id=target_profile_id,
            target_profile_url=target_profile_url,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "%s: Failed fetching contact info for target_profile_id=%s",
            task_id,
            target_profile_id,
        )
        with SyncSessionLocal() as db:
            _ensure_contact_record(
                db=db,
                target_profile_id=target_profile_id,
                outreach_profile_id=outreach_profile_id,
                gohighlevel_location_id=gohighlevel_location_id,
                sync_status=STATUS_FETCH_FAILED,
                sync_error=str(exc),
                last_fetch_error=str(exc),
            )
        raise self.retry(exc=exc, countdown=600)

    with SyncSessionLocal() as db:
        contact_info = _ensure_contact_record(
            db=db,
            target_profile_id=target_profile_id,
            outreach_profile_id=outreach_profile_id,
            gohighlevel_location_id=gohighlevel_location_id,
            sync_status=STATUS_PENDING_SYNC,
            sync_error=None,
            raw_sections=contact_payload.raw_sections,
            normalized=contact_payload.normalized,
            primary_email=contact_payload.primary_email,
            phones=contact_payload.phones,
            urls=contact_payload.urls,
        )

    try:
        ghl_response = _push_to_gohighlevel(
            target_profile_id=target_profile_id,
            outreach_profile_id=outreach_profile_id,
            gohighlevel_location_id=gohighlevel_location_id,
            payload=contact_payload,
        )
    except GoHighLevelAuthError as exc:
        logger.exception(
            "%s: GoHighLevel auth failure for location %s",
            task_id,
            gohighlevel_location_id,
        )
        _record_sync_failure(
            target_profile_id=target_profile_id,
            status=STATUS_SYNC_FAILED,
            error=f"GoHighLevel auth error: {exc}",
        )
        raise
    except GoHighLevelRetryableError as exc:
        logger.warning(
            "%s: Temporary GoHighLevel failure for location %s: %s",
            task_id,
            gohighlevel_location_id,
            exc,
        )
        _record_sync_failure(
            target_profile_id=target_profile_id,
            status=STATUS_RETRY,
            error=str(exc),
        )
        raise self.retry(exc=exc)
    except GoHighLevelApiError as exc:
        logger.exception(
            "%s: Non-retryable GoHighLevel error for location %s",
            task_id,
            gohighlevel_location_id,
        )
        _record_sync_failure(
            target_profile_id=target_profile_id,
            status=STATUS_SYNC_FAILED,
            error=f"GoHighLevel error: {exc}",
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "%s: Unexpected error syncing contact to GoHighLevel (location=%s)",
            task_id,
            gohighlevel_location_id,
        )
        _record_sync_failure(
            target_profile_id=target_profile_id,
            status=STATUS_SYNC_FAILED,
            error=str(exc),
        )
        raise

    ghl_contact_id = (
        ghl_response.get("contact", {}).get("id")
        if isinstance(ghl_response, dict)
        else None
    ) or ghl_response.get("id") if isinstance(ghl_response, dict) else None

    with SyncSessionLocal() as db:
        crud_sync.update_contact_sync_status(
            db,
            target_profile_id=target_profile_id,
            sync_status=STATUS_SYNCED,
            sync_error=None,
            last_synced_at=datetime.now(timezone.utc),
            ghl_contact_id=ghl_contact_id,
        )

    logger.info(
        "%s: Contact sync completed for target_profile_id=%s",
        task_id,
        target_profile_id,
    )
    return {
        "status": STATUS_SYNCED,
        "ghl_contact_id": ghl_contact_id,
        "gohighlevel_location_id": gohighlevel_location_id,
    }


# ---------------------------------------------------------------------------
# Fetch & persistence helpers
# ---------------------------------------------------------------------------

class ContactPayload:
    """Structured contact payload used for persistence and GoHighLevel upsert."""

    def __init__(
        self,
        *,
        raw_sections: Any,
        normalized: Dict[str, Any],
        primary_email: Optional[str],
        phones: Any,
        urls: Any,
        notes: str,
    ):
        self.raw_sections = raw_sections
        self.normalized = normalized
        self.primary_email = primary_email
        self.phones = phones
        self.urls = urls
        self.notes = notes


def _fetch_contact_info(
    *,
    outreach_profile_id: int,
    target_profile_id: int,
    target_profile_url: str,
) -> ContactPayload:
    with profile_lock(
        outreach_profile_id=outreach_profile_id,
        blocking_timeout_seconds=SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS,
    ):
        service = LinkedInMicroserviceService(outreach_profile_id=outreach_profile_id)
        try:
            if not service.start():
                raise RuntimeError("Unable to start LinkedIn microservice session")

            result = service.fetch_contact_info(target_profile_url)
        finally:
            service.close()

    if not isinstance(result, dict):
        raise RuntimeError("LinkedIn contact info response malformed")

    status = result.get("status")
    if status != "success":
        error_message = result.get("error") or status or "unknown_error"
        raise RuntimeError(f"LinkedIn contact info fetch failed: {error_message}")

    contact_info = result.get("contact_info") or {}
    raw_sections = contact_info.get("raw_sections") or []
    normalized = contact_info.get("normalized") or {}

    primary_email = normalized.get("primary_email")
    if not primary_email:
        primary_email = _first_email(normalized)

    phones = normalized.get("phones") or []
    urls = normalized.get("websites") or []

    notes = _build_notes(normalized, raw_sections, target_profile_url)
    return ContactPayload(
        raw_sections=raw_sections,
        normalized=normalized,
        primary_email=primary_email,
        phones=phones,
        urls=urls,
        notes=notes,
    )


def _ensure_contact_record(
    *,
    db,
    target_profile_id: int,
    outreach_profile_id: int,
    gohighlevel_location_id: Optional[str],
    sync_status: str,
    sync_error: Optional[str],
    raw_sections: Any = None,
    normalized: Optional[Dict[str, Any]] = None,
    primary_email: Optional[str] = None,
    phones: Any = None,
    urls: Any = None,
    last_fetch_error: Optional[str] = None,
) -> models.TargetContactInfo:
    existing = crud_sync.get_target_contact_info(db, target_profile_id)
    if existing and raw_sections is None and normalized is None:
        crud_sync.update_contact_sync_status(
            db,
            target_profile_id=target_profile_id,
            sync_status=sync_status,
            sync_error=sync_error,
        )
        return crud_sync.get_target_contact_info(db, target_profile_id)

    record = crud_sync.upsert_target_contact_info(
        db,
        target_profile_id=target_profile_id,
        outreach_profile_id=outreach_profile_id,
        gohighlevel_location_id=gohighlevel_location_id,
        raw_sections=raw_sections or (existing.raw_sections if existing else []),
        normalized_data=normalized or (existing.normalized_data if existing else {}),
        primary_email=primary_email if primary_email is not None else (existing.primary_email if existing else None),
        phones_json=phones if phones is not None else (existing.phones_json if existing else None),
        urls_json=urls if urls is not None else (existing.urls_json if existing else None),
        sync_status=sync_status,
        sync_error=sync_error,
        last_fetch_error=last_fetch_error,
        ghl_contact_id=existing.ghl_contact_id if existing else None,
    )
    return record


def _record_sync_failure(*, target_profile_id: int, status: str, error: str) -> None:
    with SyncSessionLocal() as db:
        crud_sync.update_contact_sync_status(
            db,
            target_profile_id=target_profile_id,
            sync_status=status,
            sync_error=error,
        )


# ---------------------------------------------------------------------------
# GoHighLevel helpers
# ---------------------------------------------------------------------------

def _push_to_gohighlevel(
    *,
    target_profile_id: int,
    outreach_profile_id: int,
    gohighlevel_location_id: str,
    payload: ContactPayload,
) -> Dict[str, Any]:
    with SyncSessionLocal() as db:
        account = crud_sync.get_gohighlevel_account_by_location_id(db, gohighlevel_location_id)
        if not account:
            raise GoHighLevelApiError(f"GoHighLevel account not found for location {gohighlevel_location_id}")

        tokens = crud_sync.deserialize_gohighlevel_tokens(account)
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")

        if not refresh_token:
            raise GoHighLevelAuthError("Missing GoHighLevel refresh token")

        service = GoHighLevelService()
        if _token_expired(account.expires_at) or not access_token:
            access_token, refresh_token, expires_at = _refresh_tokens(service, refresh_token)
            crud_sync.update_gohighlevel_tokens(
                db,
                account_id=account.id,
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )

        ghl_payload = _build_ghl_payload(
            db=db,
            target_profile_id=target_profile_id,
            outreach_profile_id=outreach_profile_id,
            contact_payload=payload,
        )

        if not ghl_payload:
            logger.warning(
                "Skipping GoHighLevel sync for target_profile_id=%s due to empty payload",
                target_profile_id,
            )
            crud_sync.update_contact_sync_status(
                db,
                target_profile_id=target_profile_id,
                sync_status=STATUS_SYNC_FAILED,
                sync_error="Empty payload for GoHighLevel",
            )
            return {}

        if not ghl_payload:
            raise GoHighLevelApiError("Empty payload for GoHighLevel")

        logger.info(
            "GoHighLevel upsert context: account_id=%s location_id=%s target_profile_id=%s outreach_profile_id=%s",
            account.id,
            account.location_id,
            target_profile_id,
            outreach_profile_id,
        )
        logger.info(
            "GoHighLevel upsert payload: %s",
            json.dumps(_payload_for_logging(ghl_payload), ensure_ascii=False),
        )

    return service.upsert_contact(
        location_id=account.location_id,
        access_token=access_token,
        payload=ghl_payload,
    )


def _build_ghl_payload(
    *,
    db,
    target_profile_id: int,
    outreach_profile_id: int,
    contact_payload: ContactPayload,
) -> Dict[str, Any]:
    target_profile = crud_sync.get_target_profile_by_id(db, target_profile_id)
    normalized = contact_payload.normalized or {}

    first_name, last_name = _split_name_components(target_profile)
    full_name = " ".join(part for part in (first_name, last_name) if part)

    primary_phone = None
    if contact_payload.phones:
        first = contact_payload.phones[0]
        primary_phone = first.get("value") or first.get("raw")

    normalized_first, normalized_last, normalized_full = _normalized_name_components(normalized)
    first_name = first_name or normalized_first
    last_name = last_name or normalized_last
    full_name = full_name or normalized_full

    slug_name = _name_from_profile_url(getattr(target_profile, "profile_url", None))
    if not full_name and slug_name:
        full_name = slug_name
    if not first_name and slug_name:
        first_name = slug_name.split(" ", 1)[0]
    if not last_name and slug_name and " " in slug_name:
        last_name = slug_name.split(" ", 1)[1]

    payload: Dict[str, Any] = {}

    if full_name:
        payload["name"] = full_name
    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name
    if contact_payload.primary_email:
        payload["email"] = contact_payload.primary_email
    if primary_phone:
        payload["phone"] = primary_phone

    address_fields = _address_components(normalized, target_profile)
    if address_fields.get("address1"):
        payload["address1"] = address_fields["address1"]

    linkedin_url = getattr(target_profile, "profile_url", None) if target_profile else None
    company_name = getattr(target_profile, "title", None) if target_profile else None
    if linkedin_url or company_name:
        if linkedin_url and company_name:
            payload["website"] = f"{linkedin_url} | {company_name}"
        else:
            payload["website"] = linkedin_url or company_name

    if not payload.get("name") and first_name and last_name:
        payload["name"] = f"{first_name} {last_name}".strip()

    if not payload.get("name") and linkedin_url:
        payload["name"] = _name_from_profile_url(linkedin_url) or linkedin_url

    allowed_keys = {"name", "firstName", "lastName", "email", "phone", "address1", "website"}
    return {key: value for key, value in payload.items() if key in allowed_keys and value}


def _normalized_name_components(normalized: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not normalized:
        return None, None, None

    possible_full = (
        normalized.get("full_name")
        or normalized.get("fullName")
        or normalized.get("name")
        or normalized.get("profile_name")
    )
    first = normalized.get("first_name") or normalized.get("firstName")
    last = normalized.get("last_name") or normalized.get("lastName")

    if not first and possible_full:
        parts = possible_full.split(" ", 1)
        if parts:
            first = parts[0]
            if len(parts) > 1 and not last:
                last = parts[1]

    if not last and possible_full and " " in possible_full:
        last = possible_full.split(" ", 1)[1]

    return first, last, possible_full


POSTAL_CODE_REGEX = re.compile(
    r"(?P<postal>(?:\d{4,10}|[A-Za-z]\d[A-Za-z]\s?\d[A-Za-z]\d)(?:-\d{4})?)$"
)


def _address_components(normalized: Dict[str, Any], target_profile: Optional[models.TargetLinkedInProfile]) -> Dict[str, Optional[str]]:
    components = {
        "address1": None,
        "city": None,
        "state": None,
        "postalCode": None,
        "country": None,
    }

    addresses = normalized.get("addresses") or []
    primary_address = addresses[0].get("value") if addresses else None
    parsed = _parse_address_text(primary_address)

    location_components = _location_components(getattr(target_profile, "location", None))

    for key in components:
        components[key] = parsed.get(key) or location_components.get(key)

    return components


def _parse_address_text(address_text: Optional[str]) -> Dict[str, Optional[str]]:
    components = {
        "address1": None,
        "city": None,
        "state": None,
        "postalCode": None,
        "country": None,
    }
    if not address_text:
        return components

    tokens = [token.strip() for token in re.split(r",|\n", address_text) if token.strip()]
    if not tokens:
        return components

    components["address1"] = tokens[0]
    if len(tokens) >= 2:
        components["city"] = tokens[1]
    if len(tokens) >= 3:
        state, postal = _split_state_postal(tokens[2])
        components["state"] = state
        components["postalCode"] = postal
    if len(tokens) >= 4:
        components["country"] = tokens[-1]

    if not components["country"] and len(tokens) >= 3:
        components["country"] = tokens[-1]
    return components


def _split_state_postal(text: str) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    match = POSTAL_CODE_REGEX.search(text.strip())
    postal = None
    state = text.strip()
    if match:
        postal = match.group("postal").strip()
        state = text[: match.start()].strip(", ")
    return state or None, postal


def _location_components(location_text: Optional[str]) -> Dict[str, Optional[str]]:
    components = {
        "address1": None,
        "city": None,
        "state": None,
        "postalCode": None,
        "country": None,
    }
    if not location_text:
        return components

    tokens = [token.strip() for token in re.split(r",|\n", location_text) if token.strip()]
    if not tokens:
        return components
    if len(tokens) == 1:
        components["city"] = tokens[0]
    elif len(tokens) == 2:
        components["city"], components["country"] = tokens
    else:
        components["city"] = tokens[0]
        components["state"] = tokens[1]
        components["country"] = tokens[-1]
    return components


def _payload_for_logging(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Create a log-friendly snapshot of the payload (large fields redacted)."""
    safe: Dict[str, Any] = {}
    for key, value in payload.items():
        if key == "notes" and value is not None:
            text_value = str(value)
            safe[key] = f"<omitted length={len(text_value)} chars>"
        else:
            safe[key] = value
    return safe


def _refresh_tokens(
    service: GoHighLevelService, refresh_token: str
) -> Tuple[str, str, Optional[datetime]]:
    token_data = service.refresh_access_token_sync(refresh_token)
    access_token = token_data.get("access_token")
    new_refresh = token_data.get("refresh_token") or refresh_token
    expires_at_iso = token_data.get("expires_at")
    expires_at = _parse_datetime(expires_at_iso) if expires_at_iso else None
    if not access_token:
        raise GoHighLevelAuthError("GoHighLevel refresh did not return access token")
    return access_token, new_refresh, expires_at


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _token_expired(expires_at) -> bool:
    if not expires_at:
        return False
    if isinstance(expires_at, datetime):
        expiry = expires_at.astimezone(timezone.utc)
    else:
        expiry = _parse_datetime(str(expires_at))
        if expiry is None:
            return False
    return expiry <= datetime.now(timezone.utc)


def _parse_datetime(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _split_name_components(target_profile: Optional[models.TargetLinkedInProfile]) -> Tuple[Optional[str], Optional[str]]:
    if not target_profile:
        return None, None
    first = target_profile.name
    last = target_profile.lastname
    if first and not last and " " in first:
        parts = first.split(" ", 1)
        first, last = parts[0], parts[1]
    return first, last


def _first_email(normalized: Dict[str, Any]) -> Optional[str]:
    emails = normalized.get("emails") or []
    for entry in emails:
        candidate = entry.get("value") or entry.get("email") or entry.get("text")
        if candidate:
            return candidate
    return None


def _build_notes(normalized: Dict[str, Any], raw_sections: Any, profile_url: str) -> str:
    summary = {
        "linkedin_profile": profile_url,
        "normalized": normalized,
        "raw_sections": raw_sections,
    }
    try:
        return json.dumps(summary, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return f"LinkedIn Profile: {profile_url}\nData: {summary}"


def _default_tags() -> list[str]:
    tags = ["LinkedIn"]
    if LINKEDIN_CONTACT_SYNC_TAG:
        tags.append(LINKEDIN_CONTACT_SYNC_TAG)
    return tags


def _name_from_profile_url(profile_url: Optional[str]) -> Optional[str]:
    if not profile_url:
        return None
    slug = profile_url.rstrip("/").split("/")[-1]
    if not slug:
        return None
    cleaned = slug.replace("-", " ").replace("_", " ").strip()
    if not cleaned:
        return None
    return cleaned.title()


