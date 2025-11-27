#!/usr/bin/env python
"""
Standalone Playwright tool to inspect LinkedIn's messaging composer without relying on
linkedin_service/linkedin_sync.py. Useful for debugging DOM changes that break automation.
"""

import argparse
import json
from pathlib import Path
from typing import Optional, Tuple, List

from playwright.sync_api import (
    sync_playwright,
    Page,
    BrowserContext,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
)

try:
    from sqlalchemy import select
    from app import models
    from app.database import SyncSessionLocal
    from app.services.service_manager import LinkedInSessionManager
    from app.settings import logger

    APP_IMPORTS_AVAILABLE = True
except Exception:  # pragma: no cover - fallback for host-only execution
    APP_IMPORTS_AVAILABLE = False
    import logging

    logger = logging.getLogger("standalone_message_probe")
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)


def _get_credentials_from_app(outreach_email: str | None) -> Tuple[str, str, list, Optional[str]]:
    if not APP_IMPORTS_AVAILABLE:
        raise SystemExit(
            "App modules unavailable. Provide --email/--password/--cookies-json when running outside Docker."
        )
    if not outreach_email:
        raise SystemExit("--outreach-email is required when relying on application database.")
    with SyncSessionLocal() as db:
        outreach = (
            db.execute(
                select(models.OutreachLinkedInProfile).filter(
                    models.OutreachLinkedInProfile.linkedin_email == outreach_email
                )
            )
            .scalars()
            .first()
        )
        if not outreach:
            raise SystemExit(f"Outreach profile {outreach_email} not found")

    manager = LinkedInSessionManager()
    email, password = manager.get_user_and_password(outreach.id)
    cookies, user_agent = manager._load_session_from_store(email, outreach.id)
    if not cookies:
        raise SystemExit("No stored cookies; login without automation is not supported in this script.")
    return email, password, cookies, user_agent


def _load_cookies_from_arg(arg_value: str) -> list:
    data = json.loads(arg_value)
    if isinstance(data, dict):
        if "cookies" in data:
            return data["cookies"]
        raise SystemExit("Cookie JSON must be a list or an object containing 'cookies'.")
    if not isinstance(data, list):
        raise SystemExit("Cookie JSON must decode to a list of Playwright cookies.")
    return data


def _resolve_session_inputs(args) -> Tuple[str, Optional[str], list, Optional[str]]:
    if args.email:
        cookies: list = []
        if args.cookies_json:
            cookies = _load_cookies_from_arg(Path(args.cookies_json).read_text(encoding="utf-8"))
        elif args.cookies_base64:
            cookies = _load_cookies_from_arg(args.cookies_base64)
        return args.email, args.password, cookies, args.user_agent
    return _get_credentials_from_app(args.outreach_email)


def _start_browser(
    playwright: Playwright,
    user_agent: Optional[str],
    cookies: list,
    headed: bool = False,
) -> Tuple[BrowserContext, Page]:
    browser = playwright.chromium.launch(
        headless=not headed,
        args=["--disable-dev-shm-usage", "--no-sandbox"],
    )
    context_args = {"viewport": None, "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"}}
    if user_agent:
        context_args["user_agent"] = user_agent
    context = browser.new_context(**context_args)
    if cookies:
        context.add_cookies(cookies)
    page = context.new_page()
    return context, page


def _highlight(locator, page: Page, label: str) -> None:
    if not locator or locator.count() == 0:
        return
    try:
        handle = locator.first.element_handle()
    except Exception:
        return
    if not handle:
        return
    page.evaluate(
        """(el) => {
            const prev = el.getAttribute('__probe_outline');
            if (prev === null) {
                el.setAttribute('__probe_outline', el.style.outline || '');
            }
            el.style.outline = '3px solid #ff00ff';
            el.style.outlineOffset = '2px';
        }""",
        handle,
    )
    print(f"[probe] Highlighted {label}")
    page.wait_for_timeout(600)


def _log_message_buttons(page: Page) -> None:
    buckets = [
        ("primary_actions", "div.pvs-profile-actions button:has-text('Message')"),
        ("primary_actions_links", "div.pvs-profile-actions a:has-text('Message')"),
        ("aria-label message buttons", "button[aria-label*='Message']"),
        ("aria-label message links", "a[aria-label*='Message']"),
        ("generic message buttons", "button:has-text('Message')"),
        ("generic message links", "a:has-text('Message')"),
        ("compose links", "a[href^='/messaging/compose']"),
    ]
    print("[probe] -------- message button scan --------")
    for label, selector in buckets:
        locator = page.locator(selector)
        count = locator.count()
        print(f"[probe] {label}: {count}")
        for idx in range(min(count, 3)):
            el = locator.nth(idx)
            try:
                attrs = {
                    "text": (el.inner_text() or "").strip(),
                    "aria-label": el.get_attribute("aria-label"),
                    "class": el.get_attribute("class"),
                }
            except Exception:
                attrs = {"error": "unavailable"}
            print(f"    ↳ [{idx}] {attrs}")
    print("[probe] ------------------------------------")


def _ensure_logged_in(page: Page, email: str, password: str) -> None:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
    if page.url.startswith("https://www.linkedin.com/feed/"):
        logger.info("Session restored via cookies.")
        return

    logger.info("Cookies invalid; attempting manual login.")
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
    page.fill('input[name="session_key"]', email)
    page.fill('input[name="session_password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    if not page.url.startswith("https://www.linkedin.com/feed/"):
        raise SystemExit("Login failed; cannot proceed.")


def _open_message_overlay(page: Page, profile_url: str) -> None:
    page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass
    _log_message_buttons(page)

    top_card = page.locator("section[data-view-name='profile-card'], section.pv-top-card").first
    if top_card.count():
        primary_msg = top_card.locator("div.pvs-profile-actions button:has-text('Message')")
        primary_count = primary_msg.count()
        print(f"[probe] primary action message buttons: {primary_count}")
        if primary_count:
            _highlight(primary_msg, page, "primary message button near More actions")
            clicked = False
            for attempt in range(2):
                try:
                    primary_msg.first.click(force=attempt == 1, timeout=4000)
                    clicked = True
                    break
                except Exception as exc:
                    print(f"[probe] primary click attempt {attempt + 1} failed: {exc}")
            if clicked:
                try:
                    page.wait_for_selector(
                        "div.msg-overlay-conversation-bubble-header, div.msg-form__contenteditable",
                        timeout=10000,
                    )
                except PlaywrightTimeoutError:
                    page.wait_for_timeout(1500)
                print(f"[probe] Messaging interface opened at {page.url}")
                return

    selectors = [
        "button:has-text('Message')",
        "button:has-text('Messaggio')",
        "button:has-text('Invia messaggio')",
        "a:has-text('Message')",
        "a[aria-label*='Message']",
        "button[aria-label*='Message']",
        "div[data-view-name*='message'] button",
        "div[data-view-name*='message'] a",
        "button[data-control-name*='message']",
        "button[data-view-name*='message']",
        "a[data-control-name*='message']",
        "a[data-view-name*='message']",
        "a[href^='/messaging/compose']",
        "div.pvs-sticky-header__actions button:has-text('Message')",
    ]
    for sel in selectors:
        btn = page.locator(sel).first
        if btn.count():
            _highlight(btn, page, f"message trigger ({sel})")
            try:
                btn.click(timeout=4000)
            except Exception:
                try:
                    btn.click(force=True, timeout=4000)
                except Exception:
                    handle = None
                    try:
                        handle = btn.element_handle()
                    except Exception:
                        handle = None
                    if handle:
                        page.evaluate("(el) => el.click()", handle)
            try:
                page.wait_for_selector(
                    "div.msg-overlay-conversation-bubble-header, div.msg-form__contenteditable",
                    timeout=10000,
                )
            except PlaywrightTimeoutError:
                page.wait_for_timeout(1500)
            print(f"[probe] Messaging interface opened at {page.url}")
            return
    raise SystemExit("Failed to open messaging interface; message button missing.")


def _stabilize_typeahead(page: Page) -> None:
    search_field = page.locator("input.msg-connections-typeahead__search-field").first
    if search_field.count() > 0 and search_field.is_visible():
        search_field.press("Enter")
        page.wait_for_timeout(500)
    overlay = page.locator("div.msg-connections-typeahead__search-results")
    if overlay.count() > 0 and overlay.first.is_visible():
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)


def _find_textbox(page: Page, dump_dir: Optional[Path]) -> Page:
    try:
        page.wait_for_selector("div.msg-form__contenteditable, div[role='textbox'][contenteditable='true']", timeout=8000)
    except PlaywrightTimeoutError:
        pass
    selectors = [
        "div.msg-form__contenteditable",
        'div[role="textbox"][aria-label*="Write" i]',
        'div[role="textbox"][contenteditable="true"]',
    ]
    for sel in selectors:
        locator = page.locator(sel).first
        if locator.count():
            try:
                locator.wait_for(state="visible", timeout=2000)
                _highlight(locator, page, "composer textbox located")
                return locator
            except PlaywrightTimeoutError:
                continue
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
        debug_path = dump_dir / "missing_textbox.html"
        debug_path.write_text(page.content(), encoding="utf-8")
        print(f"No textbox found at {page.url}; dumped HTML to {debug_path}")
    raise SystemExit("Composer textbox not found.")


def _fill_textbox(textbox, page: Page, text: str) -> None:
    try:
        textbox.click(timeout=2000)
    except Exception:
        handle = None
        try:
            handle = textbox.element_handle()
        except Exception:
            handle = None
        if handle:
            page.evaluate("(el) => el.focus()", handle)
    try:
        textbox.fill("")
    except Exception:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
    _highlight(textbox, page, "composer textbox before typing")
    page.wait_for_timeout(400)
    page.keyboard.type(text, delay=40)


def _inspect_send_buttons(page: Page, dump_dir: Optional[Path]) -> None:
    send_selectors = [
        "button.msg-form__send-button",
        'button[type="submit"][class*="send-button"]',
        "form.msg-form button:has-text('Send')",
        "button:has-text('Send')",
        "button[aria-label*='Send']",
    ]
    composer_form = page.locator("form.msg-form").first
    scopes: List[Tuple[str, Page]] = []
    if composer_form.count():
        scopes.append(("composer_form", composer_form))
    scopes.append(("page", page))

    for sel in send_selectors:
        for scope_name, scope in scopes:
            locator = scope.locator(sel)
            count = locator.count()
            print(f"{scope_name} :: {sel} -> {count}")
            for idx in range(min(count, 3)):
                el = locator.nth(idx)
                _highlight(el, page, f"send button candidate {sel} (scope {scope_name}, idx {idx})")
                attrs = {
                    "text": (el.inner_text() or "").strip(),
                    "aria-label": el.get_attribute("aria-label"),
                    "class": el.get_attribute("class"),
                    "disabled": el.get_attribute("disabled"),
                }
                print(f"  [{idx}] {attrs}")

    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_file = dump_dir / "composer.html"
        dump_file.write_text(page.content(), encoding="utf-8")
        print(f"Composer HTML written to {dump_file}")


def main():
    parser = argparse.ArgumentParser(description="Standalone LinkedIn messaging debugger.")
    parser.add_argument("--outreach-email")
    parser.add_argument("--email", help="LinkedIn login email (host mode).")
    parser.add_argument("--password", help="LinkedIn login password (host mode).")
    parser.add_argument("--cookies-json", help="Path to Playwright cookies JSON (host mode).")
    parser.add_argument("--cookies-base64", help="Inline JSON string for cookies (host mode).")
    parser.add_argument("--user-agent", help="Optional user-agent override when supplying credentials.")
    parser.add_argument("--skip-login", action="store_true", help="Assume cookies already authenticated; skip credential login.")
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--message", default="Standalone debug ping. Please ignore.")
    parser.add_argument("--dump-dir", type=Path)
    parser.add_argument("--click-send", action="store_true", help="Attempt to click Send if located.")
    parser.add_argument("--headed", action="store_true", help="Launch Chromium with UI for visual debugging.")
    args = parser.parse_args()

    email, password, cookies, user_agent = _resolve_session_inputs(args)

    playwright = sync_playwright().start()
    try:
        context, page = _start_browser(playwright, user_agent, cookies, headed=args.headed)
        _ensure_logged_in(page, email, password)
        _open_message_overlay(page, args.target_url)
        _stabilize_typeahead(page)
        textbox = _find_textbox(page, args.dump_dir)
        _fill_textbox(textbox, page, args.message)
        page.wait_for_timeout(1000)
        _inspect_send_buttons(page, args.dump_dir)

        if args.click_send:
            send_btn = page.locator("button.msg-form__send-button").first
            if send_btn.count():
                send_btn.click()
                print("Send button clicked.")
            else:
                print("Send button missing; skipping click.")
    finally:
        playwright.stop()


if __name__ == "__main__":
    main()

