import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import AsyncSessionLocal, SyncSessionLocal
from app.crud_async import (
    bulk_create_target_profiles,
    bulk_create_campaign_histories_with_steps,
    get_step_templates_by_id,
    get_required_variables_for_template,
    get_template_by_id,
)
from app.crud_sync import (
    get_campaign_lead_import_by_import_id,
    update_campaign_lead_import,
)
from app.services.service_manager import LinkedInMicroserviceService
from app.tasks.campaign_scheduler import run_campaign_with_scheduling
from app.utils.locks import profile_lock
from app.errors import LinkedIn2FARequired
from app.settings import (
    logger,
    LEAD_IMPORT_DEFAULT_MAX_RESULTS,
    LEAD_IMPORT_MAX_RESULTS_CAP,
)


@dataclass
class LeadImportRecord:
    id: int
    import_id: uuid.UUID
    user_id: int
    outreach_profile_id: int
    campaign_template_id: int
    search_url: str
    requested_lead_count: Optional[int]
    search_filters: Optional[Dict[str, Any]]


class LeadImportService:
    """
    Coordinates scraping LinkedIn search results, creating target profiles,
    and seeding campaign runs for imported leads.
    """

    def __init__(self, import_uuid: uuid.UUID, celery_task_id: Optional[str] = None):
        self.import_uuid = import_uuid
        self.celery_task_id = celery_task_id

    def execute(self) -> None:
        record = self._load_import_record()
        if not record:
            return

        total_extracted = 0
        total_imported = 0
        skipped_count = 0
        status = "failed"
        error_message: Optional[str] = None

        try:
            max_results = self._determine_max_results(record.requested_lead_count)
            logger.info(
                f"[LeadImport] Import {record.import_id} starting scrape "
                f"(outreach={record.outreach_profile_id}, template={record.campaign_template_id}, max_results={max_results})"
            )
            with profile_lock(record.outreach_profile_id):
                leads = self.scrape_leads(record.outreach_profile_id, record.search_url, max_results)
                total_extracted = len(leads)

                if total_extracted == 0:
                    status = "completed"
                    error_message = "LinkedIn search returned no leads."
                    logger.info(f"[LeadImport] No leads found for import {record.import_id}")
                else:
                    preparation = asyncio.run(self._prepare_campaign_async(record, leads))
                    prepared_leads: List[Dict[str, Any]] = preparation["prepared_leads"]
                    skipped = preparation["skipped"]
                    skipped_count = len(skipped)

                    if not prepared_leads:
                        status = "failed"
                        error_message = (
                            "All scraped leads were skipped due to missing required variables."
                            if skipped_count > 0
                            else "No valid leads found after preprocessing."
                        )
                        logger.warning(
                            f"[LeadImport] Import {record.import_id} yielded no usable leads "
                            f"(skipped={skipped_count})"
                        )
                    else:
                        payload = preparation["payload"]
                        step_templates_list = preparation["step_templates_list"]
                        run_campaign_with_scheduling.delay(payload, step_templates_list)

                        total_imported = len(prepared_leads)
                        if skipped_count > 0:
                            status = "partial"
                            error_message = (
                                f"Imported {total_imported} leads; skipped {skipped_count} missing required variables."
                            )
                        else:
                            status = "completed"
                        logger.info(
                            f"[LeadImport] Queued campaign run for import {record.import_id} "
                            f"({total_imported} leads, skipped={skipped_count})"
                        )

        except Exception as exc:  # pylint: disable=broad-except
            logger.exception(f"[LeadImport] Import {record.import_id} failed: {exc}")
            status = "failed"
            error_message = str(exc)
        finally:
            self._finalize_import(
                record=record,
                status=status,
                total_extracted=total_extracted,
                total_imported=total_imported,
                skipped=skipped_count,
                error=error_message,
            )

    def _load_import_record(self) -> Optional[LeadImportRecord]:
        with SyncSessionLocal() as db:
            import_obj = get_campaign_lead_import_by_import_id(db, self.import_uuid)
            if not import_obj:
                logger.error(f"[LeadImport] Import {self.import_uuid} not found.")
                return None

            import_obj = update_campaign_lead_import(
                db,
                import_obj,
                status="running",
                celery_task_id=self.celery_task_id,
                started=True,
                error=None,
            )

            return LeadImportRecord(
                id=import_obj.id,
                import_id=import_obj.import_id,
                user_id=import_obj.user_id,
                outreach_profile_id=import_obj.outreach_profile_id,
                campaign_template_id=import_obj.campaign_template_id,
                search_url=import_obj.search_url,
                requested_lead_count=import_obj.requested_lead_count,
                search_filters=import_obj.search_filters,
            )

    def _determine_max_results(self, requested: Optional[int]) -> int:
        if requested is None or requested <= 0:
            requested = LEAD_IMPORT_DEFAULT_MAX_RESULTS
        return max(1, min(requested, LEAD_IMPORT_MAX_RESULTS_CAP))

    @staticmethod
    def scrape_leads(
        outreach_profile_id: int,
        search_url: str,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        service = LinkedInMicroserviceService(outreach_profile_id)
        if not service.start():
            raise RuntimeError("Unable to initialize LinkedIn session for scraping.")

        try:
            response = service.scrape_search_results(search_url, max_results=max_results)
        except LinkedIn2FARequired:
            raise
        finally:
            service.close()

        status = response.get("status")
        if status == "success":
            return response.get("leads", []) or []
        if status == "captcha_required":
            raise RuntimeError("LinkedIn presented captcha; retry later or verify session.")
        if status == "auth_failed":
            raise RuntimeError("LinkedIn authentication failed for the outreach profile.")
        if status == "search_failed":
            raise RuntimeError(response.get("message") or "LinkedIn search failed.")

        raise RuntimeError(response.get("message") or "Unexpected error scraping LinkedIn search.")

    async def _prepare_campaign_async(
        self,
        record: LeadImportRecord,
        leads: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        async with AsyncSessionLocal() as db:
            campaign_template = await get_template_by_id(db, record.campaign_template_id)
            if not campaign_template:
                raise RuntimeError(f"Campaign template {record.campaign_template_id} not found.")

            step_templates = await get_step_templates_by_id(db, record.campaign_template_id)
            if not step_templates:
                raise RuntimeError("Campaign template has no steps defined.")

            required_vars = await get_required_variables_for_template(db, record.campaign_template_id) or []

            prepared_leads: List[Dict[str, Any]] = []
            skipped: List[Dict[str, Any]] = []

            for lead in leads:
                url = (lead.get("url") or "").strip()
                if not url:
                    skipped.append({"reason": "missing_url"})
                    continue

                variables = self.build_variables(lead)
                missing = [var for var in required_vars if var not in variables]
                if missing:
                    skipped.append({"url": url, "missing": missing})
                    continue

                prepared_leads.append(
                    {
                        "url": url,
                        "variables": variables,
                        "name": lead.get("name"),
                        "headline": lead.get("headline"),
                        "location": lead.get("location"),
                    }
                )

            if not prepared_leads:
                return {
                    "prepared_leads": [],
                    "skipped": skipped,
                    "payload": None,
                    "step_templates_list": [],
                }

            urls = [lead["url"] for lead in prepared_leads]
            target_profiles = await bulk_create_target_profiles(db, record.outreach_profile_id, urls)
            url_to_lead = {lead["url"]: lead for lead in prepared_leads}

            for profile in target_profiles:
                data = url_to_lead.get(profile.profile_url)
                if not data:
                    continue
                if data.get("name"):
                    profile.name = data["name"]
                if data.get("headline"):
                    profile.title = data["headline"]
                if data.get("location"):
                    profile.location = data["location"]
                profile.modified_at = datetime.now(timezone.utc)

            await db.commit()
            for profile in target_profiles:
                await db.refresh(profile)

            target_profile_ids = [profile.id for profile in target_profiles if profile.profile_url in url_to_lead]

            await bulk_create_campaign_histories_with_steps(
                db,
                record.user_id,
                record.outreach_profile_id,
                record.campaign_template_id,
                target_profile_ids,
                step_templates,
            )

            payload = {
                "campaign_template_id": record.campaign_template_id,
                "outreach_profile_id": record.outreach_profile_id,
                "target_profiles": [
                    {
                        "url": lead["url"],
                        "variables": lead["variables"],
                    }
                    for lead in prepared_leads
                ],
            }

            step_templates_list = [
                {
                    "id": step.id,
                    "campaign_template_id": step.campaign_template_id,
                    "step_number": step.step_number,
                    "action": step.action,
                    "additional_note_template": step.additional_note_template,
                    "delay_timestamp": step.delay_timestamp.total_seconds(),
                    "message_template": step.message_template,
                    "variables": step.variables,
                }
                for step in step_templates
            ]

            return {
                "prepared_leads": prepared_leads,
                "skipped": skipped,
                "payload": payload,
                "step_templates_list": step_templates_list,
            }

    @staticmethod
    def build_variables(lead: Dict[str, Any]) -> Dict[str, str]:
        name = lead.get("name") or ""
        headline = lead.get("headline")
        location = lead.get("location")
        first_name = name.split()[0] if name else None

        variables = {
            "profile_url": lead.get("url"),
            "name": name or None,
            "full_name": name or None,
            "first_name": first_name or None,
            "headline": headline or None,
            "location": location or None,
        }

        return {key: value for key, value in variables.items() if value}

    @staticmethod
    def format_lead_for_targets(lead: Dict[str, Any]) -> Dict[str, Any]:
        name = lead.get("name") or ""
        first_name = None
        last_name = None
        if name:
            parts = name.strip().split()
            if parts:
                first_name = parts[0]
                if len(parts) > 1:
                    last_name = " ".join(parts[1:])

        variables: Dict[str, str] = {}
        if first_name:
            variables["name"] = first_name
        if last_name:
            variables["last_name"] = last_name

        return {
            "url": lead.get("url"),
            "variables": variables,
        }

    @classmethod
    def preview_leads(
        cls,
        outreach_profile_id: int,
        search_url: str,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        max_count = max_results or LEAD_IMPORT_DEFAULT_MAX_RESULTS
        max_count = max(1, min(max_count, LEAD_IMPORT_MAX_RESULTS_CAP))
        leads = cls.scrape_leads(outreach_profile_id, search_url, max_count)
        return [
            cls.format_lead_for_targets(lead)
            for lead in leads
        ]

    def _finalize_import(
        self,
        record: LeadImportRecord,
        status: str,
        total_extracted: int,
        total_imported: int,
        skipped: int,
        error: Optional[str],
    ) -> None:
        with SyncSessionLocal() as db:
            import_obj = get_campaign_lead_import_by_import_id(db, record.import_id)
            if not import_obj:
                logger.error(f"[LeadImport] Unable to finalize import {record.import_id}; record missing.")
                return

            update_campaign_lead_import(
                db,
                import_obj,
                status=status,
                total_extracted=total_extracted,
                total_imported=total_imported,
                error=error,
                finished=True,
            )
            logger.info(
                f"[LeadImport] Import {record.import_id} finalized with status={status}, "
                f"extracted={total_extracted}, imported={total_imported}, skipped={skipped}"
            )

