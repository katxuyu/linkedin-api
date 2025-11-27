from celery import Celery
from app.settings import REDIS_URL

celery_app = Celery(
    "linkedin_automation",
    broker=f"{REDIS_URL}",
    backend=f"{REDIS_URL}",  # Enable result backend for task scheduling
    include=[
        "app.tasks",
        "app.tasks.campaign_scheduler",
        "app.tasks.campaign_watchers",
        "app.tasks.lead_importer",
        "app.tasks.contact_sync",
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour timeout
    task_soft_time_limit=3000,  # 50 minutes soft timeout
    broker_connection_retry_on_startup=True,
    
    # Celery Beat configuration for scheduled tasks
    beat_scheduler="celery.beat.Scheduler",
    beat_schedule_filename="/tmp/celerybeat-schedule",
    
    # Result backend for tracking scheduled tasks
    result_backend=f"{REDIS_URL}",
    result_expires=86400,  # Results expire after 24 hours
    
    # IMPORTANT: Force all tasks to run in worker pool, not MainProcess
    # This is critical for Playwright sync API compatibility
    task_always_eager=False,  # Never run tasks synchronously in caller
    worker_prefetch_multiplier=1,  # Only fetch one task at a time per worker
    worker_max_tasks_per_child=1000,  # Restart workers after 1000 tasks to prevent memory leaks
    
    beat_schedule={
        "expire-login-code-requests": {
            "task": "app.tasks.login_code_cleanup.expire_pending_requests",
            "schedule": 300.0,  # every 5 minutes
        },
    },
)

celery_app.autodiscover_tasks(["app"])