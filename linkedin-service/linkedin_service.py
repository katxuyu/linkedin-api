"""
LinkedIn Service Wrapper for Flask Microservice

This module wraps the existing LinkedInService to work with the Flask microservice.
It handles session management and provides a clean interface for the Flask API.
"""

from dataclasses import asdict
from typing import Dict, Any, Optional, List

from logger import logger
from linkedin_sync import (
    LinkedInService as BaseLinkedInService,
    LinkedInCaptchaError,
    LinkedInAuthError,
    LinkedInSearchError,
    LinkedInSearchEmptyError,
    LinkedInSearchLead,
)

class LinkedInService:
    """
    Wrapper around the existing LinkedInService for Flask microservice use.
    """
    
    def __init__(self, email: str, password: str, cookies=None, user_agent=None):
        """
        Initialize LinkedIn service.
        
        Args:
            email: LinkedIn email
            password: LinkedIn password
            cookies: Optional cookies for session restoration
            user_agent: Optional user agent string
        """
        self.email = email
        self.password = password
        self.cookies = cookies
        self.user_agent = user_agent
        self._outreach_profile_id = None  # Will be set later
        
        # Initialize the base service
        self._service = BaseLinkedInService(
            email=email,
            password=password,
            cookies=cookies,
            user_agent=user_agent
        )
        
        logger.info(f"LinkedIn service initialized for {email}")
    
    def set_outreach_profile_id(self, outreach_profile_id: int):
        """Set the outreach profile ID."""
        self._outreach_profile_id = outreach_profile_id
    
    def login(self) -> bool:
        """
        Login to the LinkedIn session.
        
        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            logger.info(f"Starting LinkedIn session for {self.email}")
            
            # Check if outreach_profile_id is set
            if self._outreach_profile_id is None:
                logger.error("Outreach profile ID not set")
                return False
            
            success = self._service.login(self._outreach_profile_id)
            
            if success:
                logger.info(f"LinkedIn session started successfully for {self.email}")
            else:
                logger.error(f"Failed to start LinkedIn session for {self.email}")
            
            return success
            
        except LinkedInAuthError:
            raise
        except Exception as e:
            logger.error(f"Error starting LinkedIn session for {self.email}: {e}")
            return False
    
    def close(self):
        """Close the LinkedIn session."""
        try:
            logger.info(f"Closing LinkedIn session for {self.email}")
            closed = self._service.close()
            if not closed:
                logger.error(f"Failed to close LinkedIn session for {self.email}")
                return False
            logger.info(f"LinkedIn session closed for {self.email}")
            return True
            
        except Exception as e:
            logger.exception(f"Error closing LinkedIn session for {self.email}: {e}")
            return False
    
    def fetch_profile_info(self, profile_url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch LinkedIn profile information.
        
        Args:
            profile_url: LinkedIn profile URL
            
        Returns:
            Dict with profile information or None if failed
        """
        try:
            logger.info(f"Fetching profile info for {profile_url}")
            profile_data = self._service.fetch_profile_info(profile_url)
            
            if profile_data:
                logger.info(f"Profile info fetched successfully for {profile_url}")
            else:
                logger.warning(f"Failed to fetch profile info for {profile_url}")
            
            return profile_data
            
        except LinkedInAuthError:
            raise
        except Exception as e:
            logger.error(f"Error fetching profile info for {profile_url}: {e}")
            return None

    def fetch_contact_info(self, profile_url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch LinkedIn contact info details.
        """
        try:
            logger.info(f"Fetching contact info for {profile_url}")
            info = self._service.fetch_contact_info(profile_url)
            if info:
                logger.info(f"Contact info fetched successfully for {profile_url}")
            else:
                logger.warning(f"No contact info found for {profile_url}")
            return info
        except Exception as e:
            logger.error(f"Error fetching contact info for {profile_url}: {e}")
            return None
    
    def send_connection_request(self, profile_url: str, note: str = '') -> bool:
        """
        Send connection request to a LinkedIn profile.
        
        Args:
            profile_url: LinkedIn profile URL
            note: Optional note to include with connection request
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Sending connection request to {profile_url}")
            success = self._service.send_connection_request(profile_url, note)
            
            if success:
                logger.info(f"Connection request sent successfully to {profile_url}")
            else:
                logger.warning(f"Failed to send connection request to {profile_url}")
            
            return success
            
        except LinkedInAuthError:
            raise
        except Exception as e:
            logger.error(f"Error sending connection request to {profile_url}: {e}")
            return False
    
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
            logger.info(f"Sending message to {profile_url}")
            success = self._service.send_message(profile_url, message)
            
            if success:
                logger.info(f"Message sent successfully to {profile_url}")
            else:
                logger.warning(f"Failed to send message to {profile_url}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error sending message to {profile_url}: {e}")
            return False
    
    def get_all_messages_from_chat(self, profile_url: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get all messages from a chat.
        
        Args:
            profile_url: LinkedIn profile URL
            
        Returns:
            List of messages or None if failed
        """
        try:
            logger.info(f"Getting messages from chat with {profile_url}")
            messages = self._service.get_all_messages_from_chat(profile_url)
            
            if messages is not False:
                logger.info(f"Retrieved {len(messages)} messages from {profile_url}")
            else:
                logger.warning(f"Failed to retrieve messages from {profile_url}")
            
            return messages
            
        except Exception as e:
            logger.error(f"Error retrieving messages from {profile_url}: {e}")
            return None
    
    def get_session_data(self) -> Optional[Dict[str, Any]]:
        """
        Get cookies and user agent for the current session.
        
        Returns:
            Dict with cookies and user agent or None if not available
        """
        try:
            session_data = self._service.get_session_data()
            return session_data
        except Exception as e:
            logger.error(f"Error getting session data: {e}")
            return None

    def get_last_connect_error(self) -> Optional[str]:
        if hasattr(self._service, "get_last_connect_error"):
            return self._service.get_last_connect_error()
        return None

    def get_last_checkpoint_context(self) -> Optional[Dict[str, Any]]:
        if hasattr(self._service, "get_last_checkpoint_context"):
            return self._service.get_last_checkpoint_context()
        return None

    def submit_pin(self, pin: str) -> bool:
        """
        Submit a PIN/verification code for 2FA.
        
        Args:
            pin: The verification code to submit
            
        Returns:
            bool: True if login successful after PIN submission, False otherwise
        """
        try:
            logger.info(f"Submitting PIN for {self.email}")
            success = self._service.submit_pin(pin)
            
            if success:
                logger.info(f"PIN submission successful for {self.email}")
            else:
                logger.warning(f"PIN submission failed for {self.email}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error submitting PIN for {self.email}: {e}")
            return False

    def check_app_approval_status(self) -> Dict[str, Any]:
        """
        Proxy the app-approval status check to the underlying service.

        Returns:
            Dict[str, Any]: Result describing current approval state.
        """
        if not hasattr(self._service, "check_app_approval_status"):
            raise AttributeError("Underlying service does not support app approval status checks")
        try:
            return self._service.check_app_approval_status()
        except Exception as exc:
            logger.error(f"Error checking app approval status for {self.email}: {exc}")
            raise

    def wait_for_app_approval(
        self,
        timeout_seconds: int = 60,
        poll_interval: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Block until the LinkedIn app approval flow finishes or times out.

        Args:
            timeout_seconds: Maximum time to wait.
            poll_interval: Delay between polls.

        Returns:
            Dict[str, Any]: Result containing approval status information.
        """
        if not hasattr(self._service, "wait_for_app_approval"):
            raise AttributeError("Underlying service does not support waiting for app approval")
        try:
            return self._service.wait_for_app_approval(
                timeout_seconds=timeout_seconds,
                poll_interval=poll_interval,
            )
        except Exception as exc:
            logger.error(f"Error while waiting for app approval for {self.email}: {exc}")
            raise

    def scrape_search_results(
        self,
        search_url: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Scrape LinkedIn search results for leads.

        Args:
            search_url: LinkedIn search URL.
            max_results: Maximum number of leads to retrieve.

        Returns:
            List of serialized lead dictionaries.
        """
        try:
            leads: List[LinkedInSearchLead] = self._service.scrape_search_results(
                search_url,
                max_results=max_results,
            )
            return [asdict(lead) for lead in leads]
        except LinkedInCaptchaError as exc:
            logger.warning(f"Captcha encountered while scraping search results: {exc}")
            raise
        except LinkedInAuthError as exc:
            logger.error(f"Authentication required for search scraping: {exc}")
            raise
        except LinkedInSearchEmptyError as exc:
            logger.info(f"Search returned no results: {exc}")
            raise
        except LinkedInSearchError as exc:
            logger.error(f"Search scraping failed: {exc}")
            raise
        except Exception as exc:
            logger.exception(f"Unexpected error during search scraping: {exc}")
            raise LinkedInSearchError(str(exc))
