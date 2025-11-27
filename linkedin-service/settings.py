from dotenv import load_dotenv
import os

load_dotenv()

LINKEDIN_SERVICE_PORT = int(os.getenv('LINKEDIN_SERVICE_PORT', 5001))
MAIN_BACKEND_URL = os.getenv('MAIN_BACKEND_URL', 'http://localhost:8000')
# How long to wait if a session is busy (blocks instead of 429)
LOCK_TIMEOUT_SECONDS = int(os.getenv("SESSION_LOCK_TIMEOUT_SECONDS", "60"))

TWO_CAPTCHA_API_KEY = os.getenv("TWOCAPTCHA_API_KEY") or os.getenv("2CAPTCHA_API_KEY")