# 🚀 LinkedIn Automation API

A powerful FastAPI-based backend for automating LinkedIn outreach campaigns, profile management, and messaging workflows. Built with browser automation (Playwright), async task processing (Celery), and AI-powered message generation.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.119.0-009688.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-8.2-DC382D.svg)](https://redis.io/)

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [API Documentation](#-api-documentation)
- [Campaign System](#-campaign-system)
- [LinkedIn Sessions & Authwall](#-linkedin-sessions--authwall)
- [Development](#-development)
- [Testing](#-testing)
- [Deployment](#-deployment)
- [Roadmap](#-roadmap)

---

## ✨ Features

### Core Functionality
- **🔐 User Management** - JWT-based authentication with admin/user roles
- **👤 Profile Management** - Multiple LinkedIn account management per user
- **🎯 Campaign Automation** - Multi-step outreach campaigns with templates
- **📊 Action Tracking** - Complete audit trail of all LinkedIn interactions
- **💬 Messaging** - Automated connection requests and direct messages
- **🤖 AI Integration** - OpenAI-powered message generation (coming soon)
- **🔄 Session Management** - Persistent LinkedIn sessions with cookie/token storage
- **⚡ Async Processing** - Celery-based background task queue
- **📈 Redis Caching** - Fast session and rate limit management
- **🛠 Ops Control Panel** - Streamlit dashboard for manual 2FA codes, error monitoring, and GHL sync status

### Campaign Features
- **Multi-step workflows** - Chain connection requests, follow-ups, messages
- **Variable templating** - Personalize messages with Jinja2 templates
- **Smart delays** - Human-like timing between actions
- **Connection monitoring** - Track pending/accepted connection requests
- **Error handling** - Automatic retry and failure tracking
- **Progress tracking** - Real-time campaign status updates

---

## 🏗 Architecture

```
┌─────────────┐
│   FastAPI   │ ◄──── HTTP Requests
│   Gateway   │
└──────┬──────┘
       │
       ├─────► PostgreSQL (User/Profile/Campaign Data)
       │
       ├─────► Redis (Sessions/Cache/Rate Limiting)
       │
       ├─────► Celery Workers
       │         │
       │         ├─► LinkedIn Service (Playwright)
       │         ├─► Campaign Orchestration
       │         └─► Connection Monitoring
       │
       └─────► Background Tasks
                 └─► Email Notifications (Gmail API)
```

### Project Structure

```
linkedin-api/
├── app/
│   ├── api/                          # FastAPI route handlers
│   │   ├── auth.py                   # Authentication endpoints
│   │   ├── admin.py                  # Admin-only endpoints
│   │   ├── profiles.py               # Profile management
│   │   └── campaigns.py              # Campaign endpoints
│   ├── services/                     # Business logic services
│   │   ├── linkedin_sync.py          # Playwright automation (sync)
│   │   ├── linkedin_async.py         # Playwright automation (async)
│   │   ├── session_manager_sync.py   # Session management (sync)
│   │   ├── session_manager_async.py  # Session management (async)
│   │   ├── chatbot.py                # AI chatbot integration
│   │   ├── proxy.py                  # Proxy rotation
│   │   └── captcha.py                # CAPTCHA solver (2Captcha)
│   ├── tasks/                        # Celery task definitions
│   │   └── campaign_tasks.py         # Campaign execution tasks
│   ├── models.py                     # SQLAlchemy ORM models
│   ├── schemas.py                    # Pydantic request/response schemas
│   ├── crud_sync.py                  # Sync CRUD operations
│   ├── crud_async.py                 # Async CRUD operations
│   ├── database.py                   # Database setup & connection pool
│   ├── dependencies.py               # FastAPI dependency injection
│   ├── settings.py                   # Configuration & environment
│   ├── main.py                       # Application entrypoint
│   ├── celery_app.py                 # Celery configuration
│   ├── redis.py                      # Redis client setup
│   ├── mail.py                       # Gmail API integration
│   ├── errors.py                     # Custom exceptions
│   ├── enums.py                      # Enumerations
│   └── utils.py                      # Helper utilities
├── nginx/                            # Nginx reverse proxy config
├── requirements.txt                  # Python dependencies
├── Dockerfile.dev                    # Development Dockerfile
├── Dockerfile.prod                   # Production Dockerfile
├── docker-compose.dev.yml            # Development compose
├── docker-compose.prod.yml           # Production compose
└── testing.ipynb                     # API testing notebook
```

---

## 🚀 Quick Start

### Prerequisites

- **Docker** 20.10+
- **Docker Compose** 2.0+
- **Python** 3.11+ (for local development)
- **Supabase** account (for PostgreSQL database)
- **Redis** 8.2 (included in Docker Compose)

### Docker Setup (Recommended)

1. **Clone the repository**
   ```bash
   git clone https://github.com/your-org/linkedin-api.git
   cd linkedin-api
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

   Required environment variables:
   ```env
   # Database (Supabase connection strings)
   # Get these from your Supabase project settings -> Database -> Connection string
   # Use "Session pooler" mode and select the appropriate driver
   DATABASE_URL_ASYNC=postgresql+asyncpg://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   DATABASE_URL_SYNC=postgresql+psycopg2://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
   
   # Redis
   REDIS_URL=redis://redis:6379
   
   # JWT
   JWT_SECRET=your-secret-key-here
   
   # Encryption
   FERNET_KEY=your-fernet-key-here
   
   # Admin
   DEFAULT_ADMIN_EMAIL=admin@admin.com
   DEFAULT_ADMIN_PASSWORD=ChangeMe123!

   # GoHighLevel OAuth (required for contact sync)
   GHL_CLIENT_ID=your-client-id
   GHL_CLIENT_SECRET=your-client-secret
GHL_REDIRECT_URI=https://your-domain-or-tunnel/gh/oauth/callback
   GHL_AUTH_URL=https://marketplace.gohighlevel.com/oauth/authorize
   GHL_TOKEN_URL=https://services.leadconnectorhq.com/oauth/token
   GHL_API_BASE_URL=https://services.leadconnectorhq.com
   GHL_API_SCOPES=contacts.readonly contacts.write offline_access
GHL_REFRESH_BUFFER_SECONDS=300
GHL_CONTACT_TIMEOUT_SECONDS=30
GHL_VERSION_ID=your-app-version-id
   GHL_SLACK_WEBHOOK_URL=https://hooks.slack.com/...
   
   # Optional: OpenAI
   OPENAI_API_KEY=sk-...
   
   # Optional: 2Captcha
   2CAPTCHA_API_KEY=your-2captcha-key

   # LinkedIn safety limits (per outreach profile per UTC day)
   LINKEDIN_MAX_CONNECTIONS_PER_DAY=20
   LINKEDIN_MAX_MESSAGES_PER_DAY=150
   LINKEDIN_MAX_TOTAL_ACTIONS_PER_DAY=250
   LINKEDIN_MAX_STEP_RETRIES=3
   TERMINATE_CAMPAIGN_ON_MAX_RETRIES=true
   ```

3. **Start services**
   ```bash
   docker compose -f docker-compose.dev.yml up --build
   ```

   Compose waits for Postgres/Redis to be healthy before booting API workers, Celery, and the LinkedIn microservice. Key endpoints:
   - **FastAPI / docs**: http://localhost:8000 and http://localhost:8000/docs
   - **LinkedIn microservice**: http://localhost:5001/health
   - **Flower (Celery Monitor)**: http://localhost:5555
   - **PostgreSQL**: localhost:5435
   - **Redis**: localhost:6380
   - **Streamlit Control Panel**: http://localhost:8501 (manual codes, errors, target status)

### Local Development Setup

1. **Create virtual environment**
   ```bash
   python -m venv linkedin-api-venv
   source linkedin-api-venv/bin/activate  # Linux/Mac
   # or
   linkedin-api-venv\Scripts\activate  # Windows
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Start services manually**
   ```bash
   # Terminal 1: Start PostgreSQL & Redis (via Docker)
   docker-compose -f docker-compose.dev.yml up postgres redis
   
   # Terminal 2: Start FastAPI
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
   
   # Terminal 3: Start Celery worker
   celery -A app.celery_app worker --loglevel=info
   
   # Terminal 4 (optional): Start Flower
   celery -A app.celery_app flower
   ```

---

## 📚 API Documentation

Interactive API documentation is available at `/docs` when the server is running.

### Authentication Flow

```python
import requests

BASE_URL = "http://localhost:8088"

# 1. Admin creates registration key
admin_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={"email": "admin@admin.com", "password": "ChangeMe123!"}
)
admin_token = admin_response.json()["access_token"]

reg_key_response = requests.post(
    f"{BASE_URL}/admin/registration-keys",
    headers={"Authorization": f"Bearer {admin_token}"}
)
registration_key = reg_key_response.json()["registration_key"]

# 2. User registers with key
requests.post(
    f"{BASE_URL}/auth/register",
    json={
        "email": "user@example.com",
        "password": "SecurePass123!",
        "registration_key": registration_key
    }
)

# 3. User logs in
login_response = requests.post(
    f"{BASE_URL}/auth/login",
    json={"email": "user@example.com", "password": "SecurePass123!"}
)
tokens = login_response.json()
access_token = tokens["access_token"]
```

### Core Endpoints

#### Authentication
- `POST /auth/register` - Register new user (requires registration key)
- `POST /auth/login` - Login and get JWT tokens
- `POST /auth/refresh` - Refresh access token
- `POST /auth/logout` - Logout user
- `POST /auth/password-reset/request` - Request password reset
- `POST /auth/password-reset/confirm` - Confirm password reset

#### Admin
- `POST /admin/registration-keys` - Generate registration key
- `GET /admin/users` - List all users
- `DELETE /admin/users/{user_id}` - Delete user
- `GET /admin/stats` - Get system statistics

#### Profiles
- `POST /profiles/outreach/register` - Add LinkedIn account
- `GET /profiles/outreach/list` - List your LinkedIn accounts
- `GET /profiles/outreach/find-by-email` - Find by email
- `POST /profiles/outreach/find-by-url` - Find by profile URL
- `PUT /profiles/outreach/update/url/{id}` - Update profile URL
- `PUT /profiles/outreach/update/email/{id}` - Update email
- `PUT /profiles/outreach/update/password/{id}` - Update password
- `POST /profiles/target/fetch-info` - Fetch target profile info
- `POST /profiles/target/connect` - Send connection request
- `POST /profiles/target/message` - Send direct message
- `GET /profiles/target/list` - List target profiles
- `GET /profiles/target/find-by-url` - Find target by URL

#### Campaigns
- `POST /campaigns/templates/create` - Create campaign template
- `GET /campaigns/templates/list` - List campaign templates
- `GET /campaigns/templates/{id}` - Get template details
- `DELETE /campaigns/templates/{id}` - Delete template
- `POST /campaigns/run` - Execute campaign
- `GET /campaigns/history` - View campaign history
- `GET /campaigns/history/{id}` - Get campaign details

---

## 🎯 Campaign System

### Campaign Workflow

```mermaid
graph LR
    A[Create Template] --> B[Define Steps]
    B --> C[Add Targets]
    C --> D[Run Campaign]
    D --> E[Monitor Progress]
    E --> F[Review Results]
```

### Creating a Campaign Template

Campaign templates define multi-step outreach workflows with personalized messages.

**Example: Simple Connection Request Campaign**

```python
import requests

BASE_URL = "http://localhost:8088"
headers = {"Authorization": "Bearer YOUR_ACCESS_TOKEN"}

# Create campaign template
template_payload = {
    "name": "Tech Recruiter Outreach",
    "description": "Connect with tech recruiters",
    "steps": [
        {
            "step_number": 1,
            "action": "send_connection",
            "additional_note_template": "Hi {{name}}, I noticed we're both in the {{industry}} space. Would love to connect!",
            "delay_timestamp": "0:00:00"  # Send immediately
        }
    ]
}

response = requests.post(
    f"{BASE_URL}/campaigns/templates/create",
    json=template_payload,
    headers=headers
)
template_id = response.json()["id"]
```

**Example: Multi-Step Follow-up Campaign**

```python
template_payload = {
    "name": "Sales Outreach with Follow-up",
    "description": "Initial connection + follow-up message",
    "steps": [
        {
            "step_number": 1,
            "action": "send_connection",
            "additional_note_template": "Hi {{first_name}}, I'd love to discuss how we can help {{company}}.",
            "delay_timestamp": "0:00:00"
        },
        {
            "step_number": 2,
            "action": "send_message",
            "message_template": "Thanks for connecting, {{first_name}}! I saw your post about {{topic}} - really insightful!",
            "delay_timestamp": "2d"  # Wait 2 days after step 1
        },
        {
            "step_number": 3,
            "action": "send_message",
            "message_template": "Hi {{first_name}}, following up on my previous message. Would you be open to a quick call?",
            "delay_timestamp": "3d"  # Wait 3 days after step 2
        }
    ]
}
```

### Running a Campaign

```python
# Full workflow example
BASE_URL = "http://localhost:8088"

# 1. Admin login and create registration key
admin_login = requests.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "admin@example.com",
        "password": "AdminPass123!"
    }
)
admin_token = admin_login.json()["access_token"]

reg_key_response = requests.post(
    f"{BASE_URL}/admin/registration-keys",
    headers={"Authorization": f"Bearer {admin_token}"}
)
registration_key = reg_key_response.json()["registration_key"]

# 2. Register new user
requests.post(
    f"{BASE_URL}/auth/register",
    json={
        "email": "john.doe@company.com",
        "password": "SecurePassword123!",
        "registration_key": registration_key
    }
)

# 3. User login
user_login = requests.post(
    f"{BASE_URL}/auth/login",
    json={
        "email": "john.doe@company.com",
        "password": "SecurePassword123!"
    }
)
access_token = user_login.json()["access_token"]
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

# 4. Register LinkedIn outreach profile
outreach_response = requests.post(
    f"{BASE_URL}/profiles/outreach/register",
    json={
        "linkedin_email": "john.doe.linkedin@gmail.com",
        "linkedin_password": "LinkedInPass123!",
        "linkedin_url": "https://www.linkedin.com/in/johndoe/"
    },
    headers=headers
)
outreach_profile_id = outreach_response.json()["id"]

# 5. Create campaign template
template_response = requests.post(
    f"{BASE_URL}/campaigns/templates/create",
    json={
        "name": "Developer Outreach Q1 2025",
        "description": "Reach out to senior developers",
        "steps": [
            {
                "step_number": 1,
                "action": "send_connection",
                "additional_note_template": "Hi {{name}}, impressed by your work at {{company}}!",
                "delay_timestamp": "0:00:00"
            }
        ]
    },
    headers=headers
)
campaign_template_id = template_response.json()["id"]

# 6. Run campaign with targets
campaign_run = requests.post(
    f"{BASE_URL}/campaigns/run",
    json={
        "campaign_template_id": campaign_template_id,
        "outreach_profile_id": outreach_profile_id,
        "target_profiles": [
            {
                "url": "https://www.linkedin.com/in/jane-smith/",
                "variables": {
                    "name": "Jane",
                    "company": "TechCorp"
                }
            },
            {
                "url": "https://www.linkedin.com/in/bob-johnson/",
                "variables": {
                    "name": "Bob",
                    "company": "StartupXYZ"
                }
            }
        ]
    },
    headers=headers
)

print(campaign_run.json())
# Output: {"status": "success", "message": "Campaign started"}
```

### Delay Timestamp Formats

The `delay_timestamp` field supports multiple formats:

```python
# Format 1: HH:MM:SS
"delay_timestamp": "01:30:00"  # 1 hour 30 minutes

# Format 2: HH:MM
"delay_timestamp": "00:45"  # 45 minutes

# Format 3: Duration string
"delay_timestamp": "2d5h30m"  # 2 days, 5 hours, 30 minutes
"delay_timestamp": "1h"        # 1 hour
"delay_timestamp": "30m"       # 30 minutes
"delay_timestamp": "2d"        # 2 days

# Format 4: Dictionary
"delay_timestamp": {"hours": 2, "minutes": 30, "seconds": 0}
```

### Daily Safety Limits

LinkedIn throttles accounts that blast too many invites or DMs in a short window (current public guidance is ~100 connection requests per week).  
Each outreach profile therefore gets per-day quotas enforced at the Celery worker level:

- `LINKEDIN_MAX_CONNECTIONS_PER_DAY` (default **20**) – connection invitations
- `LINKEDIN_MAX_MESSAGES_PER_DAY` (default **150**) – direct messages
- `LINKEDIN_MAX_TOTAL_ACTIONS_PER_DAY` (default **250**) – cap on *pending scheduled* actions per UTC day; new steps are automatically shifted to the next day when this bucket fills up.
- `LINKEDIN_MAX_STEP_RETRIES` (default **3**) – Celery retries per step (lock contention, rate-limit deferrals, etc.)
- `TERMINATE_CAMPAIGN_ON_MAX_RETRIES` (default **true**) – when `LINKEDIN_MAX_STEP_RETRIES` is exhausted, mark the campaign as failed and cancel remaining tasks

When a per-action limit is hit during execution, the affected campaign step is marked `rate_limited`, a `LinkedInScrapeEvent` is recorded, and the task automatically retries just after the next UTC midnight. Operators can review these events from the Streamlit “Ops Systems” tab or by querying `LinkedInScrapeEvent` with `event_type='rate_limit'`.

### Message Templates

Use Jinja2 syntax for variable substitution:

```python
# Template
"Hi {{first_name}}, I noticed you work at {{company}} as a {{title}}."

# Variables
{
    "first_name": "Sarah",
    "company": "Google",
    "title": "Senior Engineer"
}

# Result
"Hi Sarah, I noticed you work at Google as a Senior Engineer."
```

---

## 🔐 LinkedIn Sessions & Authwall

LinkedIn occasionally serves an “authwall” search page (only login prompts, no `/in/` profile links). When that happens, lead imports return zero targets even though the scraper is running. Keep sessions healthy by:

1. **Refreshing storage whenever you log in manually.** Run `npx playwright open --save-storage=linkedin_state.json https://www.linkedin.com/feed/`, solve any checkbox/image challenge, then store the JSON via `LinkedInSessionManager._save_session_to_store` (or upload it to the `linkedin-service` container).
2. **Watching the LinkedIn microservice logs.** If you see `LinkedIn search returned no people profiles` immediately after a redirect to `/uas/login`, the account hit the authwall—re-authenticate before rerunning imports.
3. **Enabling 2Captcha.** Set `TWOCAPTCHA_API_KEY` (or `2CAPTCHA_API_KEY`) so the login form automatically solves standard reCAPTCHA prompts. Full SMS/email checkpoints still require manual approval, but this prevents the basic captcha loop.

More troubleshooting details live in [`documentation/lead_import.md`](documentation/lead_import.md#authwall--login-troubleshooting).

---

## 🧩 Manual Verification & Control Panel

- **Verification tables**: `linkedin_login_code_requests`, `linkedin_verification_attempts`, and `linkedin_scrape_events` capture every pending code, operator submission, and timeout/reschedule event. They're created automatically in dev via `Base.metadata.create_all()` and managed in Supabase via Alembic migration `20251117_0002`.
- **Worker flow**: When LinkedIn forces a checkpoint, the Playwright microservice calls the internal `/internal/verification/*` APIs to open a pending request, polls for new attempts, and resumes the session once the correct code is provided (or times out). Redis locks (`login_code_lock:{outreach_profile_id}`) ensure only one pending request per seat.
- **Cleanup task**: Celery task `app.tasks.login_code_cleanup.expire_pending_requests` runs every 5 minutes to mark stale requests as `timed_out` and release locks automatically.
- **Streamlit dashboard**: `streamlit_app/main.py` surfaces three tabs—pending manual codes (with inline submission forms), error history, and target connection/sync status. The new compose service `streamlit` exposes the UI on [http://localhost:8501](http://localhost:8501). Operators can submit codes directly from the UI; it writes attempts via `LinkedInVerificationService` and blocks until the worker confirms success/failure.
- **Frontend 2FA Flow**: The Next.js frontend now includes a global 2FA modal that automatically appears when any LinkedIn operation requires verification. When the backend returns HTTP 428, the frontend intercepts it and displays a modal for code entry. Sessions remain alive for 30 minutes while users complete verification.

See [`documentation/LINKEDIN_VERIFICATION.md`](documentation/LINKEDIN_VERIFICATION.md) and [`documentation/2FA_FLOW_GUIDE.md`](documentation/2FA_FLOW_GUIDE.md) for complete walkthroughs.

---

## 🛠 Development

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Add new table"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest app/tests/test_campaigns.py

# Run with coverage
pytest --cov=app --cov-report=html
```

### Code Quality

```bash
# Format code
black app/

# Lint code
flake8 app/

# Type checking
mypy app/
```

### Debugging

Enable debug mode in `.env`:
```env
LOG_LEVEL=DEBUG
SQLALCHEMY_ECHO=true
```

View logs:
```bash
# API logs
docker-compose logs -f app

# Celery logs
docker-compose logs -f celery

# All logs
docker-compose logs -f
```

---

## 🧪 Testing

### Interactive API Testing

Use the included Jupyter notebook `testing.ipynb`:

```bash
jupyter notebook testing.ipynb
```

### Manual API Testing

```bash
# Health check
curl http://localhost:8088/health

# Login
curl -X POST http://localhost:8088/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@admin.com","password":"ChangeMe123!"}'
```

---

## 🚢 Deployment

### Production Deployment

1. **Update environment variables**
   ```bash
   # Set secure passwords
   vim .env.prod
   ```

2. **Build and start**
   ```bash
   docker-compose -f docker-compose.prod.yml up -d --build
   ```

3. **Setup reverse proxy** (Nginx included)
   ```nginx
   server {
       listen 80;
       server_name api.yourdomain.com;
       
       location / {
           proxy_pass http://localhost:8088;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

4. **Enable SSL** (with Let's Encrypt)
   ```bash
   certbot --nginx -d api.yourdomain.com
   ```

### GitHub Actions Deployment

This repository includes `.github/workflows/deploy.yml`, which runs a lightweight CI check and can redeploy `main` over SSH. To enable it:

1. Configure the following repository secrets (Settings → **Security** → **Secrets and variables** → **Actions**):
   - `SSH_HOST` – IP or hostname of the target server.
   - `SSH_USERNAME` – user with permission to pull the repo and restart services.
   - `SSH_KEY` – private SSH key for that user (paste the PEM contents).
   - `SSH_PORT` – optional, defaults to `22`.
   - `DEPLOY_PATH` – absolute path on the server where this repo is checked out (e.g. `/opt/likedin-api`).
2. Ensure the server already has the project cloned in `DEPLOY_PATH` and that `docker compose up -d --build` works locally (the workflow simply pulls and restarts).
3. Push to `main` (or trigger the workflow manually). The pipeline will:
   - Check out the code, install Python dependencies, and run `python -m compileall` for a basic syntax check.
   - If successful, connect to your server and execute:
     ```bash
     cd $DEPLOY_PATH
     git fetch origin main
     git checkout main
     git pull origin main
     docker compose pull
     docker compose up -d --build
     ```
   - Update the script in `deploy.yml` if your deployment process differs.

> **Note:** The action does not upload `.env` files or other secrets. Make sure they already exist on the server before enabling the workflow.

### Environment Configuration

**Development** (`.env.dev`):
- Debug logging
- Local database
- Exposed ports
- Browser visible (headless=False)

**Production** (`.env.prod`):
- Error-only logging
- External database
- Proxied ports
- Headless browser
- Rate limiting enabled

---

## 📈 Monitoring

### Celery Task Monitoring

Access Flower dashboard at http://localhost:5555

### Database Monitoring

```bash
# Connect to PostgreSQL
docker exec -it postgres psql -U postgres -d linkedin_db

# View active campaigns
SELECT * FROM campaign_history WHERE status = 'active';

# View recent actions
SELECT * FROM actions ORDER BY created_at DESC LIMIT 10;
```

### Redis Monitoring

```bash
# Connect to Redis
docker exec -it redis redis-cli

# View keys
KEYS *

# Check session
GET "session:user_123"
```

---

## 🗺 Roadmap

### Phase 1: Core Features ✅
- [x] User authentication & authorization
- [x] LinkedIn profile management
- [x] Basic outreach automation
- [x] Campaign system
- [x] Action tracking
- [x] Session management

### Phase 2: Enhanced Features 🚧
- [ ] AI-powered message generation (OpenAI)
- [ ] CAPTCHA solver integration (2Captcha)
- [ ] Webhook notifications
- [ ] Email notifications (Gmail API)
- [ ] Advanced analytics dashboard
- [ ] Campaign A/B testing

### Phase 3: Scale & Performance 📋
- [ ] Horizontal scaling support
- [ ] Multi-region deployment
- [ ] Advanced rate limiting
- [ ] Connection pooling optimization
- [ ] CDN integration for static assets

### Phase 4: Enterprise Features 📋
- [ ] SSO integration (SAML, OAuth)
- [ ] Team management
- [ ] Role-based access control (RBAC)
- [ ] Audit logs
- [ ] White-label support

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is proprietary and confidential.

---

## 📞 Support

For issues, questions, or feature requests:
- **Email**: support@yourdomain.com
- **Issues**: GitHub Issues
- **Documentation**: https://docs.yourdomain.com

---

## ⚠️ Disclaimer

This tool is for educational and legitimate business purposes only. Users are responsible for complying with LinkedIn's Terms of Service and applicable laws. The authors are not liable for misuse of this software.

**Use responsibly and ethically.**

---

**Made with ❤️ by Your Team**
