"""
GoHighLevel configuration loader.

Provides a typed configuration object for GoHighLevel integrations,
including OAuth credentials, API endpoints, and runtime tuning options.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Dict, List, Optional

from pydantic import AnyHttpUrl, BaseModel, Field, HttpUrl, ValidationError

logger = logging.getLogger(__name__)


class GoHighLevelConfig(BaseModel):
    """
    Typed configuration for GoHighLevel integration.

    Individual components can inspect `configured` or call
    `require_credentials` / `require_api_endpoints` before performing
    sensitive operations.
    """

    client_id: Optional[str] = Field(default=None, alias="client_id")
    client_secret: Optional[str] = Field(default=None, alias="client_secret")
    redirect_uri: Optional[HttpUrl] = Field(default=None, alias="redirect_uri")

    auth_url: Optional[AnyHttpUrl] = Field(default=None, alias="auth_url")
    token_url: Optional[AnyHttpUrl] = Field(default=None, alias="token_url")
    api_base_url: Optional[AnyHttpUrl] = Field(default=None, alias="api_base_url")
    api_scopes: Optional[str] = Field(default=None, alias="api_scopes")
    api_version: Optional[str] = Field(default=None, alias="api_version")
    version_id: Optional[str] = Field(default=None, alias="version_id")

    # Operational settings
    api_timeout_seconds: int = Field(default=20, alias="api_timeout_seconds")
    refresh_buffer_seconds: int = Field(default=300, alias="refresh_buffer_seconds")
    contact_timeout_seconds: int = Field(default=30, alias="contact_timeout_seconds")

    # Optional observability / notifications
    slack_webhook_url: Optional[AnyHttpUrl] = Field(default=None, alias="slack_webhook_url")

    # Optional status endpoint tuning (mirrors reference implementation)
    status_rate_limit: Optional[int] = Field(default=None, alias="status_rate_limit")
    status_admin_rate_limit: Optional[int] = Field(default=None, alias="status_admin_rate_limit")
    status_rate_period_seconds: Optional[int] = Field(default=None, alias="status_rate_period_seconds")

    class Config:
        allow_population_by_field_name = True
        validate_assignment = True

    @property
    def configured(self) -> bool:
        """Return True when core OAuth credentials/endpoints are available."""
        return all(
            [
                self.client_id,
                self.client_secret,
                self.redirect_uri,
                self.auth_url,
                self.token_url,
                self.api_base_url,
            ]
        )

    @property
    def scopes(self) -> List[str]:
        """Return scopes split into a list, filtering empty tokens."""
        if not self.api_scopes:
            return []
        return [scope for scope in self.api_scopes.split() if scope]

    def require_credentials(self) -> None:
        """Raise ValueError if OAuth credentials are incomplete."""
        missing = [
            ("GHL_CLIENT_ID", self.client_id),
            ("GHL_CLIENT_SECRET", self.client_secret),
            ("GHL_REDIRECT_URI", self.redirect_uri),
        ]
        missing_keys = [key for key, value in missing if not value]
        if missing_keys:
            raise ValueError(
                f"Missing GoHighLevel OAuth credentials: {', '.join(missing_keys)}"
            )

    def require_api_endpoints(self) -> None:
        """Raise ValueError if API endpoints are incomplete."""
        missing = [
            ("GHL_AUTH_URL", self.auth_url),
            ("GHL_TOKEN_URL", self.token_url),
            ("GHL_API_BASE_URL", self.api_base_url),
        ]
        missing_keys = [key for key, value in missing if not value]
        if missing_keys:
            raise ValueError(
                f"Missing GoHighLevel API endpoints: {', '.join(missing_keys)}"
            )

    def as_dict(self) -> Dict[str, Optional[str]]:
        """Return a serialisable view for debugging."""
        return {
            "client_id": self.client_id,
            "redirect_uri": str(self.redirect_uri) if self.redirect_uri else None,
            "auth_url": str(self.auth_url) if self.auth_url else None,
            "token_url": str(self.token_url) if self.token_url else None,
            "api_base_url": str(self.api_base_url) if self.api_base_url else None,
            "api_scopes": self.api_scopes,
            "api_version": self.api_version,
            "configured": self.configured,
        }


def _load_from_env() -> GoHighLevelConfig:
    """Load GoHighLevel config from environment variables."""
    raw = {
        "client_id": os.getenv("GHL_CLIENT_ID"),
        "client_secret": os.getenv("GHL_CLIENT_SECRET"),
        "redirect_uri": os.getenv("GHL_REDIRECT_URI"),
        "auth_url": os.getenv("GHL_AUTH_URL"),
        "token_url": os.getenv("GHL_TOKEN_URL"),
        "api_base_url": os.getenv("GHL_API_BASE_URL"),
        "api_scopes": os.getenv("GHL_API_SCOPES"),
        "api_version": os.getenv("GHL_API_VERSION"),
        "version_id": os.getenv("GHL_VERSION_ID"),
        "api_timeout_seconds": _env_int("GHL_API_TIMEOUT_SECONDS", 20),
        "refresh_buffer_seconds": _env_int("GHL_REFRESH_BUFFER_SECONDS", 300),
        "contact_timeout_seconds": _env_int("GHL_CONTACT_TIMEOUT_SECONDS", 30),
        "slack_webhook_url": os.getenv("GHL_SLACK_WEBHOOK_URL"),
        "status_rate_limit": _maybe_int(os.getenv("GHL_STATUS_RATE_LIMIT")),
        "status_admin_rate_limit": _maybe_int(os.getenv("GHL_STATUS_ADMIN_RATE_LIMIT")),
        "status_rate_period_seconds": _maybe_int(os.getenv("GHL_STATUS_RATE_PERIOD_SECONDS")),
    }

    try:
        config = GoHighLevelConfig(**raw)
    except ValidationError as exc:
        logger.error("Failed to load GoHighLevel configuration: %s", exc)
        raise

    if not config.configured:
        missing_parts = [
            key for key, value in config.as_dict().items() if key != "configured" and value is None
        ]
        # Log once to aid deployment troubleshooting.
        if missing_parts:
            logger.warning(
                "GoHighLevel configuration incomplete; missing values: %s",
                ", ".join(sorted(missing_parts)),
            )

    return config


def _maybe_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid integer value for GoHighLevel setting: %s", value)
        return None


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        digits = "".join(ch for ch in value if ch.isdigit())
        if digits:
            logger.warning(
                "Trimming non-numeric characters from %s value '%s'. Parsed as %s.",
                key,
                value,
                digits,
            )
            return int(digits)
        logger.warning(
            "Invalid integer value for %s: '%s'. Falling back to default %s.",
            key,
            value,
            default,
        )
        return default


@lru_cache(maxsize=1)
def get_gohighlevel_config() -> GoHighLevelConfig:
    """
    Return the (cached) GoHighLevel configuration.

    The underlying configuration is loaded once to ensure consistent
    values across the application. Use `get_gohighlevel_config.cache_clear()`
    in tests when overriding environment variables.
    """

    config = _load_from_env()
    logger.debug("Loaded GoHighLevel configuration: %s", config.as_dict())
    return config

