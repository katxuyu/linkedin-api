import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import crud_async, database, schemas
from app.dependencies import get_current_user
from app.errors import (
    GoHighLevelApiError,
    GoHighLevelAuthError,
    GoHighLevelConfigurationError,
    GoHighLevelRetryableError,
)
from app.services.gohighlevel import GoHighLevelService
from app.settings import GOHIGHLEVEL_CONFIG, logger

router = APIRouter(prefix="/gh", tags=["GoHighLevel"])


@router.get("/auth", response_model=schemas.GoHighLevelAuthResponse)
async def ghl_auth(
    client_state: Optional[str] = Query(
        None,
        description="Optional opaque state passed back on callback",
    ),
    make_default: bool = Query(
        False,
        description="When true, sets the resulting GoHighLevel account as default",
    ),
    user: schemas.UserResponse = Depends(get_current_user),
):
    """
    Initiate GoHighLevel OAuth authentication for the current user.
    """
    if not GOHIGHLEVEL_CONFIG or not GOHIGHLEVEL_CONFIG.configured:
        logger.error("GoHighLevel OAuth attempted without configuration")
        raise HTTPException(status_code=500, detail="GoHighLevel OAuth not configured")

    payload: Dict[str, Any] = {"user_id": user.id, "make_default": make_default}
    if client_state:
        payload["client_state"] = client_state

    encoded_state = _encode_state(payload)

    try:
        service = GoHighLevelService()
        authorization_url = service.build_authorization_url(encoded_state)
    except GoHighLevelConfigurationError:
        logger.exception("GoHighLevel configuration invalid while building auth URL")
        raise HTTPException(status_code=500, detail="GoHighLevel OAuth misconfigured")

    return schemas.GoHighLevelAuthResponse(
        authorization_url=authorization_url,
        message="Visit the authorization URL to authenticate with GoHighLevel",
    )


@router.get("/oauth/callback")
async def ghl_callback(
    code: Optional[str] = Query(None, description="Authorization code"),
    error: Optional[str] = Query(None, description="Error returned by GoHighLevel"),
    state: Optional[str] = Query(None, description="Opaque state round-tripped from the auth request"),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Handle GoHighLevel OAuth callback.

    Exchanges the authorization code for tokens and persists them to the database.
    """
    if error:
        logger.warning("GoHighLevel callback error: %s", error)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth failed: {error}")

    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth failed: missing code")

    state_payload = _decode_state(state)
    user_id = state_payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth failed: missing user context")

    make_default = bool(state_payload.get("make_default"))
    client_state = state_payload.get("client_state")

    user = await crud_async.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth failed: user not found")

    return await _complete_oauth_exchange(
        db=db,
        user_id=user.id,
        code=code,
        make_default=make_default,
        client_state=client_state,
    )


@router.post(
    "/oauth/manual-exchange",
    response_model=schemas.GoHighLevelAuthCompleteResponse,
    status_code=status.HTTP_200_OK,
)
async def ghl_manual_exchange(
    payload: schemas.GoHighLevelManualExchangeRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Manually exchange a GoHighLevel authorization code for tokens.

    Useful when the redirect cannot reach the backend directly (e.g., manual ngrok workflow).
    """
    return await _complete_oauth_exchange(
        db=db,
        user_id=user.id,
        code=payload.code,
        make_default=payload.make_default,
        client_state=payload.client_state,
    )


@router.get("/accounts", response_model=list[schemas.GoHighLevelAccountListResponse])
async def list_gohighlevel_accounts(
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """List GoHighLevel accounts connected for the current user."""
    accounts = await crud_async.list_gohighlevel_accounts(db, user.id)
    return accounts


@router.get("/accounts/user/{user_id}", response_model=list[schemas.GoHighLevelAccountListResponse])
async def list_gohighlevel_accounts_for_user(
    user_id: int,
    current_user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """List GoHighLevel accounts for a specific user (admin only)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    
    # Verify the target user exists
    target_user = await crud_async.get_user_by_id(db, user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    accounts = await crud_async.list_gohighlevel_accounts(db, user_id)
    return accounts


@router.patch(
    "/accounts/{account_id}/default",
    response_model=schemas.GoHighLevelSetDefaultResponse,
    status_code=status.HTTP_200_OK,
)
async def set_default_gohighlevel_account(
    account_id: int,
    user: schemas.UserResponse = Depends(get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """Mark a GoHighLevel account as the default for the current user."""
    account = await crud_async.set_default_gohighlevel_account(db, user_id=user.id, account_id=account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GoHighLevel account not found")
    return account


@router.get("/status", response_model=schemas.GoHighLevelStatusResponse)
async def ghl_status():
    """Report GoHighLevel configuration status."""
    config = GOHIGHLEVEL_CONFIG
    if not config:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Configuration not loaded")

    details = schemas.GoHighLevelStatusDetails(
        configured=config.configured,
        client_id_set=bool(config.client_id),
        client_secret_set=bool(config.client_secret),
        redirect_uri_set=bool(config.redirect_uri),
    )
    status_value = "ok" if config.configured else "error"
    return schemas.GoHighLevelStatusResponse(status=status_value, ghl_integration=details)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _encode_state(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_state(state: Optional[str]) -> Dict[str, Any]:
    if not state:
        return {}
    try:
        padded_state = state + "=" * (-len(state) % 4)
        decoded = base64.urlsafe_b64decode(padded_state.encode("utf-8"))
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        logger.warning("Failed to decode GoHighLevel state payload: %s", state)
        return {}


def _parse_expires_at(expires_at: Optional[str], expires_in: Optional[Any]) -> Optional[datetime]:
    if expires_at:
        try:
            return datetime.fromisoformat(expires_at)
        except ValueError:
            logger.warning("Unable to parse expires_at value from GoHighLevel: %s", expires_at)

    if expires_in:
        try:
            expires_seconds = int(expires_in)
            return datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
        except (TypeError, ValueError):
            logger.warning("Unable to parse expires_in value from GoHighLevel: %s", expires_in)
    return None


async def _complete_oauth_exchange(
    *,
    db: AsyncSession,
    user_id: int,
    code: str,
    make_default: bool,
    client_state: Optional[str],
) -> Dict[str, Any]:
    service = GoHighLevelService()
    token_data = await _exchange_code_with_handling(service, code)

    location_id = token_data.get("locationId") or token_data.get("location_id")
    if not location_id:
        logger.error("GoHighLevel token response missing locationId: %s", token_data)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token exchange failed: missing locationId",
        )

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token or not refresh_token:
        logger.error("GoHighLevel token response missing tokens: %s", token_data)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Token exchange failed: missing tokens",
        )

    expires_at = _parse_expires_at(token_data.get("expires_at"), token_data.get("expires_in"))
    display_name = token_data.get("locationName") or token_data.get("location_name")

    metadata = {
        "scope": token_data.get("scope"),
        "token_type": token_data.get("token_type"),
        "location_name": display_name,
    }

    account = await crud_async.upsert_gohighlevel_account(
        db,
        user_id=user_id,
        location_id=location_id,
        display_name=display_name,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        metadata=metadata,
        force_default=make_default,
    )

    response_payload: Dict[str, Any] = {
        "status": "success",
        "account_id": account.id,
        "location_id": account.location_id,
        "is_default": account.is_default,
    }
    if client_state:
        response_payload["client_state"] = client_state
    return response_payload


async def _exchange_code_with_handling(service: GoHighLevelService, code: str) -> Dict[str, Any]:
    try:
        return await service.exchange_code_for_tokens(code)
    except GoHighLevelAuthError as exc:
        logger.exception("GoHighLevel token exchange unauthorized")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GoHighLevel rejected the authorization code",
        ) from exc
    except GoHighLevelRetryableError as exc:
        logger.exception("GoHighLevel token exchange temporary failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporary GoHighLevel failure during token exchange",
        ) from exc
    except GoHighLevelApiError as exc:
        logger.exception("GoHighLevel token exchange failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GoHighLevel token exchange failed",
        ) from exc

