import requests
from typing import Optional, Dict, Any

from logger import logger
from settings import MAIN_BACKEND_URL


class VerificationAPI:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 15.0):
        root = (base_url or MAIN_BACKEND_URL).rstrip("/")
        self.base_url = f"{root}/internal/verification"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        logger.info(f"[VerificationAPI] Initialized with base_url={self.base_url}")

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        timeout = kwargs.pop("timeout", self.timeout)
        response = self.session.request(method, url, timeout=timeout, **kwargs)
        if response.status_code >= 400:
            logger.error(
                "[VerificationAPI] %s %s failed status=%s body=%s",
                method,
                url,
                response.status_code,
                response.text,
            )
        response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def create_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/requests", json=payload)

    def get_request(self, request_id: int) -> Dict[str, Any]:
        return self._request("GET", f"/requests/{request_id}")

    def get_latest_attempt(self, request_id: int) -> Optional[Dict[str, Any]]:
        data = self._request("GET", f"/requests/{request_id}/attempts/latest")
        return data or None

    def list_attempts(self, request_id: int) -> Dict[str, Any]:
        return self._request("GET", f"/requests/{request_id}/attempts")

    def update_status(self, request_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", f"/requests/{request_id}/status", json=payload)

    def update_attempt(self, attempt_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PATCH", f"/attempts/{attempt_id}", json=payload)




