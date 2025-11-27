#!/usr/bin/env python
"""
Manual DOM inspection helper for troubleshooting LinkedIn UI changes.

Usage example (inside the web container):
    python scripts/inspect_linkedin_dom.py \
        --outreach-email ronel.andrade.grajo@gmail.com \
        --target-url https://www.linkedin.com/in/idmtechnologies/ \
        --dump-html /tmp/idmtechnologies.html
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select  # noqa: E402

from app import models  # noqa: E402
from app.crud_sync import get_outreach_profile_by_id  # noqa: E402
from app.database import SyncSessionLocal  # noqa: E402
from app.services.service_manager import LinkedInSessionManager  # noqa: E402

# Allow importing the microservice LinkedInService implementation
LINKEDIN_SERVICE_PATH = Path(__file__).resolve().parents[1] / "linkedin-service"
if str(LINKEDIN_SERVICE_PATH) not in sys.path:
    sys.path.append(str(LINKEDIN_SERVICE_PATH))

from linkedin_sync import LinkedInService  # type: ignore  # noqa: E402


def _resolve_outreach_profile(
    outreach_id: Optional[int],
    outreach_email: Optional[str],
) -> Dict[str, Any]:
    with SyncSessionLocal() as db:
        profile = None
        if outreach_id:
            profile = get_outreach_profile_by_id(db, outreach_id)
        elif outreach_email:
            stmt = select(models.OutreachLinkedInProfile).filter(
                models.OutreachLinkedInProfile.linkedin_email == outreach_email
            )
            profile = db.execute(stmt).scalars().first()
        if not profile:
            raise RuntimeError("Outreach profile not found.")
        return {
            "id": profile.id,
            "email": profile.linkedin_email,
        }


def _describe_locators(page, selectors: List[str], limit: int = 3) -> List[Dict[str, Any]]:
    descriptions: List[Dict[str, Any]] = []
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue
        for index in range(min(count, limit)):
            handle = locator.nth(index)
            try:
                element = handle.element_handle()
            except Exception:
                element = None
            if not element:
                continue
            snapshot = page.evaluate(
                """(el) => ({
                    text: el.innerText,
                    ariaLabel: el.getAttribute('aria-label'),
                    tag: el.tagName,
                    classes: el.className,
                    visible: !!(el.offsetParent),
                })""",
                element,
            )
            snapshot.update({"selector": selector, "index": index})
            descriptions.append(snapshot)
    return descriptions


def inspect_dom(outreach_id: int, target_url: str, dump_html: Optional[Path] = None) -> Dict[str, Any]:
    session_manager = LinkedInSessionManager()
    email, password = session_manager.get_user_and_password(outreach_id)
    cookies, user_agent = session_manager._load_session_from_store(email, outreach_id)

    service = LinkedInService(email, password, cookies=cookies, user_agent=user_agent)
    try:
        if not service.login(outreach_id):
            raise RuntimeError("Unable to login with stored credentials.")
        page_handle = service.goto_profile(target_url)
        if not page_handle:
            raise RuntimeError(f"Failed to navigate to {target_url}.")
        service.human_delay(1, 2)
        service._detect_captcha_or_logout()

        page = service.page
        if dump_html:
            dump_html.write_text(page.content(), encoding="utf-8")

        selectors_message = [
            "button:has-text('Message')",
            "button:has-text('Messaggio')",
            "button:has-text('Invia messaggio')",
            "button[aria-label*='Message']",
            "button[aria-label*='Messaggio']",
            "button[aria-label*='Invia messaggio']",
            "a[aria-label*='Message']",
            "a[aria-label*='Messaggio']",
            "a[data-control-name*='message']",
            "a[href*='/messaging/']",
        ]
        selectors_connect = [
            "button:has-text('Connect')",
            "button:has-text('Collegati')",
            "button:has-text('Connetti')",
            "button[aria-label*='Invite to connect']",
            "button[aria-label*='Collegati']",
            "button[aria-label*='Connetti']",
            "button[data-control-name*='connect']",
        ]
        selectors_pending = [
            "button:has-text('Pending')",
            "button:has-text('In attesa')",
            "button:has-text('Richiesta inviata')",
            "button[aria-label*='Pending']",
            "button[aria-label*='In attesa']",
            "button[aria-label*='Richiesta inviata']",
        ]

        report = {
            "page_url": page.url,
            "page_title": page.title(),
            "message_buttons": _describe_locators(page, selectors_message),
            "connect_buttons": _describe_locators(page, selectors_connect),
            "pending_buttons": _describe_locators(page, selectors_pending),
            "timestamp": time.time(),
        }
        return report
    finally:
        try:
            service.close()
        except Exception:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect LinkedIn DOM for troubleshooting selectors.")
    parser.add_argument("--outreach-id", type=int, help="Outreach profile ID")
    parser.add_argument("--outreach-email", help="Outreach profile email")
    parser.add_argument("--target-url", required=True, help="LinkedIn profile URL to inspect")
    parser.add_argument("--dump-html", help="Optional path to store the full page HTML after loading the profile.")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.outreach_id and not args.outreach_email:
        raise SystemExit("Provide either --outreach-id or --outreach-email.")

    profile_meta = _resolve_outreach_profile(args.outreach_id, args.outreach_email)
    dump_path = Path(args.dump_html).resolve() if args.dump_html else None
    report = inspect_dom(profile_meta["id"], args.target_url, dump_path)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

