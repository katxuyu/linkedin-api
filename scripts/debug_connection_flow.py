#!/usr/bin/env python
"""
Manual harness for the connection-request workflow.

It mirrors the Celery `_execute_connection_request` steps:
1. Resolve an outreach seat (stored session or raw email/password)
2. Login through `LinkedInService`
3. Fetch profile info to decide whether the target is already connected / pending
4. Optionally send the connection request (with or without a note)
5. Confirm the resulting status and optionally dump HTML for offline inspection
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select

from app import models
from app.database import SyncSessionLocal
from app.services.service_manager import LinkedInSessionManager

import sys

LINKEDIN_SERVICE_PATH = Path(__file__).resolve().parents[1] / "linkedin-service"
if str(LINKEDIN_SERVICE_PATH) not in sys.path:
    sys.path.append(str(LINKEDIN_SERVICE_PATH))

from linkedin_sync import LinkedInService  # type: ignore  # noqa: E402


def _print_block(title: str, payload: Dict) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _load_cookie_payload(arg_value: str) -> List[dict]:
    data = json.loads(arg_value)
    if isinstance(data, dict):
        if "cookies" in data:
            return data["cookies"]
        raise SystemExit("Cookie JSON must be a list or an object containing 'cookies'.")
    if not isinstance(data, list):
        raise SystemExit("Cookie payload must decode to a list of Playwright cookies.")
    return data


def _resolve_session(args: argparse.Namespace) -> Tuple[str, str, List[dict], Optional[str], Optional[int]]:
    if args.email:
        if not args.password:
            raise SystemExit("--password is required when --email is provided.")
        cookies: List[dict] = []
        if args.cookies_json:
            cookies = _load_cookie_payload(Path(args.cookies_json).read_text(encoding="utf-8"))
        elif args.cookies_base64:
            cookies = _load_cookie_payload(args.cookies_base64)
        return args.email, args.password, cookies, args.user_agent, None

    if not args.outreach_email:
        raise SystemExit("Provide either --outreach-email or --email/--password.")

    with SyncSessionLocal() as db:
        stmt = select(models.OutreachLinkedInProfile).filter(
            models.OutreachLinkedInProfile.linkedin_email == args.outreach_email
        )
        outreach = db.execute(stmt).scalars().first()
        if not outreach:
            raise SystemExit(f"Outreach profile {args.outreach_email} not found.")
        outreach_id = outreach.id

    session_manager = LinkedInSessionManager()
    email, password = session_manager.get_user_and_password(outreach_id)
    cookies, user_agent = session_manager._load_session_from_store(email, outreach_id)
    return email, password, cookies, user_agent, outreach_id


def _dump_page(service: LinkedInService, dump_dir: Path, label: str) -> None:
    dump_dir.mkdir(parents=True, exist_ok=True)
    content = service.page.content()
    path = dump_dir / f"{label}.html"
    path.write_text(content, encoding="utf-8")
    print(f"[debug] wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect connection workflow for a target profile.")
    parser.add_argument("--outreach-email", help="Outreach seat email stored in the DB")
    parser.add_argument("--email", help="Raw LinkedIn login email (bypass DB lookup)")
    parser.add_argument("--password", help="Raw LinkedIn login password (requires --email)")
    parser.add_argument("--cookies-json", help="Path to JSON file containing Playwright cookies")
    parser.add_argument("--cookies-base64", help="Inline JSON/Base64 cookie string")
    parser.add_argument("--user-agent", help="Optional UA override when using --email/--password")
    parser.add_argument("--target-url", required=True, help="Target LinkedIn profile URL")
    parser.add_argument("--note", default="", help="Optional connection note (<=300 chars)")
    parser.add_argument("--dump-dir", help="Directory to store HTML snapshots after completion")
    parser.add_argument("--force-send", action="store_true", help="Send invite even if already connected/pending")
    args = parser.parse_args()

    email, password, cookies, user_agent, outreach_id = _resolve_session(args)
    service = LinkedInService(email, password, cookies=cookies, user_agent=user_agent)

    dump_dir = Path(args.dump_dir).resolve() if args.dump_dir else None

    try:
        login_key = outreach_id or 0
        print(f"[debug] Logging in as {email} (outreach_id={login_key})...")
        if not service.login(login_key):
            raise SystemExit("Login failed.")

        profile_data = service.fetch_profile_info(args.target_url)
        if not profile_data:
            raise SystemExit("fetch_profile_info returned nothing.")
        _print_block("PROFILE SNAPSHOT", profile_data)

        connected = bool(profile_data.get("connected"))
        pending = bool(profile_data.get("connection_pending"))

        if connected and not args.force_send:
            print("[result] Already connected – no invite sent.")
            return
        if pending and not args.force_send:
            print("[result] Invitation already pending – no invite sent.")
            return

        if args.note and len(args.note) > 300:
            raise SystemExit("Note exceeds 300-character LinkedIn limit.")

        print("[debug] Sending connection request...")
        success = service.send_connection_request(args.target_url, args.note or None)
        if not success:
            reason = None
            if hasattr(service, "get_last_connect_error"):
                try:
                    reason = service.get_last_connect_error()
                except Exception:
                    reason = None
            message = "send_connection_request returned False."
            if reason:
                message += f" Reason: {reason}"
            raise SystemExit(message)
        print("[result] Connection request flow completed successfully.")

        # Re-fetch to show updated state (best effort)
        refreshed = service.fetch_profile_info(args.target_url)
        if refreshed:
            _print_block("REFRESHED SNAPSHOT", refreshed)

        if dump_dir:
            _dump_page(service, dump_dir, "post_connection")
    finally:
        try:
            service.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

