import logging
import os

# Configure logging
log_level_name = os.getenv("LINKEDIN_SERVICE_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, log_level_name, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("linkedin_service")