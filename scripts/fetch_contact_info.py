#!/usr/bin/env python
"""
Fetch contact info for a target profile using an outreach seat session.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))
sys.path.append(str(ROOT_DIR / "linkedin-service"))

from scripts.debug_connection_flow import _resolve_session  # noqa: E402
from linkedin_sync import LinkedInService  # type: ignore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch LinkedIn contact info via stored session.")
    parser.add_argument("--outreach-email", required=True, help="Email of outreach profile stored in DB")
    parser.add_argument("--target-url", required=True, help="LinkedIn profile URL to scrape contact info from")
    parser.add_argument("--dump-dir", help="Optional directory to store modal HTML or dumps")
    args = parser.parse_args()

    email, password, cookies, user_agent, outreach_id = _resolve_session(
        argparse.Namespace(
            outreach_email=args.outreach_email,
            email=None,
            password=None,
            cookies_json=None,
            cookies_base64=None,
            user_agent=None,
        )
    )

    service = LinkedInService(email, password, cookies=cookies, user_agent=user_agent)

    dump_dir: Optional[Path] = Path(args.dump_dir).resolve() if args.dump_dir else None
    dump_path: Optional[Path] = None
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_path = dump_dir / "contact_modal.html"

    try:
        login_key = outreach_id or 0
        if not service.login(login_key):
            raise SystemExit("Login failed.")
        data = service.fetch_contact_info(args.target_url)
        print(json.dumps(data, indent=2))
        if dump_path and data.get("modal_html"):
            dump_path.write_text(data["modal_html"], encoding="utf-8")
            print(f"[debug] wrote modal HTML to {dump_path}")
    finally:
        try:
            service.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

