#!/usr/bin/env python
"""
Utility script to manually inspect LinkedIn's messaging composer state for a given outreach profile.

This bypasses the normal send_message workflow and instead captures the DOM that determines whether
the Send button is available/enabled. Use this to debug selector or localization regressions.
"""

import argparse
import json
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import select

from app import models
from app.database import SyncSessionLocal
from app.services.service_manager import LinkedInSessionManager

import sys
sys.path.append("/app/linkedin-service")
from linkedin_sync import LinkedInService


def _print_title(text: str) -> None:
    print("\n" + "=" * 80)
    print(text)
    print("=" * 80 + "\n")


def _dump_elements(label: str, locator, limit: int = 5) -> None:
    count = locator.count()
    print(f"{label}: count={count}")
    for idx in range(min(count, limit)):
        el = locator.nth(idx)
        attrs = {
            "text": (el.inner_text() or "").strip(),
            "aria-label": el.get_attribute("aria-label"),
            "class": el.get_attribute("class"),
            "type": el.get_attribute("type"),
            "disabled": el.get_attribute("disabled"),
        }
        print(f"  [{idx}] attrs={json.dumps(attrs, ensure_ascii=False)}")


def _ensure_textbox_ready(service: LinkedInService):
    page = service.page
    textbox = page.locator("div.msg-form__contenteditable").first
    if textbox.count() == 0:
        textbox = page.locator("div[role='textbox'][contenteditable='true']").first
    if textbox.count() == 0:
        raise RuntimeError("Composer textbox not found")

    # Dismiss typeahead overlay if present
    overlay = page.locator("div.msg-connections-typeahead__search-results")
    if overlay.count() > 0 and overlay.first.is_visible():
        service.page.keyboard.press("Escape")
        service.human_delay(0.5, 1.0)
    else:
        search_field = page.locator("input.msg-connections-typeahead__search-field").first
        if search_field.count() > 0 and search_field.is_visible():
            search_field.press("Enter")
            service.human_delay(0.5, 1.0)

    try:
        textbox.click(timeout=3000)
    except Exception:
        handle = None
        try:
            handle = textbox.element_handle()
        except Exception:
            pass
        if handle:
            try:
                service.page.evaluate("(el) => el.focus()", handle)
                service.page.evaluate("(el) => el.click()", handle)
            except Exception:
                pass
    service.human_delay(0.5, 1.0)
    return textbox


def _set_textbox_value(textbox, service: LinkedInService, text: str) -> None:
    try:
        textbox.fill("")
    except Exception:
        try:
            textbox.press("Control+A")
            textbox.press("Backspace")
        except Exception:
            pass
    try:
        service.page.keyboard.type(text, delay=40)
    except Exception:
        handle = None
        try:
            handle = textbox.element_handle()
        except Exception:
            pass
        if handle:
            service.page.evaluate(
                "(el, value) => { el.innerHTML = `<p>${value}</p>`; el.dispatchEvent(new Event('input', {bubbles:true})); }",
                handle,
                text,
            )


def analyze_send_button(service: LinkedInService, dump_dir: Optional[Path] = None) -> None:
    page = service.page
    textbox = _ensure_textbox_ready(service)

    _print_title("TEXTBOX STATE")
    inner_html = textbox.inner_html()
    print(inner_html)

    send_selectors: List[str] = [
        "button.msg-form__send-button",
        'button[type="submit"][class*="send-button"]',
        "form.msg-form button:has-text('Send')",
        "button:has-text('Send')",
        "button[aria-label*='Send']",
    ]

    _print_title("SEND BUTTON SEARCH (composer form first, then page)")
    composer_form = textbox.locator("xpath=ancestor::form[contains(@class,'msg-form')]")
    scopes = []
    if composer_form.count():
        scopes.append(("composer_form", composer_form.first))
    scopes.append(("page", page))

    for sel in send_selectors:
        for scope_name, scope in scopes:
            locator = scope.locator(sel)
            _dump_elements(f"{scope_name} :: {sel}", locator)

    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
        for name, locator in [("composer", textbox), ("page", page.locator("body"))]:
            if locator.count():
                html = locator.inner_html() if hasattr(locator, "inner_html") else page.content()
                path = dump_dir / f"{name}.html"
                path.write_text(html, encoding="utf-8")
                print(f"Wrote {path}")


def _load_cookies_from_arg(arg_value: str) -> list:
    data = json.loads(arg_value)
    if isinstance(data, dict):
        if "cookies" in data:
            return data["cookies"]
        raise SystemExit("Cookie JSON must be a list or an object containing 'cookies'.")
    if not isinstance(data, list):
        raise SystemExit("Cookie JSON must decode to a list of Playwright cookies.")
    return data


def _resolve_session_inputs(
    args: argparse.Namespace,
) -> Tuple[str, str, list, Optional[str], Optional[int]]:
    if args.email:
        if not args.password:
            raise SystemExit("--password is required when --email is provided.")
        cookies: list = []
        if args.cookies_json:
            cookies = _load_cookies_from_arg(Path(args.cookies_json).read_text(encoding="utf-8"))
        elif args.cookies_base64:
            cookies = _load_cookies_from_arg(args.cookies_base64)
        return args.email, args.password, cookies, args.user_agent, None

    if not args.outreach_email:
        raise SystemExit("Provide either --outreach-email or --email/--password.")

    session_manager = LinkedInSessionManager()
    with SyncSessionLocal() as db:
        outreach = (
            db.execute(
                select(models.OutreachLinkedInProfile).filter(
                    models.OutreachLinkedInProfile.linkedin_email == args.outreach_email
                )
            )
            .scalars()
            .first()
        )
        if not outreach:
            raise SystemExit(f"Outreach profile {args.outreach_email} not found in DB.")
        outreach_id = outreach.id

    email, password = session_manager.get_user_and_password(outreach_id)
    cookies, user_agent = session_manager._load_session_from_store(email, outreach_id)
    return email, password, cookies, user_agent, outreach_id


def main():
    parser = argparse.ArgumentParser(description="Inspect LinkedIn messaging composer for debugging.")
    parser.add_argument("--outreach-email", help="LinkedIn outreach seat email (uses stored session)")
    parser.add_argument("--email", help="LinkedIn login email (direct login mode)")
    parser.add_argument("--password", help="LinkedIn password (direct login mode)")
    parser.add_argument("--cookies-json", help="Path to JSON file containing Playwright cookies")
    parser.add_argument("--cookies-base64", help="Inline JSON/base64 string containing Playwright cookies")
    parser.add_argument("--user-agent", help="Optional user agent when using --email/--password")
    parser.add_argument("--target-url", required=True, help="LinkedIn profile URL to open")
    parser.add_argument("--message", default="Debug message from inspection script.", help="Message text to type")
    parser.add_argument("--dump-dir", type=Path, help="Optional directory to dump HTML snapshots")
    parser.add_argument("--send", action="store_true", help="Attempt to click Send after inspection")
    args = parser.parse_args()

    email, password, cookies, user_agent, outreach_id = _resolve_session_inputs(args)
    login_profile_id = outreach_id if outreach_id is not None else 0

    service = LinkedInService(email, password, cookies=cookies, user_agent=user_agent)
    try:
        if not service.login(login_profile_id):
            raise SystemExit("login failed")
        service.goto_profile(args.target_url)
        service.human_delay(2, 3)
        if not service.open_messaging_interface(args.target_url):
            raise SystemExit("Unable to open messaging interface")

        textbox = _ensure_textbox_ready(service)
        _set_textbox_value(textbox, service, args.message)
        service.human_delay(1, 2)

        analyze_send_button(service, args.dump_dir)

        if args.send:
            send_btn = service.page.locator("button.msg-form__send-button").first
            if send_btn.count():
                send_btn.click()
                print("Clicked Send button.")
            else:
                print("Send button still missing; skipping click.")

    finally:
        service.close()


if __name__ == "__main__":
    main()

