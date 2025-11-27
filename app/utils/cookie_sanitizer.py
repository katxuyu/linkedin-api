from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

REQUIRED_FIELDS = ("name", "value", "domain", "path")
TRUTHY_VALUES = {"true", "1", "yes", "y"}
FALSY_VALUES = {"false", "0", "no", "n"}


def normalize_same_site(raw_value: Optional[str]) -> str:
    if not raw_value:
        return "Lax"
    lowered = raw_value.lower()
    if lowered in ("no_restriction", "none"):
        return "None"
    if lowered == "strict":
        return "Strict"
    return "Lax"


def coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in TRUTHY_VALUES:
            return True
        if lowered in FALSY_VALUES:
            return False
    try:
        numeric = int(value)
        return bool(numeric)
    except (TypeError, ValueError):
        return bool(value)


def sanitize_cookie(cookie: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cookie:
        return None
    if any(not cookie.get(field) for field in REQUIRED_FIELDS):
        return None
    sanitized: Dict[str, Any] = {
        "name": str(cookie["name"]),
        "value": str(cookie["value"]),
        "domain": str(cookie["domain"]),
        "path": str(cookie["path"]),
        "httpOnly": coerce_bool(cookie.get("httpOnly", False), False),
        "secure": coerce_bool(cookie.get("secure", True), True),
        "sameSite": normalize_same_site(cookie.get("sameSite")),
    }
    expires_value = cookie.get("expires") or cookie.get("expirationDate")
    if expires_value not in (None, ""):
        try:
            sanitized["expires"] = int(float(expires_value))
        except (TypeError, ValueError):
            pass
    return sanitized


def sanitize_cookies(cookies: Optional[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if cookies is None:
        return []
    sanitized_list: List[Dict[str, Any]] = []
    for cookie in cookies:
        sanitized_cookie = sanitize_cookie(cookie)
        if sanitized_cookie:
            sanitized_list.append(sanitized_cookie)
    return sanitized_list






