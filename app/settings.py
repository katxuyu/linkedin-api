import os
import logging
from cryptography.fernet import Fernet
from passlib.context import CryptContext
from pathlib import Path
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
STRICT_LOCKS = os.getenv("STRICT_LOCKS", "true").lower() in ("1", "true", "yes")

DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@admin.com")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")

BASE_DIR = Path(__file__).resolve().parent

# JSON_FILES = Path(BASE_DIR / "json_files")
# JSON_FILES.mkdir(exist_ok=True)

SQLALCHEMY_DATABASE_URL_ASYNC = os.getenv("DATABASE_URL_ASYNC")
SQLALCHEMY_DATABASE_URL_SYNC = os.getenv("DATABASE_URL_SYNC")

# Fix Heroku-style postgres:// URLs (SQLAlchemy 1.4+ requires postgresql://)
if SQLALCHEMY_DATABASE_URL_ASYNC and SQLALCHEMY_DATABASE_URL_ASYNC.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL_ASYNC = SQLALCHEMY_DATABASE_URL_ASYNC.replace("postgres://", "postgresql+asyncpg://", 1)
if SQLALCHEMY_DATABASE_URL_SYNC and SQLALCHEMY_DATABASE_URL_SYNC.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL_SYNC = SQLALCHEMY_DATABASE_URL_SYNC.replace("postgres://", "postgresql+psycopg2://", 1)

SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"

FERNET_KEY = os.getenv("FERNET_KEY", Fernet.generate_key())
FERNET = Fernet(FERNET_KEY)

PWD_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIES_EXPIRATION_TIME = 365 * 24 * 60 * 60

ACCESS_TOKEN_EXPIRE_MINUTES = 120
REFRESH_TOKEN_EXPIRE_DAYS = 7
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 30

TWO_CAPTCHA_API_KEY = os.getenv("2CAPTCHA_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Celery settings
CELERY_WORKER_CHECK_INTERVAL = 300  # 5 minutes in seconds

# Watcher timing configuration
WATCHER_MIN_RUNTIME_SECONDS = int(
    os.getenv("WATCHER_MIN_RUNTIME_SECONDS", str(10 * 24 * 60 * 60))
)  # Default: 10 days
CONNECTION_WATCHER_MAX_WAIT_SECONDS = int(
    os.getenv("CONNECTION_WATCHER_MAX_WAIT_SECONDS", str(24 * 60 * 60))
)  # Default: 1 day

CONNECTION_WATCHER_CHECK_INTERVAL = int(
    os.getenv("CONNECTION_WATCHER_CHECK_INTERVAL", str(24 * 60 * 60))
)  # Default: check once per day

INCOMING_MESSAGE_WATCHER_MAX_WAIT_SECONDS = int(
    os.getenv(
        "INCOMING_MESSAGE_WATCHER_MAX_WAIT_SECONDS",
        str(WATCHER_MIN_RUNTIME_SECONDS),
    )
) 
INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL = int(
    os.getenv(
        "INCOMING_MESSAGE_WATCHER_CHECK_INTERVAL",
        str(CELERY_WORKER_CHECK_INTERVAL),
    )
)

# Rate limits & quotas
LINKEDIN_MAX_CONNECTIONS_PER_DAY = int(os.getenv("LINKEDIN_MAX_CONNECTIONS_PER_DAY", "20"))
LINKEDIN_MAX_MESSAGES_PER_DAY = int(os.getenv("LINKEDIN_MAX_MESSAGES_PER_DAY", "150"))
LINKEDIN_MAX_TOTAL_ACTIONS_PER_DAY = int(os.getenv("LINKEDIN_MAX_TOTAL_ACTIONS_PER_DAY", "250"))
LINKEDIN_MAX_STEP_RETRIES = int(os.getenv("LINKEDIN_MAX_STEP_RETRIES", "3"))
TERMINATE_CAMPAIGN_ON_MAX_RETRIES = os.getenv("TERMINATE_CAMPAIGN_ON_MAX_RETRIES", "true").lower() in ("1", "true", "yes")

# n8n webhook integration
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")  # Optional: for autonomous chat continuation

LINKEDIN_SERVICE_URL = os.getenv("LINKEDIN_SERVICE_URL", "http://localhost:5001")
SESSION_LOCK_TIMEOUT_SECONDS = int(os.getenv("SESSION_LOCK_TIMEOUT_SECONDS", "60"))
SESSION_LOCK_TTL_SECONDS = int(os.getenv("SESSION_LOCK_TTL_SECONDS", str(20 * 60)))  # 20 minutes
SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS = int(os.getenv("SESSION_LOCK_BLOCKING_TIMEOUT_SECONDS", str(180)))
LINKEDIN_CONTACT_SYNC_TAG = os.getenv("LINKEDIN_CONTACT_SYNC_TAG", "").strip()

# Lead import defaults
LEAD_IMPORT_DEFAULT_MAX_RESULTS = int(os.getenv("LEAD_IMPORT_DEFAULT_MAX_RESULTS", "100"))
LEAD_IMPORT_MAX_RESULTS_CAP = int(os.getenv("LEAD_IMPORT_MAX_RESULTS_CAP", "250"))

# GoHighLevel configuration
try:
    from app.config import gohighlevel_config as GOHIGHLEVEL_CONFIG
except Exception as exc:
    logger.error("Failed to load GoHighLevel configuration: %s", exc)
    GOHIGHLEVEL_CONFIG = None