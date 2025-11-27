"""
GoHighLevel service utilities.

Provides OAuth helpers (auth URL generation, token exchange, refresh) and
API helpers (contact upsert) with resilient error handling used by both
FastAPI routes and background tasks.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx

from app.config import gohighlevel_config
from app.errors import (
    GoHighLevelApiError,
    GoHighLevelAuthError,
    GoHighLevelConfigurationError,
    GoHighLevelRetryableError,
)

logger = logging.getLogger(__name__)

JSON_HEADERS = {"Content-Type": "application/json"}
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


class GoHighLevelService:
    """Wrapper around GoHighLevel OAuth + API endpoints."""

    def __init__(self, timeout: Optional[float] = None):
        self.config = gohighlevel_config
        if self.config is None:
            raise GoHighLevelConfigurationError("GoHighLevel configuration not loaded")
        self.timeout = timeout or self.config.api_timeout_seconds

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------
    def build_authorization_url(self, state: Optional[str] = None) -> str:
        """Construct the GoHighLevel OAuth authorization URL."""
        self.config.require_credentials()
        self.config.require_api_endpoints()

        params = {
            "response_type": "code",
            "redirect_uri": str(self.config.redirect_uri),
            "client_id": self.config.client_id,
        }
        if self.config.version_id:
            params["version_id"] = self.config.version_id
        if state:
            params["state"] = state

        encoded_params = httpx.QueryParams(params)
        scope = self._encode_scope(self.config.api_scopes or "")
        auth_base = str(self.config.auth_url)
        auth_url = f"{auth_base}?{encoded_params}&scope={scope}"
        logger.debug("Generated GoHighLevel auth URL (truncated): %s", auth_url[:120])
        return auth_url

    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access/refresh tokens."""
        payload = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(self.config.redirect_uri),
            "user_type": "Location",
        }
        return await self._post_token_payload(payload)

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh the access token asynchronously."""
        payload = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return await self._post_token_payload(payload)

    def refresh_access_token_sync(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh access token synchronously (for Celery tasks)."""
        payload = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return self._post_token_payload_sync(payload)

    # ------------------------------------------------------------------
    # Contacts API
    # ------------------------------------------------------------------
    def upsert_contact(
        self,
        *,
        location_id: str,
        access_token: str,
        payload: Dict[str, Any],
        max_attempts: int = 3,
        backoff_factor: float = 1.5,
    ) -> Dict[str, Any]:
        """
        Upsert a contact into the specified GoHighLevel location.

        Raises GoHighLevelAuthError on 401/403, GoHighLevelRetryableError on
        retry-eligible responses (5xx/429), and GoHighLevelApiError otherwise.
        """
        self.config.require_api_endpoints()

        base_url_value = self.config.api_base_url
        base_url = (str(base_url_value) if base_url_value else "").rstrip("/")
        url = f"{base_url}/contacts/upsert"
        version_header = self.config.api_version or "2021-07-28"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Version": version_header,
            **JSON_HEADERS,
        }
        request_payload = dict(payload or {})
        request_payload.setdefault("locationId", location_id)

        attempt = 0
        last_error: Optional[Exception] = None

        with httpx.Client(timeout=self.timeout) as client:
            while attempt < max_attempts:
                attempt += 1
                try:
                    response = client.post(url, headers=headers, json=request_payload)
                except httpx.RequestError as exc:
                    last_error = exc
                    logger.warning(
                        "GoHighLevel contact upsert request error: %s (attempt %s/%s)",
                        exc,
                        attempt,
                        max_attempts,
                    )
                    if attempt >= max_attempts:
                        raise GoHighLevelRetryableError("Upsert contact network failure") from exc
                    self._sleep_with_backoff(attempt, backoff_factor)
                    continue

                if response.status_code in (401, 403):
                    raise GoHighLevelAuthError(
                        "GoHighLevel access token rejected",
                        status_code=response.status_code,
                        details=_safe_json(response),
                    )

                if response.status_code in (429, 500, 502, 503, 504):
                    logger.warning(
                        "GoHighLevel upsert contact retry due to status %s (attempt %s/%s)",
                        response.status_code,
                        attempt,
                        max_attempts,
                    )
                    if attempt >= max_attempts:
                        raise GoHighLevelRetryableError(
                            f"GoHighLevel temporary failure (HTTP {response.status_code})",
                            status_code=response.status_code,
                            details=_safe_json(response),
                        )
                    self._sleep_with_backoff(attempt, backoff_factor)
                    continue

                if response.is_error:
                    raise GoHighLevelApiError(
                        f"GoHighLevel contact upsert failed (HTTP {response.status_code})",
                        status_code=response.status_code,
                        details=_safe_json(response),
                    )

                data = _safe_json(response)
                logger.debug("GoHighLevel upsert success: %s", data)
                return data

        raise GoHighLevelRetryableError("GoHighLevel contact upsert failed") from last_error

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _post_token_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.config.require_credentials()
        self.config.require_api_endpoints()

        token_url = str(self.config.token_url)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    token_url,
                    data=payload,
                    headers=FORM_HEADERS,
                )
            except httpx.RequestError as exc:
                raise GoHighLevelRetryableError("Token request failed") from exc

        return self._process_token_response(response)

    def _post_token_payload_sync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.config.require_credentials()
        self.config.require_api_endpoints()

        token_url = str(self.config.token_url)

        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.post(
                    token_url,
                    data=payload,
                    headers=FORM_HEADERS,
                )
            except httpx.RequestError as exc:
                raise GoHighLevelRetryableError("Token request failed") from exc

        return self._process_token_response(response)

    def _process_token_response(self, response: httpx.Response) -> Dict[str, Any]:
        if response.status_code in (401, 403):
            raise GoHighLevelAuthError(
                "GoHighLevel token request unauthorized",
                status_code=response.status_code,
                details=_safe_json(response),
            )

        if response.is_error:
            raise GoHighLevelApiError(
                f"GoHighLevel token request failed (HTTP {response.status_code})",
                status_code=response.status_code,
                details=_safe_json(response),
            )

        data = _safe_json(response)
        if "access_token" not in data:
            raise GoHighLevelApiError("Token response missing access_token")

        # Compute expiry timestamp if expires_in provided.
        expires_in = data.get("expires_in")
        if expires_in is not None:
            try:
                expires_int = int(expires_in)
                buffer_seconds = self.config.refresh_buffer_seconds
                data["expires_at"] = (
                    datetime.now(timezone.utc) + timedelta(seconds=max(expires_int - buffer_seconds, 0))
                ).isoformat()
            except (TypeError, ValueError):
                logger.warning("Unexpected expires_in value from GoHighLevel: %s", expires_in)
        return data

    @staticmethod
    def _encode_scope(raw_scope: str) -> str:
        if not raw_scope:
            return ""
        return raw_scope.replace(" ", "%20")

    @staticmethod
    def _sleep_with_backoff(attempt: int, backoff_factor: float) -> None:
        sleep_seconds = backoff_factor ** max(attempt - 1, 0)
        sleep_seconds = min(sleep_seconds, 30)
        logger.debug("Sleeping %.2fs before next GoHighLevel retry", sleep_seconds)
        time.sleep(sleep_seconds)


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"text": response.text}

