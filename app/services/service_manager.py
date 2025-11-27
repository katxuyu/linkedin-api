"""
LinkedIn Session Manager for Microservice

This module manages LinkedIn sessions by communicating with the LinkedIn Flask microservice.
It replaces the direct LinkedIn service management.
"""

import json
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from fake_useragent import UserAgent
import requests

from app.services.linkedin_service_client import LinkedInMicroserviceClient
from app.redis import get_redis_sync
from app.database import SyncSessionLocal
from app.crud_sync import get_linkedin_session, save_linkedin_session, get_outreach_profile_by_id
from app.errors import (
    LinkedInServiceNotAvailable,
    LinkedInLoginFailed,
    DecryptionError,
    LinkedInSessionNotFound,
    LinkedIn2FARequired,
    LinkedInCheckpointRequired,
)
from app.settings import FERNET, COOKIES_EXPIRATION_TIME, logger
from app.utils.cookie_sanitizer import sanitize_cookies


class LinkedInSessionManager:
    """
    Manages LinkedIn sessions via the Flask microservice.
    """
    
    def __init__(self):
        """
        Initialize the session manager.
        """        
        logger.info(f"LinkedIn session manager initialized")
    
    @classmethod
    def _load_session_from_store(cls, email: str, outreach_profile_id: int):
        redis_client = get_redis_sync()
        cookies_key = f"cookies:{email}"
        ua_key = f"user_agent:{email}"

        cookies = user_agent = None

        # Try Redis first
        cookies_data = redis_client.get(cookies_key)
        ua_data = redis_client.get(ua_key)
        if cookies_data and ua_data:
            logger.info(f"Found session for {email} in Redis.")
            try:
                cookies_payload = json.loads(FERNET.decrypt(cookies_data).decode())
                sanitized_cookies = sanitize_cookies(cookies_payload)
                if not sanitized_cookies:
                    logger.warning(f"Sanitized Redis cookies empty for {email}")
                else:
                    cookies = sanitized_cookies
                    user_agent = json.loads(ua_data).get("user_agent")
                    logger.info(f"Restored session for {email} from Redis.")
            except Exception as e:
                logger.warning(f"Redis session decode failed for {email}: {e}")

        # Fallback to DB
        if not cookies or not user_agent:
            logger.info(f"No session found for {email} in Redis or DB, falling back to DB.")
            with SyncSessionLocal() as db:
                session = get_linkedin_session(db, outreach_profile_id)
            if session and session.cookies and session.user_agent:
                logger.info(f"Found session for {email} in DB.")
                decrypted_payload = json.loads(FERNET.decrypt(session.cookies.encode()).decode())
                sanitized_cookies = sanitize_cookies(decrypted_payload)
                if not sanitized_cookies:
                    logger.warning(f"Sanitized DB cookies empty for {email}")
                else:
                    cookies = sanitized_cookies
                    user_agent = session.user_agent
                    sanitized_json = json.dumps(sanitized_cookies)
                    encrypted_cookies = FERNET.encrypt(sanitized_json.encode())
                    redis_client.setex(cookies_key, COOKIES_EXPIRATION_TIME, encrypted_cookies)
                    redis_client.setex(ua_key, COOKIES_EXPIRATION_TIME, json.dumps({"user_agent": user_agent}))
                    logger.info(f"Restored session for {email} from DB.")
                    if decrypted_payload != sanitized_cookies:
                        cls._save_session_to_store(email, outreach_profile_id, sanitized_cookies, user_agent)

        if not user_agent:
            logger.info(f"No user agent found for {email}, generating new one.")
            ua = UserAgent()
            user_agent = ua.random
            # Retry until we get a desktop user agent
            while any(x in user_agent.lower() for x in ["mobile", "iphone", "ipad", "android"]):
                user_agent = ua.random
            logger.info(f"Generated new user agent for {email}: {user_agent}")

        redis_client.close()
        return cookies, user_agent

    @classmethod
    def _save_session_to_store(cls, email: str, outreach_profile_id: int, cookies, user_agent):
        redis_client = get_redis_sync()
        sanitized_cookies = sanitize_cookies(cookies)
        if not sanitized_cookies:
            logger.warning(f"Skipping session store for {email}: cookies empty after sanitization")
            redis_client.close()
            return
        cookies_json = json.dumps(sanitized_cookies)
        encrypted_cookies = FERNET.encrypt(cookies_json.encode())
        ua_json = json.dumps({"user_agent": user_agent})

        redis_client.setex(f"cookies:{email}", COOKIES_EXPIRATION_TIME, encrypted_cookies)
        redis_client.setex(f"user_agent:{email}", COOKIES_EXPIRATION_TIME, ua_json)

        with SyncSessionLocal() as db:
            save_linkedin_session(
                db=db,
                outreach_profile_id=outreach_profile_id,
                cookies=cookies_json,
                user_agent=user_agent,
            )
        redis_client.close()
        logger.info(f"Session stored for {email} in Redis & DB")

    def get_user_and_password(self, outreach_profile_id: int) -> tuple[str, str]:
        # Get profile data from database
        with SyncSessionLocal() as db:
            profile = get_outreach_profile_by_id(db, outreach_profile_id)
        if not profile:
            logger.error(f"Can't get user and password for outreach profile {outreach_profile_id} because it doesn't exist")
            return None, None
        # Decrypt password
        try:
            decrypted_password = FERNET.decrypt(profile.linkedin_password.encode()).decode()
        except Exception as e:
            raise DecryptionError(f"Failed to decrypt password for outreach profile {outreach_profile_id}: {e}")
        
        email = profile.linkedin_email
        password = decrypted_password
        return email, password


def open_manual_verification(
    outreach_profile_id: int,
    session_key: str,
    expires_at: str,
    pending_reason: str = "2FA code required",
    request_type: str = "profile_verification"
) -> Dict[str, Any]:
    """
    Centralized helper to create verification state and store session info.
    
    Args:
        outreach_profile_id: The outreach profile ID
        session_key: The microservice session key
        expires_at: ISO timestamp when the session expires
        pending_reason: Human-readable reason for the verification
        request_type: Type of verification request
        
    Returns:
        Dict with verification_request_id, session_key, expires_at for HTTP 428 response
    """
    from app.services.linkedin_verification import LinkedInVerificationService
    
    with SyncSessionLocal() as sync_db:
        verification_service = LinkedInVerificationService(sync_db)
        verification_state = verification_service.open_manual_verification_window(
            outreach_profile_id=outreach_profile_id,
            request_type=request_type,
            pending_reason=pending_reason,
            ttl_seconds=1800
        )
    
    redis = get_redis_sync()
    try:
        redis.setex(
            f"pending_2fa_session:{outreach_profile_id}",
            1800,
            json.dumps({
                "session_key": session_key,
                "expires_at": expires_at,
                "verification_request_id": verification_state.request_id
            })
        )
    finally:
        redis.close()
    
    return {
        "verification_request_id": verification_state.request_id,
        "session_key": session_key,
        "expires_at": expires_at,
        "profile_id": outreach_profile_id
    }


class LinkedInMicroserviceService:
    """
    Wrapper around the microservice client to provide a service-like interface.
    """
    
    def __init__(self, outreach_profile_id: int):
        """
        Initialize the microservice service.
        
        Args:
            client: Microservice client
            session_manager: Session manager
            outreach_profile_id: Outreach profile ID
        """
        self.client = LinkedInMicroserviceClient()
        self.session_manager = LinkedInSessionManager()
        self.outreach_profile_id = outreach_profile_id
        self.session_key = None
        self._logged_in = False

    def _extract_error_data(self, http_error: requests.exceptions.HTTPError) -> Optional[Dict[str, Any]]:
        """Best-effort extraction of JSON payload from HTTPError."""
        if hasattr(http_error, "error_data"):
            return getattr(http_error, "error_data")
        response = getattr(http_error, "response", None)
        if not response:
            return None
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError):
            try:
                if hasattr(response, "_content") and response._content:
                    return json.loads(response._content.decode("utf-8"))
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                return None
        return None
    
    def start(self) -> bool:
        """
        Start the Flask microservice session.
        
        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            result = self.client.create_session(self.outreach_profile_id)
            if result.get("status") == "success":
                self._logged_in = True
                self.session_key = result.get('session_key')
                logger.info(f"Flask session created with key {self.session_key}")
                return True
            else:
                logger.error(f"Failed to create Flask session: {result.get('error')}")
                return False
        except Exception as e:
            logger.error(f"Error during Flask session creation: {e}")
            return False
    
    def close(self):
        """Close the Flask microservice session."""
        try:
            result = self.client.logout_session(self.session_key)
            if result.get("status") == "success":
                self._logged_in = False
                logger.info(f"Flask session {self.session_key} closed successfully")
            else:
                logger.error(f"Failed to close Flask session {self.session_key}: {result.get('error')}")
        except Exception as e:
            logger.exception(f"Error closing Flask session {self.session_key}: {e}")
    
    def fetch_profile_info(self, profile_url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch LinkedIn profile information.
        
        Args:
            profile_url: LinkedIn profile URL
            
        Returns:
            Dict with profile information or None if failed
        """
        try:
            email, password = self.session_manager.get_user_and_password(self.outreach_profile_id)
            cookies, user_agent = self.session_manager._load_session_from_store(email, self.outreach_profile_id)
            result = self.client.fetch_profile(
                self.session_key,
                email,
                password,
                self.outreach_profile_id,
                profile_url,
                cookies,
                user_agent
            )
            if result.get("status") != "success":
                logger.error(f"Failed to fetch profile {profile_url}: {result.get('error')}")
                return None
            new_cookies = result.get("cookies")
            new_user_agent = result.get("user_agent")
            if new_cookies!=cookies or new_user_agent!=user_agent:
                self.session_manager._save_session_to_store(email, self.outreach_profile_id, new_cookies, new_user_agent)
            return result.get("profile_data")
        except requests.exceptions.HTTPError as e:
            logger.info(f"Caught HTTPError: status={e.response.status_code if e.response else None}, url={e.response.url if e.response else None}, error={str(e)}")
            error_data = self._extract_error_data(e)
            # Check if it's a 401 error - either from response or from error message
            is_401 = False
            if e.response and e.response.status_code == 401:
                is_401 = True
            elif "401" in str(e) or "2fa_required" in str(e).lower():
                # Fallback: check error message for 401 or 2fa_required
                is_401 = True
                logger.warning(f"HTTPError doesn't have response attached, but error message suggests 401: {str(e)}")
            
            if is_401:
                # Check if it's a 2FA error by checking the error message or response body
                is_2fa_error = False
                session_key = None
                expires_at = None
                
                # Now check if it's a 2FA error (any type: 2fa_required, 2fa_pin_required, 2fa_app_approval)
                error_type = None
                try:
                    error_type = error_data.get("error") if error_data else None
                    if error_type in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                        is_2fa_error = True
                        session_key = error_data.get("session_key")
                        expires_at = error_data.get("expires_at")
                        logger.info(f"2FA error parsed: type={error_type}, session_key={session_key}, expires_at={expires_at}")
                except (AttributeError, TypeError) as err:
                    logger.warning(f"Error accessing error_data: {err}")
                
                # If we still don't have error_data, check the error message string
                if not is_2fa_error:
                    error_msg = str(e)
                    if any(x in error_msg.lower() for x in ("2fa_required", "2fa_pin_required", "2fa_app_approval")):
                        is_2fa_error = True
                        error_type = next(
                            (
                                token
                                for token in ("2fa_app_approval", "2fa_pin_required", "2fa_required")
                                if token in error_msg.lower()
                            ),
                            "2fa_required",
                        )
                        logger.warning(f"2FA error detected in message but couldn't parse JSON response, error_msg={error_msg}")
                        # Try to extract session_key from the URL in the error message
                        import re
                        # The error message contains: "for url: http://linkedin-service:5001/session/18/profile/fetch"
                        url_match = re.search(r'/session/(\d+)/', error_msg)
                        if url_match:
                            session_key = url_match.group(1)
                            logger.info(f"Extracted session_key from error message URL: {session_key}")
                        # Also try to get from response.url if available
                        elif hasattr(e, 'response') and e.response and hasattr(e.response, 'url'):
                            url_match = re.search(r'/session/(\d+)/', e.response.url)
                            if url_match:
                                session_key = url_match.group(1)
                                logger.info(f"Extracted session_key from response.url: {session_key}")
                
                if is_2fa_error:
                    # If we don't have expires_at, set a default (30 minutes from now)
                    if not expires_at:
                        from datetime import datetime, timezone, timedelta
                        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=1800)).isoformat()
                        logger.info(f"Using default expires_at (30 minutes): {expires_at}")
                    logger.warning(f"2FA required for profile {profile_url}, session_key={session_key}, expires_at={expires_at}")
                    raise LinkedIn2FARequired(
                        message="2FA verification required",
                        session_key=session_key,
                        expires_at=expires_at,
                        twofa_type=error_type or "2fa_required",
                    )
            
            # Handle checkpoint/manual verification errors (non-401)
            checkpoint_error_type = None
            try:
                checkpoint_error_type = error_data.get("error") if error_data else None
            except AttributeError:
                checkpoint_error_type = None

            checkpoint_codes = ("checkpoint_action_required", "checkpoint_unknown")
            if checkpoint_error_type in checkpoint_codes:
                message = error_data.get("message") if error_data else "LinkedIn requires additional verification."
                checkpoint_context = error_data.get("checkpoint_context") if error_data else None
                raise LinkedInCheckpointRequired(
                    message=message or "LinkedIn requires additional verification.",
                    checkpoint_context=checkpoint_context,
                    error_type=checkpoint_error_type,
                )

            error_msg_lower = str(e).lower()
            if any(code in error_msg_lower for code in checkpoint_codes):
                raise LinkedInCheckpointRequired(
                    message="LinkedIn presented a checkpoint that requires manual action.",
                    checkpoint_context=None,
                    error_type="checkpoint_action_required" if "action_required" in error_msg_lower else "checkpoint_unknown",
                )

            logger.exception(f"Error fetching profile {profile_url}: {e}")
            return None
        except LinkedIn2FARequired:
            raise
        except LinkedInCheckpointRequired:
            raise
        except Exception as e:
            logger.exception(f"Error fetching profile {profile_url}: {e}")
            return None
    
    def fetch_contact_info(self, profile_url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch LinkedIn contact info details.
        """
        try:
            email, password = self.session_manager.get_user_and_password(self.outreach_profile_id)
            cookies, user_agent = self.session_manager._load_session_from_store(email, self.outreach_profile_id)
            result = self.client.fetch_contact_info(
                self.session_key,
                email,
                password,
                self.outreach_profile_id,
                profile_url,
                cookies,
                user_agent,
            )

            status = result.get("status")
            if status != "success":
                logger.warning(
                    "Failed to fetch contact info for %s: %s",
                    profile_url,
                    result.get("error") or status,
                )
                return result

            new_cookies = result.get("cookies")
            new_user_agent = result.get("user_agent")
            if new_cookies and new_user_agent and (new_cookies != cookies or new_user_agent != user_agent):
                self.session_manager._save_session_to_store(email, self.outreach_profile_id, new_cookies, new_user_agent)
            contact_info = result.get("contact_info") or {}
            return {"status": "success", "contact_info": contact_info}
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 401:
                try:
                    error_data = e.response.json()
                    error_type = error_data.get("error")
                    if error_type in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                        logger.warning(f"2FA required ({error_type}) for contact info {profile_url}")
                        raise LinkedIn2FARequired(
                            message=f"2FA verification required ({error_type})",
                            session_key=error_data.get("session_key"),
                            expires_at=error_data.get("expires_at"),
                            twofa_type=error_type or "2fa_pin_required",
                        )
                except (ValueError, KeyError) as json_err:
                    logger.error(f"Failed to parse 2FA response JSON: {json_err}")
                except LinkedIn2FARequired:
                    raise
            logger.exception(f"Error fetching contact info for {profile_url}: {e}")
            return {"status": "error", "error": str(e)}
        except LinkedIn2FARequired:
            raise
        except Exception as e:
            logger.exception(f"Error fetching contact info for {profile_url}: {e}")
            return {"status": "error", "error": str(e)}

    def send_connection_request(self, profile_url: str, additional_note: Optional[str] = None) -> Dict[str, Any]:
        """
        Send connection request to a LinkedIn profile.
        
        Args:
            profile_url: LinkedIn profile URL
            note: Optional note to include with connection request
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            email, password = self.session_manager.get_user_and_password(self.outreach_profile_id)
            cookies, user_agent = self.session_manager._load_session_from_store(email, self.outreach_profile_id)
            result = self.client.send_connection_request(
                self.session_key,
                email,
                password,
                self.outreach_profile_id,
                profile_url,
                additional_note,
                cookies,
                user_agent
            )
            if result.get("status") != "success":
                error_code = result.get("error") or "connection_request_failed"
                logger.error(f"Failed to send connection request to {profile_url}: {error_code}")
                return {"success": False, "error": error_code}
            new_cookies = result.get("cookies")
            new_user_agent = result.get("user_agent")
            if new_cookies!=cookies or new_user_agent!=user_agent:
                self.session_manager._save_session_to_store(email, self.outreach_profile_id, new_cookies, new_user_agent)
            return {"success": True}
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 401:
                try:
                    error_data = e.response.json()
                    error_type = error_data.get("error")
                    if error_type in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                        logger.warning(f"2FA required ({error_type}) for connection request {profile_url}")
                        raise LinkedIn2FARequired(
                            message=f"2FA verification required ({error_type})",
                            session_key=error_data.get("session_key"),
                            expires_at=error_data.get("expires_at"),
                            twofa_type=error_type or "2fa_pin_required",
                        )
                except (ValueError, KeyError) as json_err:
                    logger.error(f"Failed to parse 2FA response JSON: {json_err}")
                except LinkedIn2FARequired:
                    raise
            logger.exception(f"Error sending connection request to {profile_url}: {e}")
            return {"success": False, "error": "connection_request_failed"}
        except LinkedIn2FARequired:
            raise
        except Exception as e:
            logger.exception(f"Error sending connection request to {profile_url}: {e}")
            return {"success": False, "error": "connection_request_failed"}
    
    def send_message(self, profile_url: str, message: str) -> bool:
        """
        Send message to a LinkedIn profile.
        
        Args:
            profile_url: LinkedIn profile URL
            message: Message content
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            email, password = self.session_manager.get_user_and_password(self.outreach_profile_id)
            cookies, user_agent = self.session_manager._load_session_from_store(email, self.outreach_profile_id)
            result = self.client.send_message(
                self.session_key,
                email,
                password,
                self.outreach_profile_id,
                profile_url,
                message, 
                cookies, 
                user_agent
            )
            if result.get("status") != "success":
                logger.error(f"Failed to send message to {profile_url}: {result.get('error')}")
                return False
            new_cookies = result.get("cookies")
            new_user_agent = result.get("user_agent")
            if new_cookies!=cookies or new_user_agent!=user_agent:
                self.session_manager._save_session_to_store(email, self.outreach_profile_id, new_cookies, new_user_agent)
            return True
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 401:
                try:
                    error_data = e.response.json()
                    error_type = error_data.get("error")
                    if error_type in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                        logger.warning(f"2FA required ({error_type}) for send message {profile_url}")
                        raise LinkedIn2FARequired(
                            message=f"2FA verification required ({error_type})",
                            session_key=error_data.get("session_key"),
                            expires_at=error_data.get("expires_at"),
                            twofa_type=error_type or "2fa_pin_required",
                        )
                except (ValueError, KeyError) as json_err:
                    logger.error(f"Failed to parse 2FA response JSON: {json_err}")
                except LinkedIn2FARequired:
                    raise
            logger.exception(f"Error sending message to {profile_url}: {e}")
            return False
        except LinkedIn2FARequired:
            raise
        except Exception as e:
            logger.exception(f"Error sending message to {profile_url}: {e}")
            return False
    
    def get_all_messages_from_chat(self, profile_url: str) -> Optional[list]:
        """
        Get all messages from a chat.
        
        Args:
            profile_url: LinkedIn profile URL
            
        Returns:
            List of messages or None if failed
        """
        try:
            email, password = self.session_manager.get_user_and_password(self.outreach_profile_id)
            cookies, user_agent = self.session_manager._load_session_from_store(email, self.outreach_profile_id)
            result = self.client.get_messages(
                self.session_key,
                email,
                password,
                self.outreach_profile_id,
                profile_url,
                cookies,
                user_agent
            )
            if result.get("status") != "success":
                logger.error(f"Failed to get messages from {profile_url}: {result.get('error')}")
                return None
            new_cookies = result.get("cookies")
            new_user_agent = result.get("user_agent")
            if new_cookies!=cookies or new_user_agent!=user_agent:
                self.session_manager._save_session_to_store(email, self.outreach_profile_id, new_cookies, new_user_agent)
            return result.get("messages", [])
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 401:
                try:
                    error_data = e.response.json()
                    error_type = error_data.get("error")
                    if error_type in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                        logger.warning(f"2FA required ({error_type}) for get messages {profile_url}")
                        raise LinkedIn2FARequired(
                            message=f"2FA verification required ({error_type})",
                            session_key=error_data.get("session_key"),
                            expires_at=error_data.get("expires_at"),
                            twofa_type=error_type or "2fa_pin_required",
                        )
                except (ValueError, KeyError) as json_err:
                    logger.error(f"Failed to parse 2FA response JSON: {json_err}")
                except LinkedIn2FARequired:
                    raise
            logger.exception(f"Error getting messages from {profile_url}: {e}")
            return None
        except LinkedIn2FARequired:
            raise
        except Exception as e:
            logger.exception(f"Error getting messages from {profile_url}: {e}")
            return None

    def scrape_search_results(
        self,
        search_url: str,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        """
        Scrape LinkedIn search results for potential leads.

        Args:
            search_url: LinkedIn search URL.
            max_results: Maximum number of leads to retrieve.

        Returns:
            Dict response from microservice.
        """
        try:
            email, password = self.session_manager.get_user_and_password(self.outreach_profile_id)
            cookies, user_agent = self.session_manager._load_session_from_store(email, self.outreach_profile_id)
            result = self.client.scrape_search_results(
                self.session_key,
                email,
                password,
                self.outreach_profile_id,
                search_url,
                max_results,
                cookies,
                user_agent,
            )
            new_cookies = result.get("cookies")
            new_user_agent = result.get("user_agent")
            if new_cookies and new_user_agent and (new_cookies != cookies or new_user_agent != user_agent):
                self.session_manager._save_session_to_store(
                    email,
                    self.outreach_profile_id,
                    new_cookies,
                    new_user_agent,
                )
            return result
        except requests.exceptions.HTTPError as e:
            if e.response and e.response.status_code == 401:
                try:
                    error_data = e.response.json()
                    error_type = error_data.get("error")
                    if error_type in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                        logger.warning(f"2FA required ({error_type}) for scrape search {search_url}")
                        raise LinkedIn2FARequired(
                            message=f"2FA verification required ({error_type})",
                            session_key=error_data.get("session_key"),
                            expires_at=error_data.get("expires_at"),
                            twofa_type=error_type or "2fa_pin_required",
                        )
                except (ValueError, KeyError) as json_err:
                    logger.error(f"Failed to parse 2FA response JSON: {json_err}")
                except LinkedIn2FARequired:
                    raise
            logger.exception(f"Error scraping search results for {search_url}: {e}")
            return {
                "status": "error",
                "error": str(e),
            }
        except LinkedIn2FARequired:
            raise
        except Exception as exc:
            logger.exception(f"Error scraping search results for {search_url}: {exc}")
            return {
                "status": "error",
                "error": str(exc),
            }

    def submit_pin(self, pin: str, session_key: str) -> bool:
        """
        Submit a PIN/verification code for 2FA.
        
        Args:
            pin: The verification code to submit
            session_key: The session key for the pending 2FA session
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            result = self.client.submit_pin(session_key, pin)
            if result.get("status") == "success":
                new_cookies = result.get("cookies")
                new_user_agent = result.get("user_agent")
                if new_cookies and new_user_agent:
                    email, _ = self.session_manager.get_user_and_password(self.outreach_profile_id)
                    self.session_manager._save_session_to_store(
                        email,
                        self.outreach_profile_id,
                        new_cookies,
                        new_user_agent,
                    )
                return True
            return False
        except Exception as e:
            logger.exception(f"Error submitting PIN: {e}")
            return False
    
    def cancel_pending_session(self, session_key: str) -> bool:
        """
        Cancel a pending 2FA session.
        
        Args:
            session_key: The session key to cancel
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            result = self.client.cancel_session(session_key)
            return result.get("status") == "success"
        except Exception as e:
            logger.exception(f"Error cancelling session: {e}")
            return False