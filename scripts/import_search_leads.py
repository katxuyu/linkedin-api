#!/usr/bin/env python3
"""
CLI utility to trigger LinkedIn search lead imports.

It mirrors the API behaviour by creating a campaign lead import record and either
submitting it to Celery or executing it synchronously via the shared service layer.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure project root is on sys.path so `app` package can be imported when the
# script is executed as `python scripts/import_search_leads.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import AsyncSessionLocal, SyncSessionLocal  # noqa: E402
from app.crud_async import (  # noqa: E402
    get_outreach_profile_by_id,
    get_template_by_id,
    get_step_templates_by_id,
    create_campaign_lead_import,
)
from app.crud_sync import get_campaign_lead_import_by_import_id  # noqa: E402
from app.services.lead_importer import LeadImportService  # noqa: E402
from app.services.service_manager import LinkedInMicroserviceService  # noqa: E402
from app.tasks.lead_importer import run_lead_import  # noqa: E402
from app.settings import (  # noqa: E402
    logger,
    LEAD_IMPORT_DEFAULT_MAX_RESULTS,
    LEAD_IMPORT_MAX_RESULTS_CAP,
)
from app.utils.locks import profile_lock  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import LinkedIn search leads into a campaign."
    )
    parser.add_argument(
        "--outreach-profile-id",
        type=int,
        required=True,
        help="Outreach profile ID that will execute the campaign.",
    )
    parser.add_argument(
        "--campaign-template-id",
        type=int,
        help="Campaign template ID to apply to imported leads (required unless --dry-run).",
    )
    parser.add_argument(
        "--search-url",
        required=True,
        help="LinkedIn search URL to scrape.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help=f"Maximum number of leads to import (cap: {LEAD_IMPORT_MAX_RESULTS_CAP}).",
    )
    parser.add_argument(
        "--filters",
        type=str,
        default=None,
        help="Optional JSON string describing search filters (stored with the import).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and preview leads without creating database records or scheduling campaigns.",
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Execute the import synchronously instead of queueing a Celery task.",
    )
    return parser.parse_args()


def _coerce_filters(raw_filters: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw_filters:
        return None
    try:
        return json.loads(raw_filters)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON for --filters: {exc}") from exc


async def _validate_resources(
    outreach_profile_id: int,
    campaign_template_id: Optional[int],
) -> None:
    async with AsyncSessionLocal() as db:
        outreach_profile = await get_outreach_profile_by_id(db, outreach_profile_id)
        if not outreach_profile:
            raise SystemExit(f"Outreach profile {outreach_profile_id} not found.")

        if campaign_template_id is None:
            return

        campaign_template = await get_template_by_id(db, campaign_template_id)
        if not campaign_template:
            raise SystemExit(f"Campaign template {campaign_template_id} not found.")

        step_templates = await get_step_templates_by_id(db, campaign_template_id)
        if not step_templates:
            raise SystemExit("Campaign template has no steps defined.")


async def _create_import_record(
    user_id: int,
    outreach_profile_id: int,
    campaign_template_id: int,
    search_url: str,
    max_results: Optional[int],
    search_filters: Optional[Dict[str, Any]],
):
    async with AsyncSessionLocal() as db:
        lead_import = await create_campaign_lead_import(
            db,
            user_id=user_id,
            outreach_profile_id=outreach_profile_id,
            campaign_template_id=campaign_template_id,
            search_url=search_url,
            requested_lead_count=max_results,
            search_filters=search_filters,
        )
        return lead_import


def _dry_run(outreach_profile_id: int, search_url: str, max_results: Optional[int]) -> None:
    """Run a scraping dry-run without database side-effects."""
    max_results = max_results or LEAD_IMPORT_DEFAULT_MAX_RESULTS
    max_results = min(max_results, LEAD_IMPORT_MAX_RESULTS_CAP)

    logger.info(
        f"[LeadImportCLI] Dry-run: scraping up to {max_results} leads for outreach profile {outreach_profile_id}"
    )

    with profile_lock(outreach_profile_id):
        service = LinkedInMicroserviceService(outreach_profile_id)
        if not service.start():
            raise SystemExit("Failed to initialise LinkedIn session. Is the microservice running?")
        try:
            result = service.scrape_search_results(search_url, max_results=max_results)
        finally:
            service.close()

    if result.get("status") != "success":
        error = result.get("error", "unknown_error")
        message = result.get("message", "")
        raise SystemExit(f"Dry-run failed: {error} {message}".strip())

    leads = result.get("leads", []) or []
    total = len(leads)
    print(f"Dry-run success. Found {total} lead(s).")
    preview_count = min(5, total)
    for lead in leads[:preview_count]:
        print(f"- {lead.get('name') or 'Unknown'} :: {lead.get('headline') or 'No headline'} :: {lead.get('url')}")
    if total > preview_count:
        print(f"... {total - preview_count} more leads not shown.")


def main() -> None:
    args = parse_args()

    if args.dry_run:
        if args.campaign_template_id is None:
            logger.info("Dry-run selected: campaign template validation skipped.")
        else:
            asyncio.run(
                _validate_resources(args.outreach_profile_id, args.campaign_template_id)
            )
        _dry_run(args.outreach_profile_id, args.search_url, args.max_results)
        return

    if args.campaign_template_id is None:
        raise SystemExit("--campaign-template-id is required unless --dry-run is provided.")

    asyncio.run(
        _validate_resources(args.outreach_profile_id, args.campaign_template_id)
    )

    # At the CLI layer we cannot infer the authenticated user, so we default to using
    # the outreach profile owner for the import user_id.
    # This keeps behaviour consistent with the API which enforces ownership.
    async def _resolve_user_id(outreach_profile_id: int) -> int:
        async with AsyncSessionLocal() as db:
            outreach_profile = await get_outreach_profile_by_id(db, outreach_profile_id)
            return outreach_profile.user_id

    user_id = asyncio.run(_resolve_user_id(args.outreach_profile_id))

    search_filters = _coerce_filters(args.filters)
    max_results = args.max_results
    if max_results:
        max_results = min(max_results, LEAD_IMPORT_MAX_RESULTS_CAP)

    lead_import = asyncio.run(
        _create_import_record(
            user_id=user_id,
            outreach_profile_id=args.outreach_profile_id,
            campaign_template_id=args.campaign_template_id,
            search_url=args.search_url,
            max_results=max_results,
            search_filters=search_filters,
        )
    )

    if args.run_now:
        logger.info(f"[LeadImportCLI] Running import {lead_import.import_id} synchronously.")
        service = LeadImportService(lead_import.import_id)
        service.execute()
        with SyncSessionLocal() as db:
            refreshed = get_campaign_lead_import_by_import_id(db, lead_import.import_id)
        if refreshed:
            print(f"Import {lead_import.import_id} completed with status={refreshed.status}")
        else:
            print(f"Import {lead_import.import_id} completed. Unable to load final status.")
        return

    logger.info(f"[LeadImportCLI] Queuing import {lead_import.import_id} via Celery.")
    run_lead_import.delay(str(lead_import.import_id))
    print(
        f"Queued lead import {lead_import.import_id}. "
        "Track progress via GET /campaigns/import-search/{import_id}."
    )


if __name__ == "__main__":
    main()

