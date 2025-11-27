"""
LinkedIn Microservice Client with retry/backoff.
"""

import requests
import json
import time
import random
from typing import Dict, Any, Optional
from app.settings import LINKEDIN_SERVICE_URL, logger

class LinkedInMicroserviceClient:
    # Timeouts for various Playwright operations
    PIN_SUBMIT_TIMEOUT = 60  # seconds - PIN submission with page interaction
    PROFILE_FETCH_TIMEOUT = 600  # seconds - includes browser launch, login, navigation
    SEND_MESSAGE_TIMEOUT = 90  # seconds - includes opening messenger, typing, sending
    DEFAULT_TIMEOUT = 30  # seconds for quick operations
    
    def __init__(self, base_url: Optional[str] = None, session: Optional[requests.Session] = None):
        self.base_url = (base_url or LINKEDIN_SERVICE_URL).rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ------------ internal ------------

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        max_attempts = int(kwargs.pop("max_attempts", 12))
        base_sleep = float(kwargs.pop("base_sleep", 0.75))
        max_sleep  = float(kwargs.pop("max_sleep", 3.0))
        timeout = kwargs.pop("timeout", self.DEFAULT_TIMEOUT)

        attempt = 0
        while True:
            attempt += 1
            resp = self.session.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code not in (429, 423, 503):
                return resp
            # Busy/unavailable: jittered exponential backoff
            sleep_s = min(max_sleep, base_sleep * (1.5 ** (attempt - 1))) + random.uniform(0, 0.5)
            logger.info(f"[LinkedInMicroserviceClient] {resp.status_code} {url} — attempt {attempt}/{max_attempts}, sleep {sleep_s:.2f}s")
            if attempt >= max_attempts:
                return resp
            time.sleep(sleep_s)
    
    def _normal_request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _raise_checkpoint_error(self, resp: requests.Response) -> None:
        """
        Raise an HTTPError with attached error_data when the microservice reports
        a checkpoint that cannot be automated.
        """
        if resp.status_code not in (409, 410, 423):
            return
        try:
            error_data = resp.json()
        except ValueError:
            return
        error_msg = error_data.get("error")
        if error_msg in ("checkpoint_action_required", "checkpoint_unknown"):
            error = requests.exceptions.HTTPError(
                f"{resp.status_code} Client Error: {error_msg} for url: {resp.url}",
                response=resp,
            )
            error.error_data = error_data
            raise error

    # ------------ sessions ------------

    def create_session(
        self,
        outreach_profile_id: int,
    ) -> Dict[str, Any]:
        payload = {
            "outreach_profile_id": outreach_profile_id, 
        }
        resp = self._request_with_retry("POST", f"{self.base_url}/session/create", data=json.dumps(payload))
        resp.raise_for_status()
        return resp.json()

    def logout_session(self, session_key: str) -> Dict[str, Any]:
        resp = self._request_with_retry("POST", f"{self.base_url}/session/{session_key}/logout")
        resp.raise_for_status()
        return resp.json()

    # ------------ actions ------------

    def fetch_profile(
        self,
        session_key: str,
        email: str,
        password: str,
        outreach_profile_id: int,
        target_profile_url: str,
        cookies: Optional[dict] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Fetch profile with longer timeout since it involves:
        - Browser launch (~5s)
        - LinkedIn navigation (~10s)
        - Login form submission (~10s)
        - Profile page load (~10-20s)
        - Possible 2FA checkpoint detection
        """
        payload = {
            "email": email,
            "password": password,
            "outreach_profile_id": outreach_profile_id,
            "target_profile_url": target_profile_url,
        }
        if cookies:
            payload["cookies"] = cookies
        if user_agent:
            payload["user_agent"] = user_agent
        resp = self._request_with_retry(
            "POST", 
            f"{self.base_url}/session/{session_key}/profile/fetch", 
            data=json.dumps(payload),
            timeout=self.PROFILE_FETCH_TIMEOUT,  # 120 seconds for full login flow
        )
        
        if resp.status_code == 401:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", "Unauthorized")
                # Handle all 2FA error types: 2fa_required, 2fa_pin_required, 2fa_app_approval
                if error_msg in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                    # Create HTTPError with response properly attached
                    # Use requests.HTTPError constructor that properly attaches response
                    error = requests.exceptions.HTTPError(
                        f"401 Client Error: {error_msg} for url: {resp.url}",
                        response=resp
                    )
                    # Ensure response is attached (requests library should do this, but be explicit)
                    if not hasattr(error, 'response') or error.response is None:
                        error.response = resp
                    # Attach the parsed error data to the exception for easy access
                    error.error_data = error_data
                    raise error
            except requests.exceptions.HTTPError:
                raise
            except (ValueError, KeyError):
                pass
        
        self._raise_checkpoint_error(resp)
        resp.raise_for_status()
        return resp.json()

    def fetch_contact_info(
        self,
        session_key: str,
        email: str,
        password: str,
        outreach_profile_id: int,
        target_profile_url: str,
        cookies: Optional[dict] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "email": email,
            "password": password,
            "outreach_profile_id": outreach_profile_id,
            "target_profile_url": target_profile_url,
        }
        if cookies:
            payload["cookies"] = cookies
        if user_agent:
            payload["user_agent"] = user_agent
        resp = self._request_with_retry(
            "POST",
            f"{self.base_url}/session/{session_key}/profile/contact-info",
            data=json.dumps(payload),
        )
        
        if resp.status_code == 401:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", "Unauthorized")
                # Handle all 2FA error types
                if error_msg in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                    error = requests.exceptions.HTTPError(f"401 Client Error: {error_msg} for url: {resp.url}", response=resp)
                    error.response = resp
                    error.error_data = error_data
                    raise error
            except requests.exceptions.HTTPError:
                raise
            except (ValueError, KeyError):
                pass
        
        self._raise_checkpoint_error(resp)
        resp.raise_for_status()
        return resp.json()

    def send_connection_request(
        self,
        session_key: str,
        email: str,
        password: str,
        outreach_profile_id: int,
        target_profile_url: str,
        additional_note: Optional[str] = None,
        cookies: Optional[dict] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        payload = {
            "email": email,
            "password": password,
            "outreach_profile_id": outreach_profile_id,
            "target_profile_url": target_profile_url,
        }
        if additional_note:
            payload["additional_note"] = additional_note
        if cookies:
            payload["cookies"] = cookies
        if user_agent:
            payload["user_agent"] = user_agent
        resp = self._request_with_retry("POST", f"{self.base_url}/session/{session_key}/connection", data=json.dumps(payload))
        
        if resp.status_code == 401:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", "Unauthorized")
                # Handle all 2FA error types
                if error_msg in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                    error = requests.exceptions.HTTPError(f"401 Client Error: {error_msg} for url: {resp.url}", response=resp)
                    error.response = resp
                    error.error_data = error_data
                    raise error
            except requests.exceptions.HTTPError:
                raise
            except (ValueError, KeyError):
                pass
        
        self._raise_checkpoint_error(resp)
        resp.raise_for_status()
        return resp.json()

    def send_message(
        self,
        session_key: str,
        email: str,
        password: str,
        outreach_profile_id: int,
        target_profile_url: str,
        message: str,
        cookies: Optional[dict] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        payload = {
            "email": email,
            "password": password,
            "outreach_profile_id": outreach_profile_id,
            "target_profile_url": target_profile_url,
            "message": message
        }
        if cookies:
            payload["cookies"] = cookies
        if user_agent:
            payload["user_agent"] = user_agent
        resp = self._request_with_retry(
            "POST", 
            f"{self.base_url}/session/{session_key}/messages/send", 
            data=json.dumps(payload),
            timeout=self.SEND_MESSAGE_TIMEOUT  # Use longer timeout for messaging
        )
        
        if resp.status_code == 401:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", "Unauthorized")
                # Handle all 2FA error types
                if error_msg in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                    error = requests.exceptions.HTTPError(f"401 Client Error: {error_msg} for url: {resp.url}", response=resp)
                    error.response = resp
                    error.error_data = error_data
                    raise error
            except requests.exceptions.HTTPError:
                raise
            except (ValueError, KeyError):
                pass
        
        self._raise_checkpoint_error(resp)
        resp.raise_for_status()
        return resp.json()

    def get_messages(
        self,
        session_key: str,
        email: str,
        password: str,
        outreach_profile_id: int,
        target_profile_url: str,
        cookies: Optional[dict] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        payload = {
            "email": email,
            "password": password,
            "outreach_profile_id": outreach_profile_id,
            "target_profile_url": target_profile_url,
        }
        if cookies:
            payload["cookies"] = cookies
        if user_agent:
            payload["user_agent"] = user_agent
        resp = self._request_with_retry(
            "POST", 
            f"{self.base_url}/session/{session_key}/messages/get", 
            data=json.dumps(payload),
            timeout=self.PROFILE_FETCH_TIMEOUT  # Use longer timeout for message retrieval
        )
        
        if resp.status_code == 401:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", "Unauthorized")
                # Handle all 2FA error types
                if error_msg in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                    error = requests.exceptions.HTTPError(f"401 Client Error: {error_msg} for url: {resp.url}", response=resp)
                    error.response = resp
                    error.error_data = error_data
                    raise error
            except requests.exceptions.HTTPError:
                raise
            except (ValueError, KeyError):
                pass
        
        self._raise_checkpoint_error(resp)
        resp.raise_for_status()
        return resp.json()

    def scrape_search_results(
        self,
        session_key: str,
        email: str,
        password: str,
        outreach_profile_id: int,
        search_url: str,
        max_results: int = 50,
        cookies: Optional[dict] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "email": email,
            "password": password,
            "outreach_profile_id": outreach_profile_id,
            "search_url": search_url,
            "max_results": max_results,
        }
        if cookies:
            payload["cookies"] = cookies
        if user_agent:
            payload["user_agent"] = user_agent
        resp = self._request_with_retry(
            "POST",
            f"{self.base_url}/session/{session_key}/search/scrape",
            data=json.dumps(payload),
        )
        
        if resp.status_code == 401:
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", "Unauthorized")
                # Handle all 2FA error types
                if error_msg in ("2fa_required", "2fa_pin_required", "2fa_app_approval"):
                    error = requests.exceptions.HTTPError(f"401 Client Error: {error_msg} for url: {resp.url}", response=resp)
                    error.response = resp
                    error.error_data = error_data
                    raise error
            except requests.exceptions.HTTPError:
                raise
            except (ValueError, KeyError):
                pass
        
        self._raise_checkpoint_error(resp)
        resp.raise_for_status()
        return resp.json()

    def submit_pin(
        self,
        session_key: str,
        pin: str,
    ) -> Dict[str, Any]:
        """Submit PIN with longer timeout since Playwright operations can take time."""
        payload = {
            "pin": pin,
        }
        resp = self._request_with_retry(
            "POST",
            f"{self.base_url}/session/{session_key}/pin/submit",
            data=json.dumps(payload),
            timeout=self.PIN_SUBMIT_TIMEOUT,  # Use longer timeout for PIN submission
        )
        resp.raise_for_status()
        return resp.json()
    
    def cancel_session(
        self,
        session_key: str,
    ) -> Dict[str, Any]:
        resp = self._request_with_retry(
            "POST",
            f"{self.base_url}/session/{session_key}/cancel",
        )
        resp.raise_for_status()
        return resp.json()

    def check_app_approval(
        self,
        session_key: str,
    ) -> Dict[str, Any]:
        """
        Check the status of a pending app approval (push notification 2FA).
        
        Returns:
            Dict with status: "approved" | "rejected" | "pending" | "expired" | "error"
        """
        resp = self._request_with_retry(
            "GET",
            f"{self.base_url}/session/{session_key}/app-approval/check",
            timeout=30,
        )
        # Don't raise for non-2xx - we want to handle different statuses
        return resp.json()
    
    def wait_for_app_approval(
        self,
        session_key: str,
        timeout_seconds: int = 60,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Wait for app approval with a timeout (blocking call).
        
        Args:
            session_key: The session key
            timeout_seconds: Max time to wait (max 120)
            poll_interval: Time between checks
            
        Returns:
            Dict with status: "approved" | "rejected" | "timeout" | "error"
        """
        payload = {
            "timeout_seconds": min(timeout_seconds, 120),
            "poll_interval": poll_interval,
        }
        resp = self._request_with_retry(
            "POST",
            f"{self.base_url}/session/{session_key}/app-approval/wait",
            data=json.dumps(payload),
            timeout=timeout_seconds + 30,  # Allow extra time for the request itself
        )
        return resp.json()


















# """
# LinkedIn Microservice Client

# This module provides a client interface for communicating with the LinkedIn Flask microservice.
# It replaces the direct LinkedIn service calls in the main backend.
# """

# import requests
# import json
# from typing import Dict, Any, Optional, List
# from datetime import datetime, timezone

# from app.settings import LINKEDIN_SERVICE_URL, logger

# class LinkedInMicroserviceClient:
#     """
#     Client for communicating with the LinkedIn Flask microservice.
#     """
    
#     def __init__(self, base_url: str = LINKEDIN_SERVICE_URL):
#         """
#         Initialize the microservice client.
        
#         Args:
#             base_url: Base URL of the LinkedIn microservice
#         """
#         self.base_url = base_url.rstrip('/')
#         self.session = requests.Session()
#         self.session.headers.update({
#             'Content-Type': 'application/json',
#             'Accept': 'application/json'
#         })
        
#         logger.info(f"LinkedIn microservice client initialized with base URL: {self.base_url}")
    
#     def health_check(self) -> Dict[str, Any]:
#         """
#         Check if the microservice is healthy.
        
#         Returns:
#             Dict with health status
#         """
#         try:
#             response = self.session.get(f"{self.base_url}/health")
#             response.raise_for_status()
#             return response.json()
#         except Exception as e:
#             logger.error(f"Health check failed: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def create_session(self, email: str, password: str, outreach_profile_id: int, 
#                       cookies: Optional[Dict] = None, user_agent: Optional[str] = None) -> Dict[str, Any]:
#         """
#         Create a new LinkedIn session.
        
#         Args:
#             email: LinkedIn email
#             password: LinkedIn password
#             outreach_profile_id: Outreach profile ID
#             cookies: Optional cookies for session restoration
#             user_agent: Optional user agent string
            
#         Returns:
#             Dict with session creation result
#         """
#         try:
#             payload = {
#                 "email": email,
#                 "password": password,
#                 "outreach_profile_id": outreach_profile_id,
#                 "cookies": cookies,
#                 "user_agent": user_agent
#             }
            
#             response = self.session.post(f"{self.base_url}/session/create", json=payload)
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to create session: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def login_session(self, session_key: str) -> Dict[str, Any]:
#         """
#         Login to LinkedIn for a specific session.
        
#         Args:
#             session_key: Session key
            
#         Returns:
#             Dict with login result
#         """
#         try:
#             response = self.session.post(f"{self.base_url}/session/{session_key}/login")
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to login session {session_key}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def logout_session(self, session_key: str) -> Dict[str, Any]:
#         """
#         Logout and close a LinkedIn session.
        
#         Args:
#             session_key: Session key
            
#         Returns:
#             Dict with logout result
#         """
#         try:
#             response = self.session.post(f"{self.base_url}/session/{session_key}/logout")
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to logout session {session_key}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def fetch_profile(self, session_key: str, profile_url: str) -> Dict[str, Any]:
#         """
#         Fetch LinkedIn profile information.
        
#         Args:
#             session_key: Session key
#             profile_url: LinkedIn profile URL
            
#         Returns:
#             Dict with profile data
#         """
#         try:
#             response = self.session.get(f"{self.base_url}/session/{session_key}/profile/{profile_url}")
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to fetch profile {profile_url}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def send_connection_request(self, session_key: str, profile_url: str, note: str = '') -> Dict[str, Any]:
#         """
#         Send connection request to a LinkedIn profile.
        
#         Args:
#             session_key: Session key
#             profile_url: LinkedIn profile URL
#             note: Optional note to include with connection request
            
#         Returns:
#             Dict with connection request result
#         """
#         try:
#             payload = {"note": note} if note else {}
#             response = self.session.post(f"{self.base_url}/session/{session_key}/connection/{profile_url}", json=payload)
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to send connection request to {profile_url}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def send_message(self, session_key: str, profile_url: str, message: str) -> Dict[str, Any]:
#         """
#         Send message to a LinkedIn profile.
        
#         Args:
#             session_key: Session key
#             profile_url: LinkedIn profile URL
#             message: Message content
            
#         Returns:
#             Dict with message sending result
#         """
#         try:
#             payload = {"message": message}
#             response = self.session.post(f"{self.base_url}/session/{session_key}/message/{profile_url}", json=payload)
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to send message to {profile_url}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def get_messages(self, session_key: str, profile_url: str) -> Dict[str, Any]:
#         """
#         Get all messages from a chat.
        
#         Args:
#             session_key: Session key
#             profile_url: LinkedIn profile URL
            
#         Returns:
#             Dict with messages
#         """
#         try:
#             response = self.session.get(f"{self.base_url}/session/{session_key}/messages/{profile_url}")
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to get messages from {profile_url}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def get_cookies(self, session_key: str) -> Dict[str, Any]:
#         """
#         Get cookies for a session.
        
#         Args:
#             session_key: Session key
            
#         Returns:
#             Dict with cookies
#         """
#         try:
#             response = self.session.get(f"{self.base_url}/session/{session_key}/cookies")
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to get cookies for session {session_key}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def get_user_agent(self, session_key: str) -> Dict[str, Any]:
#         """
#         Get user agent for a session.
        
#         Args:
#             session_key: Session key
            
#         Returns:
#             Dict with user agent
#         """
#         try:
#             response = self.session.get(f"{self.base_url}/session/{session_key}/user-agent")
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to get user agent for session {session_key}: {e}")
#             return {"status": "error", "error": str(e)}
    
#     def list_sessions(self) -> Dict[str, Any]:
#         """
#         List all active sessions.
        
#         Returns:
#             Dict with sessions list
#         """
#         try:
#             response = self.session.get(f"{self.base_url}/sessions")
#             response.raise_for_status()
#             return response.json()
            
#         except Exception as e:
#             logger.error(f"Failed to list sessions: {e}")
#             return {"status": "error", "error": str(e)}
