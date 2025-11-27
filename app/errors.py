from typing import Any, Optional


class ProfileNotFoundError(Exception):
    pass

class DecryptionError(Exception):
    pass

class TargetProfileInfoError(Exception):
    pass

class LinkedInServiceNotAvailable(Exception):
    pass

class LinkedInLoginFailed(Exception):
    pass

class LinkedInConnectionRequestFailed(Exception):
    pass

class LinkedInSessionNotFound(Exception):
    pass

class LinkedIn2FARequired(Exception):
    """
    Raised when LinkedIn requires an additional verification step.
    
    `twofa_type` can be:
      - '2fa_pin_required' (default): user must enter a PIN/code
      - '2fa_app_approval': user must approve on their authenticator app
      - '2fa_required': generic fallback used by older flows
    """
    def __init__(
        self,
        message: str,
        session_key: str = None,
        expires_at: str = None,
        twofa_type: str = "2fa_pin_required",
    ):
        super().__init__(message)
        self.session_key = session_key
        self.expires_at = expires_at
        self.twofa_type = twofa_type


class LinkedInCheckpointRequired(Exception):
    """
    Raised when LinkedIn presents a checkpoint that can't be completed
    automatically (e.g., document upload, identity quiz).
    """

    def __init__(
        self,
        message: str,
        *,
        checkpoint_context: Optional[dict] = None,
        error_type: str = "checkpoint_action_required",
    ):
        super().__init__(message)
        self.checkpoint_context = checkpoint_context or {}
        self.error_type = error_type


class GoHighLevelError(Exception):
    """Base exception for GoHighLevel integration issues."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class GoHighLevelConfigurationError(GoHighLevelError):
    """Raised when required configuration values are missing."""


class GoHighLevelApiError(GoHighLevelError):
    """Raised for non-retryable API errors."""


class GoHighLevelAuthError(GoHighLevelApiError):
    """Raised when GoHighLevel rejects the supplied credentials."""


class GoHighLevelRetryableError(GoHighLevelApiError):
    """Raised for retryable API errors (e.g., 429, 5xx)."""