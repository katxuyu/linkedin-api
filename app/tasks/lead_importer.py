import uuid

from app.celery_app import celery_app
from app.services.lead_importer import LeadImportService
from app.settings import logger


@celery_app.task(name="app.tasks.lead_importer.run", bind=True)
def run_lead_import(self, import_id: str) -> None:
    """
    Celery task entry point to run a LinkedIn lead import.
    """
    try:
        import_uuid = uuid.UUID(import_id)
    except ValueError:
        logger.error(f"[LeadImportTask] Invalid import_id provided: {import_id}")
        return

    logger.info(f"[LeadImportTask] Starting lead import {import_uuid}")
    service = LeadImportService(import_uuid, celery_task_id=self.request.id)
    service.execute()

