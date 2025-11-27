"""
Configuration module for application-level settings.

Currently exposes the GoHighLevel config which is shared across the
OAuth router, service client, and background tasks.
"""

from .gohighlevel import get_gohighlevel_config

gohighlevel_config = get_gohighlevel_config()

__all__ = [
    "gohighlevel_config",
    "get_gohighlevel_config",
]



