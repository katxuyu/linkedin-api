import asyncio
import time
import json
import os
import random
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from playwright.sync_api import (
    sync_playwright,
    Playwright,
    BrowserContext,
    Page,
    Locator,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)
from fake_useragent import UserAgent
from typing import Any, Optional, Dict, List
import re
from datetime import datetime, timedelta, timezone
import requests
from logger import logger
from settings import TWO_CAPTCHA_API_KEY
from utils.cookie_sanitizer import sanitize_cookies


class LinkedInServiceError(Exception):
    """Base class for LinkedIn service errors."""


class LinkedInAuthError(LinkedInServiceError):
    """Raised when authentication is required or fails."""


class LinkedInCaptchaError(LinkedInServiceError):
    """Raised when LinkedIn presents a captcha or security challenge."""


class LinkedInSearchError(LinkedInServiceError):
    """Raised when a LinkedIn search fails."""


class LinkedInSearchEmptyError(LinkedInSearchError):
    """Raised when a LinkedIn search returns no people results."""


@dataclass
class LinkedInSearchLead:
    url: str
    name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None


class TwoCaptchaSolver:
    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def solve_recaptcha_v2(self, page: Page, site_key: str, page_url: str) -> bool:
        if not self.is_configured:
            logger.debug("2Captcha API key not configured; skipping captcha solve.")
            return False

        logger.info("Submitting reCAPTCHA to 2Captcha for %s", page_url)
        try:
            response = requests.post(
                "http://2captcha.com/in.php",
                data={
                    "key": self.api_key,
                    "method": "userrecaptcha",
                    "googlekey": site_key,
                    "pageurl": page_url,
                    "json": 1,
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != 1:
                logger.error("Failed to submit captcha to 2Captcha: %s", payload.get("request"))
                return False

            captcha_id = payload["request"]
            logger.info("2Captcha request accepted (id=%s). Waiting for solution...", captcha_id)

            solution = None
            for attempt in range(40):  # ~2 minutes max
                time.sleep(3)
                poll = requests.get(
                    "http://2captcha.com/res.php",
                    params={
                        "key": self.api_key,
                        "action": "get",
                        "id": captcha_id,
                        "json": 1,
                    },
                    timeout=15,
                )
                poll.raise_for_status()
                poll_data = poll.json()
                if poll_data.get("status") == 1:
                    solution = poll_data["request"]
                    logger.info("2Captcha solved the challenge.")
                    break
                if poll_data.get("request") != "CAPCHA_NOT_READY":
                    logger.error("2Captcha returned error: %s", poll_data.get("request"))
                    return False
            if not solution:
                logger.error("Timed out waiting for 2Captcha solution.")
                return False

            page.evaluate(
                """(token) => {
                    const inject = (el) => {
                        el.value = token;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    };
                    let textarea = document.getElementById('g-recaptcha-response');
                    if (!textarea) {
                        textarea = document.createElement('textarea');
                        textarea.id = 'g-recaptcha-response';
                        textarea.name = 'g-recaptcha-response';
                        textarea.style.width = '1px';
                        textarea.style.height = '1px';
                        textarea.style.opacity = '0';
                        textarea.style.position = 'absolute';
                        textarea.style.left = '-9999px';
                        document.body.appendChild(textarea);
                    }
                    inject(textarea);
                    const other = document.querySelector('textarea[name="g-recaptcha-response"]');
                    if (other && other !== textarea) {
                        inject(other);
                    }
                }""",
                solution,
            )
            return True
        except Exception as exc:
            logger.exception("2Captcha solving failed: %s", exc)
            return False


class LinkedInService:
    def __init__(self, email: str, password: str, cookies=None, user_agent=None):
        self.proxies = []
        self.email = email
        self.password = password
        self.playwright: Optional[Playwright] = None
        self.browser_context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.browser = None
        sanitized_cookies = sanitize_cookies(cookies) if cookies else []
        self.cookies = sanitized_cookies or None
        self.user_agent = user_agent
        self.captcha_solver = TwoCaptchaSolver(TWO_CAPTCHA_API_KEY) if TWO_CAPTCHA_API_KEY else None
        self.current_profile_url: Optional[str] = None
        self.last_connect_error: Optional[str] = None
        self.last_checkpoint_context: Optional[Dict[str, Any]] = None

    @staticmethod
    def human_delay(min_sec=1, max_sec=5):
        """Simulate human-like delay in synchronous code."""
        time.sleep(random.uniform(min_sec, max_sec))

    def is_alive(self) -> bool:
        try:
            if not self.page or not self.browser:
                return False
            return not self.page.is_closed() and self.browser.is_connected()
        except Exception:
            return False
    
    @staticmethod
    def _normalize_profile_url(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        raw = url.strip()
        parsed = urlsplit(raw)
        path = parsed.path or ""
        path = path if path.startswith("/") else f"/{path}" if path else ""
        path = path.rstrip("/")
        scheme = parsed.scheme
        netloc = parsed.netloc
        if not scheme:
            scheme = "https"
        if not netloc:
            netloc = "www.linkedin.com"
        normalized = urlunsplit((scheme, netloc, path, "", ""))
        return normalized

    @staticmethod
    def _append_locale_param(url: Optional[str], locale: str = "en") -> Optional[str]:
        if not url:
            return url
        try:
            parsed = urlsplit(url)
        except Exception:
            return url
        netloc = parsed.netloc or ""
        path = parsed.path or ""
        if "linkedin.com" not in netloc:
            return url
        if "/in/" not in path:
            return url
        params = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() != "locale"
        ]
        params.append(("locale", locale))
        new_query = urlencode(params)
        return urlunsplit((parsed.scheme, netloc, path, new_query, parsed.fragment))

    def _find_top_card(self):
        if not self.page:
            return None
        selectors = [
            "section[componentkey*='Topcard']",
            "div[componentkey*='Topcard']",
            "section[data-view-name='profile-card']",
            "section.pv-top-card",
            "section.artdeco-card.pv-profile-card",
            "section.scaffold-layout__row:has(h1)",
            "section:has(h1)",
            "div[data-view-name='profile-card']",
            "div.pv-top-card",
            "div.artdeco-card.pv-top-card",
            "div.artdeco-card:has(h1)",
            "div.scaffold-layout__row:has(h1)",
            "main div:has(> div.pv-text-details__left-panel h1)",
        ]
        for selector in selectors:
            locator = self.page.locator(selector)
            if locator.count() > 0:
                return locator.first
        return None

    def _extract_text_from_selectors(self, root, selectors):
        if not root:
            return None
        for selector in selectors:
            locator = root.locator(selector)
            text = self._scrape_safe_text(locator)
            if text:
                return text.strip()
        return None

    def _element_snapshot(self, locator: Locator) -> Dict[str, Optional[str]]:
        snapshot: Dict[str, Optional[str]] = {}
        try:
            snapshot["text"] = (locator.inner_text() or "").strip()
        except Exception:
            snapshot["text"] = None
        for attr in ("aria-label", "href", "class", "data-control-name", "data-view-name"):
            try:
                snapshot[attr] = locator.get_attribute(attr)
            except Exception:
                snapshot[attr] = None
        try:
            box = locator.bounding_box()
            if box:
                snapshot["position"] = f"x={box['x']:.1f}, y={box['y']:.1f}"
        except Exception:
            snapshot["position"] = None
        return snapshot

    def _has_follow_button(self, scopes: list[Locator]) -> bool:
        selectors = [
            "button:has-text('Follow')",
            "button:has-text('Following')",
            "a:has-text('Follow')",
            "a:has-text('Following')",
            "button[aria-label*='Follow']",
            "a[aria-label*='Follow']",
        ]
        selector_str = ", ".join(selectors)
        for scope in scopes:
            if not scope:
                continue
            try:
                locator = scope.locator(selector_str)
                if locator.count() > 0:
                    return True
            except Exception:
                continue
        return False

    def get_last_connect_error(self) -> Optional[str]:
        return self.last_connect_error

    def _log_message_buttons(self, context: str) -> None:
        buckets = [
            ("primary_data_view", "a[data-view-name='profile-primary-message'], button[data-view-name='profile-primary-message']"),
            ("top_card_buttons", "div.pvs-profile-actions button:has-text('Message')"),
            ("top_card_links", "div.pvs-profile-actions a:has-text('Message')"),
            ("aria_buttons", "button[aria-label*='Message']"),
            ("aria_links", "a[aria-label*='Message']"),
            ("generic_buttons", "button:has-text('Message')"),
            ("generic_links", "a:has-text('Message')"),
            ("compose_links", "a[href^='/messaging/compose']"),
        ]
        logger.info("Message button scan (%s)", context)
        for label, selector in buckets:
            locator = self.page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0
            logger.info("  [%s] selector=%s count=%s", label, selector, count)
            for idx in range(min(count, 3)):
                try:
                    entry = locator.nth(idx)
                    info = self._element_snapshot(entry)
                    logger.info("    - #%s %s", idx, info)
                except Exception:
                    logger.debug("Unable to inspect message button %s idx %s", label, idx, exc_info=True)

    def _should_skip_message_button(self, locator: Locator) -> bool:
        try:
            aria = (locator.get_attribute("aria-label") or "").strip().lower()
        except Exception:
            aria = ""
        try:
            text = (locator.inner_text() or "").strip().lower()
        except Exception:
            text = ""
        premium_phrases = ("message with premium",)
        premium_texts = ("say hello",)
        if any(phrase in aria for phrase in premium_phrases):
            return True
        if any(text == phrase for phrase in premium_texts):
            return True
        try:
            data_view = (locator.get_attribute("data-view-name") or "").lower()
        except Exception:
            data_view = ""
        if "highlights-message" in data_view:
            return True
        try:
            overlay = locator.locator("xpath=ancestor::*[contains(@class, 'msg-overlay')]")
            if overlay.count() > 0:
                return True
        except Exception:
            pass
        return False

    def _log_connect_buttons(self, context: str) -> None:
        buckets = [
            (
                "top_card_actions",
                "div.pvs-profile-actions button:has-text('Connect'), "
                "div.pvs-profile-actions button:has-text('Collegati'), "
                "div.pvs-profile-actions button:has-text('Connetti'), "
                "div.pvs-profile-actions button[aria-label*='Invite to connect'], "
                "div.pvs-profile-actions button[aria-label*='Connect']",
            ),
            (
                "data_view_actions",
                "div[data-view-name*='relationship-building'] button, "
                "div[data-view-name*='edge-creation-connect-action'] button, "
                "button[data-view-name*='connect'], "
                "a[data-view-name*='connect']",
            ),
            (
                "aria_buttons",
                "button[aria-label*='Invite to connect'], "
                "button[aria-label*='Connect'], "
                "button[aria-label*='Collegati'], "
                "button[aria-label*='Connetti']",
            ),
            (
                "generic_buttons",
                "button:has-text('Connect'), "
                "button:has-text('Collegati'), "
                "button:has-text('Connetti')",
            ),
            (
                "generic_links",
                "a:has-text('Connect'), "
                "a:has-text('Collegati'), "
                "a[href*='/preload/custom-invite']",
            ),
        ]
        logger.info("Connect button scan (%s)", context)
        for label, selector in buckets:
            locator = self.page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0
            logger.info("  [%s] selector=%s count=%s", label, selector, count)
            for idx in range(min(count, 3)):
                try:
                    entry = locator.nth(idx)
                    info = self._element_snapshot(entry)
                    logger.info("    - #%s %s", idx, info)
                except Exception:
                    logger.debug("Unable to inspect connect button %s idx %s", label, idx, exc_info=True)

    def _click_connect_button(self, locator: Locator, source: str = "") -> bool:
        target = locator
        try:
            if locator.count() > 1:
                target = locator.first
        except Exception:
            pass
        if target.count() == 0:
            return False
        try:
            logger.info(
                "Attempting to click Connect button%s %s",
                f" from {source}" if source else "",
                self._element_snapshot(target),
            )
        except Exception:
            logger.debug("Unable to capture element snapshot before clicking connect", exc_info=True)
        try:
            target.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            logger.debug("Unable to scroll connect button into view", exc_info=True)
        try:
            target.wait_for(state="visible", timeout=5000)
        except Exception:
            logger.debug("Connect button located but not visibly rendered; forcing click", exc_info=True)

        for attempt in range(3):
            try:
                if attempt == 0:
                    target.click(timeout=4000)
                elif attempt == 1:
                    target.click(force=True, timeout=4000)
                else:
                    handle = target.element_handle()
                    if handle:
                        self.page.evaluate("(el) => el.click()", handle)
                    else:
                        raise PlaywrightError("Connect button element handle missing")
                logger.info("Clicked Connect button%s", f" from {source}" if source else "")
                return True
            except Exception as exc:
                logger.warning("Attempt %s to click Connect button failed: %s", attempt + 1, exc)
                self.human_delay(0.5, 1.0)
        logger.error("Unable to click Connect button after multiple attempts")
        return False

    def _locate_more_actions_button(self, scopes: list[Locator]) -> Locator | None:
        selectors = [
            'button[aria-label*="More actions"]',
            'button[aria-label*="More"]',
            'button[data-test-icon="ellipsis-h"]',
            "button:has-text('More')",
            "button:has-text('Altro')",
        ]
        search_scopes = list(scopes)
        if self.page not in search_scopes:
            search_scopes.append(self.page)
        for scope in search_scopes:
            if not scope:
                continue
            for sel in selectors:
                candidate = scope.locator(sel).first
                if candidate.count() > 0:
                    return candidate
        return None

    def close(self) -> bool:
        try:
            if self.is_alive():  # and self.browser.is_connected():
                self.browser.close()
                self.playwright.stop()
                return True
            return False
        except Exception:
            return False

    def start(
        self, 
        use_proxies: bool = False, 
        max_proxy_retries: int = 20
    ):
        """Start Playwright and launch browser, keep it persistent."""

        # Ensure we are not inside a running asyncio loop before using sync Playwright API
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            logger.debug("Existing asyncio loop detected; creating a new event loop for Playwright sync API.")
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)

        self.playwright = sync_playwright().start()

        # Configure browser context
        browser_context_options = {
            # "viewport": {"width": 1280, "height": 720},
            "viewport": None,
            "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"}
        }
        if self.user_agent:
            browser_context_options.update({"user_agent": self.user_agent})

        # Disable WebRTC / bot detection
        bot_stealth_js_script = """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            Object.defineProperty(window, 'RTCPeerConnection', {value: undefined});
            Object.defineProperty(window, 'webkitRTCPeerConnection', {value: undefined});
            Object.defineProperty(window, 'mozRTCPeerConnection', {value: undefined});
            Object.defineProperty(navigator, 'getUserMedia', {value: undefined});
            Object.defineProperty(navigator, 'webkitGetUserMedia', {value: undefined});
            Object.defineProperty(navigator, 'mozGetUserMedia', {value: undefined});
        """

        logger.info("Starting session without proxy...")

        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]

        headless_env = os.getenv("PLAYWRIGHT_HEADLESS", "").strip().lower()
        requested_headless = headless_env not in {"0", "false", "no"}
        launch_kwargs = {
            "headless": requested_headless,
            "args": launch_args,
        }

        try:
            self.browser = self.playwright.chromium.launch(**launch_kwargs)
        except PlaywrightError as exc:
            if not requested_headless:
                logger.warning(
                    "Headed Chromium launch failed (%s); retrying in headless mode.",
                    exc,
                )
                launch_kwargs["headless"] = True
                self.browser = self.playwright.chromium.launch(**launch_kwargs)
            else:
                self.playwright.stop()
                raise
        self.browser_context = self.browser.new_context(**browser_context_options)
        
        # restore cookies if available (after browser_context is created)
        if self.cookies:
            try:
                self.browser_context.add_cookies(self.cookies)
            except Exception as e:
                logger.warning(f"Failed to restore cookies for {self.email}: {e}")

        self.browser_context.add_init_script(bot_stealth_js_script)
        self.page = self.browser_context.new_page()

        # if use_proxies:
        #     self.proxies = Proxy().load_all_proxies()
        # if self.proxies:
        #     proxy_list = random.sample(self.proxies, k=max_proxy_retries)

        #     for i, proxy in enumerate(proxy_list):
        #         logger.info(f"Starting browser with proxy {i+1}/{max_proxy_retries}: {proxy['server']}")
        #         browser_context_options["proxy"] = proxy
        #         try:
        #             self.browser = self.playwright.chromium.launch(headless=False, slow_mo=100, args=["--start-maximized"])
        #             self.browser_context = self.browser.new_context(**browser_context_options)
        #             if self.cookies:
        #                 self.browser_context.add_cookies(self.cookies)
        #             self.browser_context.add_init_script(bot_stealth_js_script)
        #             self.page = self.browser_context.new_page()
        #             if proxy:
        #                 try:
        #                     # Test proxy if applicable
        #                     if not self.test_proxy(self.page, proxy, timeout=30000):
        #                         logger.warning(f"Skipping proxy {proxy['server']} due to test failure.")
        #                         self.browser.close()
        #                         continue
        #                     else:
        #                         logger.warning(f"Proxy {proxy['server']} is working.")
        #                         break  # Exit loop if proxy works
        #                 except Exception as e:
        #                     logger.error(f"Error occurred while testing proxy {proxy['server']}: {e}")
        #                     continue
        #         except Exception as e:
        #             logger.error(f"Failed to launch browser with proxy {proxy['server']}: {e}")
        #             continue
        #     logger.error(f"All proxies failed after {max_proxy_retries} attempts.")
        #     self.browser.close()
        

    def test_proxy(self, page, proxy, timeout=15000):
        """Test if a proxy is working by navigating to a test site."""
        logger.info(f"Testing proxy: {proxy['server']}")
        try:
            page.goto("https://www.whatismyipaddress.com", wait_until="domcontentloaded", timeout=timeout)
            ip_content = page.content()
            logger.info(f"Proxy test successful for {proxy['server']}. Current IP (partial content): {ip_content[:200]}")
            return True
        except Exception as e:
            if "net::ERR_TUNNEL_CONNECTION_FAILED" in str(e):
                logger.warning(f"Proxy {proxy['server']} connection failed...")
            elif "Timeout" in str(e):
                logger.warning(f"Proxy {proxy['server']} request timed out...")
            else:
                logger.warning(f"Proxy test failed for {proxy['server']}: {e}")
            return False

    
    def login(self, outreach_profile_id: int) -> bool:
        """Login to LinkedIn with optional proxy rotation."""
        if not self.is_alive():
            logger.info("Attempting to start browser...")
        # self.close()
        # logger.info("Closed browser")
            self.start()  # make sure browser/page exists

        if self.cookies and self.user_agent:
            logger.info(f"Found stored session for {self.email}, trying to restore...")
            # Set user agent
            self.browser_context = self.browser.new_context(user_agent=self.user_agent)
            # self.page = self.browser_context.new_page()

            # Set cookies
            self.browser_context.add_cookies(self.cookies)

            # Try direct navigation to feed
            self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
            self.human_delay()

            if self.page.url.startswith("https://www.linkedin.com/feed/"):
                logger.info("Restored session successfully via cookies.")
                return True
            else:
                logger.warning("Stored session invalid, falling back to normal login...")

        # --- Step 2: Do normal login with credentials ---
        # Navigate to LinkedIn login page first
        self.page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
        self.human_delay()

        # Handle welcome back screen
        login_as_button = self.page.locator('button[aria-label^="Login as"]')
        if login_as_button.count() > 0:
            login_as_button.first.click()
            self.human_delay()
            logger.info("Clicked 'Login as' button")
        if self.page.url.startswith("https://www.linkedin.com/feed/"):
            logger.info("User is already logged in.")
            return True
            # self.human_delay()
        else:
            logger.info("No 'Login as' button found, proceeding with standard login")
            self.human_delay()
            self._ensure_login_form_visible()

            # Fill credentials
            self.page.fill('input[name="session_key"]', self.email)
            self.human_delay()
            self.page.fill('input[name="session_password"]', self.password)
            self.human_delay()
            self.page.click('button[type="submit"]')
            self.human_delay()
            self.page.wait_for_load_state("domcontentloaded", timeout=60000)
            
            # Handle captcha if present
            captcha_solved = self._solve_recaptcha_if_present()
            if captcha_solved:
                logger.info("Captcha solved via 2Captcha. Checking post-captcha page state...")
                self.human_delay()
                
                # After captcha, check what page we're on before trying to click submit
                post_captcha_result = self._detect_post_captcha_state()
                if post_captcha_result == "logged_in":
                    logger.info("Successfully logged in after captcha solve.")
                    return True
                elif post_captcha_result == "2fa_pin_required":
                    logger.warning("2FA PIN input detected after captcha solve.")
                    raise LinkedInAuthError("2FA_PIN_REQUIRED")
                elif post_captcha_result == "2fa_app_approval":
                    logger.warning("LinkedIn App approval required after captcha solve - user must approve on phone.")
                    raise LinkedInAuthError("2FA_APP_APPROVAL")
                elif post_captcha_result == "account_restricted":
                    logger.error("Account restricted or blocked after captcha solve.")
                    raise LinkedInAuthError("ACCOUNT_RESTRICTED: Your LinkedIn account may be temporarily restricted. Please log in manually to verify.")
                elif post_captcha_result == "login_form":
                    # Still on login form, try to submit again
                    logger.info("Re-submitting LinkedIn login after solving captcha via 2Captcha.")
                    submit_btn = self.page.locator('button[type="submit"]')
                    if submit_btn.count() > 0:
                        submit_btn.first.click()
                        self.human_delay()
                        self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                    else:
                        logger.warning("Submit button not found after captcha solve")
                elif post_captcha_result == "captcha_failed":
                    logger.error("Captcha solution was rejected by LinkedIn.")
                    raise LinkedInAuthError("CAPTCHA_FAILED: The captcha solution was rejected. Please try again.")
                elif post_captcha_result == "checkpoint_manual_verification":
                    message = self._checkpoint_message("LinkedIn is asking for additional verification.")
                    logger.warning(f"Manual verification required: {message}")
                    raise LinkedInAuthError(f"CHECKPOINT_ACTION_REQUIRED: {message}")
                elif post_captcha_result == "checkpoint_unknown":
                    message = self._checkpoint_message("LinkedIn presented a checkpoint that we cannot handle automatically.")
                    logger.warning(f"Unknown checkpoint variant encountered: {message}")
                    raise LinkedInAuthError(f"CHECKPOINT_UNKNOWN: {message}")
                else:
                    logger.warning(f"Unknown post-captcha state: {post_captcha_result}")

        # --- Step 3: Detect login success/failure ---
        result = self._detect_post_captcha_state()
        
        if result == "logged_in":
            logger.info("Login successful.")
            return True
        elif result == "2fa_pin_required":
            logger.warning("2FA PIN input detected. User needs to enter verification code.")
            # Try solving captcha on checkpoint if present
            if self._solve_recaptcha_if_present():
                logger.info("Captcha solved while on checkpoint screen; checking if login succeeded.")
                self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                if self.page.url.startswith("https://www.linkedin.com/feed/"):
                    return True
            raise LinkedInAuthError("2FA_PIN_REQUIRED")
        elif result == "2fa_app_approval":
            logger.warning("LinkedIn App approval required. User must approve on phone/LinkedIn app.")
            raise LinkedInAuthError("2FA_APP_APPROVAL")
        elif result == "account_restricted":
            logger.error("Account restricted or blocked.")
            raise LinkedInAuthError("ACCOUNT_RESTRICTED: Your LinkedIn account may be temporarily restricted. Please log in manually to verify.")
        elif result == "checkpoint_manual_verification":
            message = self._checkpoint_message("LinkedIn is asking for additional verification before continuing.")
            logger.warning(f"Manual verification checkpoint detected: {message}")
            raise LinkedInAuthError(f"CHECKPOINT_ACTION_REQUIRED: {message}")
        elif result == "checkpoint_unknown":
            message = self._checkpoint_message("LinkedIn presented a checkpoint we cannot classify.")
            logger.error(f"Unknown checkpoint detected: {message}")
            raise LinkedInAuthError(f"CHECKPOINT_UNKNOWN: {message}")
        elif result == "unsupported_browser":
            logger.warning("Unsupported browser detected.")
            return False
        elif result == "wrong_credentials":
            logger.error("Invalid credentials.")
            raise LinkedInAuthError("INVALID_CREDENTIALS: The email or password is incorrect.")
        else:
            logger.error(f"Login failed with unknown state: {result}, URL: {self.page.url}")
            return False

    def get_session_data(self) -> dict[str, Any]:
        """
        Return cookies and user agent for persistence.
        """
        return {"cookies": self.browser_context.cookies(), "user_agent": self.page.evaluate("navigator.userAgent")}

    def submit_pin(self, pin: str) -> bool:
        """
        Submit a PIN/verification code for 2FA.
        
        LinkedIn has multiple verification flows with different input field names:
        - Standard 2FA: input[name="pin"]
        - Checkpoint challenge: input[id="input__email_verification_pin"] or other variations
        
        Args:
            pin: The verification code to submit
            
        Returns:
            bool: True if login successful after PIN submission, False otherwise
        """
        if not self.is_alive():
            logger.error("Browser session not active, cannot submit PIN")
            return False
        
        try:
            # Log current page state for debugging
            current_url = self.page.url
            logger.info(f"Attempting PIN submission on URL: {current_url}")
            
            # Try multiple possible PIN input selectors (LinkedIn uses different ones)
            pin_selectors = [
                'input[name="pin"]',
                'input[id="input__email_verification_pin"]',
                'input[id="input__phone_verification_pin"]', 
                'input[name="verification_pin"]',
                'input[type="text"][autocomplete="one-time-code"]',
                'input[aria-label*="verification"]',
                'input[aria-label*="code"]',
                'input[placeholder*="code"]',
                'input[placeholder*="digit"]',
                # Generic checkpoint input
                'input.pin-input',
                'input.verification-code-input',
                '#captcha-internal input[type="text"]',
                '.challenge-dialog input[type="text"]',
            ]
            
            pin_input = None
            used_selector = None
            
            for selector in pin_selectors:
                try:
                    locator = self.page.locator(selector)
                    if locator.count() > 0:
                        pin_input = locator.first
                        used_selector = selector
                        logger.info(f"Found PIN input with selector: {selector}")
                        break
                except Exception:
                    continue
            
            if pin_input is None:
                # Last resort: find any visible text input on the page
                all_inputs = self.page.locator('input[type="text"]:visible, input[type="tel"]:visible, input[type="number"]:visible')
                if all_inputs.count() > 0:
                    pin_input = all_inputs.first
                    used_selector = "fallback (first visible text input)"
                    logger.warning(f"Using fallback: found {all_inputs.count()} visible text inputs")
                else:
                    # Log page content for debugging
                    try:
                        page_title = self.page.title()
                        body_text = self.page.locator('body').inner_text()[:500]
                        logger.error(f"PIN input not found. Page title: {page_title}")
                        logger.error(f"Page content preview: {body_text}")
                    except Exception:
                        pass
                    logger.error("PIN input field not found with any selector")
                    return False
            
            logger.info(f"Filling PIN input field (selector: {used_selector})")
            pin_input.fill(pin)
            self.human_delay()
            
            # Try multiple submit button selectors
            submit_selectors = [
                'button[type="submit"]',
                'button[data-litms-control-urn*="submit"]',
                'button.btn__primary--large',
                '#two-step-submit-button',
                'button:has-text("Submit")',
                'button:has-text("Verify")',
                'button:has-text("Continue")',
            ]
            
            submit_clicked = False
            for selector in submit_selectors:
                try:
                    submit_button = self.page.locator(selector)
                    if submit_button.count() > 0:
                        logger.info(f"Clicking submit button with selector: {selector}")
                        submit_button.first.click()
                        submit_clicked = True
                        break
                except Exception:
                    continue
            
            if not submit_clicked:
                logger.warning("No submit button found, trying Enter key")
                pin_input.press("Enter")
            
            self.human_delay()
            self.page.wait_for_load_state("domcontentloaded", timeout=60000)
            
            # Check if login was successful
            new_url = self.page.url
            logger.info(f"After PIN submission, URL: {new_url}")
            
            if new_url.startswith("https://www.linkedin.com/feed/"):
                logger.info("PIN submission successful, logged in to feed")
                return True
            elif "/checkpoint/" not in new_url and "/login" not in new_url:
                # Might be on profile or other authenticated page
                if self.page.locator('img[alt*="Photo of"]').count() > 0:
                    logger.info("PIN submission successful, user photo visible")
                    return True
                if self.page.locator('[data-control-name="identity_welcome_message"]').count() > 0:
                    logger.info("PIN submission successful, welcome message visible")
                    return True
                # Check for nav bar (indicates logged in)
                if self.page.locator('#global-nav').count() > 0:
                    logger.info("PIN submission successful, global nav visible")
                    return True
            
            logger.error(f"PIN submission may have failed, current URL: {new_url}")
            return False
                
        except Exception as e:
            logger.error(f"Error submitting PIN: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def _scrape_safe_text(self, locator) -> Optional[str]:
        try:
            if locator.count() == 0:
                return None
            text = locator.first.inner_text().strip()
            return text or None
        except Exception:
            return None

    def _scrape_first_text(self, root: Locator, selectors: list[str]) -> Optional[str]:
        for selector in selectors:
            text = self._scrape_safe_text(root.locator(selector))
            if text:
                return text
        return None

    def _extract_visible_lines(self, locator) -> list[str]:
        try:
            raw_text = locator.inner_text()
        except Exception:
            return []
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        return lines

    def _go_to_next_search_page(self) -> bool:
        if not self.page:
            return False
        next_selectors = [
            "button[aria-label='Next']",
            "button.artdeco-pagination__button--next",
            "section.artdeco-pagination button.artdeco-pagination__button--next",
        ]
        for selector in next_selectors:
            locator = self.page.locator(selector)
            if locator.count() == 0:
                continue
            button = locator.first
            try:
                button.wait_for(state="visible", timeout=5000)
            except Exception:
                continue
            try:
                button.scroll_into_view_if_needed()
            except Exception:
                pass
            is_disabled = False
            try:
                if button.is_disabled():
                    is_disabled = True
            except Exception:
                pass
            if not is_disabled:
                aria_disabled = button.get_attribute("aria-disabled")
                class_attr = button.get_attribute("class") or ""
                if aria_disabled == "true" or "disabled" in class_attr:
                    is_disabled = True
            if is_disabled:
                continue
            try:
                button.click()
                self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                self.page.wait_for_selector("main li, div[role='listitem']", timeout=15000)
                self.page.wait_for_timeout(500)
                self._detect_captcha_or_logout()
                return True
            except Exception as exc:
                logger.warning(f"Pagination click failed ({selector}): {exc}")
        return False

    def _detect_captcha_or_logout(self):
        if not self.page:
            return
        try:
            if "captcha" in self.page.url.lower():
                raise LinkedInCaptchaError("LinkedIn presented a captcha challenge.")

            captcha_indicators = [
                "iframe[src*='captcha']",
                "img[src*='captcha']",
                "div:has-text(\"Let's confirm that you are human\")",
                "div:has-text('Security verification')",
                "div:has-text('unusual activity')",
            ]
            for selector in captcha_indicators:
                locator = self.page.locator(selector)
                if locator.count() > 0 and locator.first.is_visible():
                    raise LinkedInCaptchaError("LinkedIn presented a captcha challenge.")

            if self.page.url.startswith("https://www.linkedin.com/checkpoint/"):
                raise LinkedInAuthError("LinkedIn requested additional verification.")

            if "login" in self.page.url and self.page.locator('input[name="session_key"]').count() > 0:
                raise LinkedInAuthError("LinkedIn session expired; login required.")
        except LinkedInServiceError:
            raise
        except Exception:
            # Best-effort detection; swallow unexpected errors.
            return

    def _solve_recaptcha_if_present(self) -> bool:
        if not self.captcha_solver or not self.captcha_solver.is_configured:
            return False
        try:
            captcha_iframe = self.page.locator("iframe[src*='recaptcha'], iframe[src*='gstatic.com/recaptcha']")
            captcha_div = self.page.locator(".g-recaptcha, div[data-sitekey]")
            has_captcha = captcha_iframe.count() > 0 or captcha_div.count() > 0
        except Exception:
            has_captcha = False

        if not has_captcha:
            return False

        site_key = None
        try:
            site_key = self.page.evaluate(
                """() => {
                    const explicit = document.querySelector('[data-sitekey]');
                    if (explicit && explicit.getAttribute('data-sitekey')) {
                        return explicit.getAttribute('data-sitekey');
                    }
                    const iframe = document.querySelector('iframe[src*="recaptcha"]');
                    if (iframe) {
                        try {
                            const url = new URL(iframe.src);
                            return url.searchParams.get('k') || url.searchParams.get('sitekey') || url.searchParams.get('render');
                        } catch (err) {
                            return null;
                        }
                    }
                    return null;
                }"""
            )
        except Exception:
            site_key = None

        if not site_key:
            logger.warning("Detected reCAPTCHA but could not find site key; skipping solver.")
            return False

        logger.info("Detected reCAPTCHA on LinkedIn login; attempting automated solve.")
        solved = self.captcha_solver.solve_recaptcha_v2(self.page, site_key, self.page.url)
        if solved:
            self.human_delay(1, 2)
        return solved

    def _reset_checkpoint_context(self) -> None:
        """Clear any cached checkpoint context."""
        self.last_checkpoint_context = None

    def _capture_checkpoint_context(self) -> Dict[str, Any]:
        """
        Snapshot the current checkpoint DOM so downstream services can surface
        the exact message LinkedIn is showing to the user.
        """
        context: Dict[str, Any] = {
            "url": self.page.url if self.page else None,
        }

        def _first_text(selector: str) -> Optional[str]:
            if not self.page:
                return None
            try:
                locator = self.page.locator(selector)
                if locator.count() > 0:
                    text = locator.first.inner_text().strip()
                    if text:
                        return text
            except Exception:
                return None
            return None

        try:
            context["title"] = self.page.title()
        except Exception:
            context["title"] = None

        headline = _first_text("main h1, section h1, h1, h2")
        context["headline"] = headline

        subhead = _first_text("main p, section p, p")
        context["subheadline"] = subhead

        body_text = None
        if self.page:
            try:
                body_text = self.page.text_content("main", timeout=1500)
            except Exception:
                try:
                    body_text = self.page.text_content("body", timeout=1500)
                except Exception:
                    body_text = None
        if body_text:
            body_text = body_text.strip()
        context["body"] = body_text

        # Primary message surfaced to users (prefer headline/subheadline)
        for candidate_key in ("headline", "subheadline", "body"):
            value = context.get(candidate_key)
            if value:
                context["message"] = value.strip()
                break
        else:
            context["message"] = None

        if self.page:
            try:
                raw_html = self.page.inner_html("main", timeout=1500)
            except Exception:
                try:
                    raw_html = self.page.inner_html("body", timeout=1500)
                except Exception:
                    raw_html = None
            if raw_html:
                context["html"] = raw_html[:8000]
            else:
                context["html"] = None
        else:
            context["html"] = None

        self.last_checkpoint_context = context
        return context

    def get_last_checkpoint_context(self) -> Optional[Dict[str, Any]]:
        """Expose the most recent checkpoint snapshot for downstream services."""
        return self.last_checkpoint_context

    def _checkpoint_message(self, fallback: str) -> str:
        context = self.get_last_checkpoint_context() or {}
        message = context.get("message")
        if message:
            return message
        headline = context.get("headline")
        if headline:
            return headline
        return fallback

    def _detect_post_captcha_state(self) -> str:
        """
        Detect the current page state after login attempt or captcha solve.
        
        Returns:
            str: One of:
                - "logged_in": Successfully logged in (on feed or profile page)
                - "2fa_pin_required": 2FA PIN input page (user needs to enter code)
                - "2fa_app_approval": LinkedIn App approval page (user needs to approve on phone)
                - "account_restricted": Account is restricted/blocked
                - "unsupported_browser": Unsupported browser error page
                - "wrong_credentials": Invalid credentials error
                - "login_form": Still on login form (can retry submit)
                - "captcha_failed": Captcha solution was rejected
                - "unknown": Unknown state
        """
        self._reset_checkpoint_context()
        current_url = self.page.url
        logger.info(f"Detecting post-captcha state. URL: {current_url}")
        
        # Check for successful login
        if current_url.startswith("https://www.linkedin.com/feed/"):
            return "logged_in"
        
        # Check for profile photo (another indicator of successful login)
        try:
            if self.page.is_visible('img[alt*="Photo of"]', timeout=1000):
                return "logged_in"
        except:
            pass
        
        # Check for unsupported browser error
        if current_url.startswith("https://www.linkedin.com/error_pages/unsupported-browser"):
            return "unsupported_browser"
        
        # Check for checkpoint/challenge pages (need to distinguish between PIN and App approval)
        checkpoint_indicators = [
            "checkpoint" in current_url,
            "challenge" in current_url,
            "/checkpoint/" in current_url,
        ]
        
        if any(checkpoint_indicators):
            logger.info(f"Checkpoint URL detected: {current_url}")
            context = self._capture_checkpoint_context()
            
            # First, check if this is LinkedIn App Challenge (authenticator approval)
            # This page has title "LinkedIn App Challenge" and text "Check your LinkedIn app"
            try:
                page_title = self.page.title()
                page_text = self.page.text_content("body", timeout=2000) or ""
                page_text_lower = page_text.lower()
                
                # LinkedIn App Challenge indicators (push notification / authenticator app approval)
                app_approval_indicators = [
                    "linkedin app challenge" in page_title.lower(),
                    "check your linkedin app" in page_text_lower,
                    "open your linkedin app and tap yes" in page_text_lower,
                    "we sent a notification to your signed in devices" in page_text_lower,
                    "tap yes to confirm your sign-in" in page_text_lower,
                    "verify using authenticator app" in page_text_lower,
                ]
                
                if any(app_approval_indicators):
                    logger.info("LinkedIn App Challenge detected - user needs to approve on phone/app")
                    return "2fa_app_approval"
                    
            except Exception as e:
                logger.debug(f"Error checking app approval indicators: {e}")
            
            # Check for PIN input fields (traditional 2FA with code entry)
            twofa_input_selectors = [
                'input[name="pin"]',
                'input[id="input__phone_verification_pin"]',
                'input[id="input__email_verification_pin"]',
                'input[aria-label*="verification"]',
                'input[aria-label*="code"]',
                'input[type="text"][autocomplete="one-time-code"]',
            ]
            
            for selector in twofa_input_selectors:
                try:
                    if self.page.is_visible(selector, timeout=500):
                        logger.info(f"2FA PIN input detected: {selector}")
                        return "2fa_pin_required"
                except:
                    pass
            
            page_text_lower = ""
            if context.get("body"):
                page_text_lower = context["body"].lower()
            else:
                try:
                    raw_body = self.page.text_content("body", timeout=1500) or ""
                    page_text_lower = raw_body.lower()
                    context["body"] = raw_body.strip()
                except Exception:
                    page_text_lower = ""

            manual_verification_indicators = [
                "upload a photo",
                "upload a copy",
                "government-issued id",
                "confirm your identity",
                "secure your account",
                "suspicious activity",
                "provide additional verification",
                "help us verify",
                "take a photo",
                "scan of your id",
                "identity verification",
                "provide more information",
                "complete the following steps",
                "submit your information",
            ]

            for indicator in manual_verification_indicators:
                if indicator in page_text_lower:
                    logger.warning("Manual verification checkpoint detected - user action required.")
                    return "checkpoint_manual_verification"

            logger.info("Checkpoint detected but challenge type is unknown.")
            return "checkpoint_unknown"
        
        # Check for PIN input outside checkpoint URLs (rare but possible)
        twofa_input_selectors = [
            'input[name="pin"]',
            'input[id="input__phone_verification_pin"]',
            'input[id="input__email_verification_pin"]',
            'input[aria-label*="verification"]',
            'input[aria-label*="code"]',
        ]
        
        for selector in twofa_input_selectors:
            try:
                if self.page.is_visible(selector, timeout=500):
                    logger.info(f"2FA PIN input detected: {selector}")
                    return "2fa_pin_required"
            except:
                pass
        
        # Check for account restriction/security pages
        restriction_indicators = [
            "restricted" in current_url.lower(),
            "suspended" in current_url.lower(),
            "appeal" in current_url.lower(),
            "/security/" in current_url,
        ]
        
        if any(restriction_indicators):
            return "account_restricted"
        
        # Check page content for restriction messages
        try:
            page_text = self.page.text_content("body", timeout=2000) or ""
            page_text_lower = page_text.lower()
            
            restriction_texts = [
                "account has been restricted",
                "account is restricted",
                "temporarily restricted",
                "unusual activity",
                "suspicious activity",
                "verify your identity",
                "confirm your identity",
                "we've restricted your account",
            ]
            
            for text in restriction_texts:
                if text in page_text_lower:
                    logger.warning(f"Account restriction text found: {text}")
                    return "account_restricted"
            
            # Check for wrong credentials
            wrong_creds_texts = [
                "wrong email or password",
                "incorrect password",
                "couldn't find an account",
                "invalid credentials",
                "please check your email",
            ]
            
            for text in wrong_creds_texts:
                if text in page_text_lower:
                    logger.warning(f"Wrong credentials text found: {text}")
                    return "wrong_credentials"
            
            # Check for captcha rejection
            captcha_fail_texts = [
                "captcha verification failed",
                "please complete the security check",
                "verification unsuccessful",
            ]
            
            for text in captcha_fail_texts:
                if text in page_text_lower:
                    logger.warning(f"Captcha failure text found: {text}")
                    return "captcha_failed"
                    
        except Exception as e:
            logger.debug(f"Error reading page text: {e}")
        
        # Check if still on login form
        try:
            login_form_visible = (
                self.page.is_visible('input[name="session_key"]', timeout=500) and
                self.page.is_visible('input[name="session_password"]', timeout=500)
            )
            if login_form_visible:
                return "login_form"
        except:
            pass
        
        # Check for submit button (might still be on login page variant)
        try:
            if self.page.is_visible('button[type="submit"]', timeout=500):
                # Could be login form or some other form
                if "login" in current_url.lower():
                    return "login_form"
        except:
            pass
        
        logger.warning(f"Unknown page state. URL: {current_url}")
        return "unknown"

    def check_app_approval_status(self) -> dict:
        """
        Check the current state of app approval without waiting.
        
        Returns:
            dict with keys:
                - status: "approved" | "rejected" | "pending" | "expired" | "error"
                - message: Human-readable message
                - details: Optional additional info
        """
        if not self.is_alive():
            return {
                "status": "expired",
                "message": "Browser session has expired. Please start a new verification.",
            }
        
        try:
            current_url = self.page.url
            logger.info(f"[check_app_approval_status] Current URL: {current_url}")
            
            # Check if successfully logged in (user approved)
            if current_url.startswith("https://www.linkedin.com/feed/"):
                logger.info("[check_app_approval_status] User approved - redirected to feed")
                return {
                    "status": "approved",
                    "message": "Successfully authenticated! LinkedIn approved your sign-in.",
                }
            
            # Check for profile photo (another indicator of successful login)
            try:
                if self.page.is_visible('img[alt*="Photo of"]', timeout=1000):
                    logger.info("[check_app_approval_status] User approved - profile photo visible")
                    return {
                        "status": "approved",
                        "message": "Successfully authenticated!",
                    }
            except:
                pass
            
            # Check page content for rejection indicators
            try:
                page_text = self.page.text_content("body", timeout=2000) or ""
                page_text_lower = page_text.lower()
                
                # Rejection indicators
                rejection_indicators = [
                    "request denied",
                    "sign-in was not approved",
                    "you didn't approve",
                    "request was denied",
                    "sign in attempt blocked",
                    "didn't recognize",
                    "wasn't you",
                    "try again",  # Often shown after rejection
                ]
                
                for indicator in rejection_indicators:
                    if indicator in page_text_lower:
                        logger.warning(f"[check_app_approval_status] Rejection detected: {indicator}")
                        return {
                            "status": "rejected",
                            "message": "Sign-in request was denied. Please try again and approve on your LinkedIn app.",
                            "details": indicator
                        }
                
                # Still on approval page - check for approval indicators
                approval_page_indicators = [
                    "check your linkedin app",
                    "tap yes to confirm",
                    "we sent a notification",
                    "open your linkedin app",
                    "verify using authenticator",
                ]
                
                for indicator in approval_page_indicators:
                    if indicator in page_text_lower:
                        logger.info(f"[check_app_approval_status] Still pending - approval page visible")
                        return {
                            "status": "pending",
                            "message": "Waiting for approval. Please check your LinkedIn app and tap 'Yes'.",
                        }
                        
            except Exception as e:
                logger.debug(f"[check_app_approval_status] Error reading page text: {e}")
            
            # Check if still on checkpoint/challenge URL
            if "checkpoint" in current_url or "challenge" in current_url:
                # Might be pending or a different state
                state = self._detect_post_captcha_state()
                if state == "2fa_app_approval":
                    return {
                        "status": "pending",
                        "message": "Waiting for approval. Please check your LinkedIn app.",
                    }
                elif state == "2fa_pin_required":
                    return {
                        "status": "error",
                        "message": "LinkedIn is now asking for a PIN code instead. Please restart verification.",
                        "details": "state_changed_to_pin"
                    }
                elif state in ("checkpoint_manual_verification", "checkpoint_unknown"):
                    message = self._checkpoint_message("LinkedIn is asking for additional verification.")
                    return {
                        "status": "checkpoint_action_required",
                        "message": message,
                        "context": self.get_last_checkpoint_context(),
                    }
                elif state == "logged_in":
                    return {
                        "status": "approved",
                        "message": "Successfully authenticated!",
                    }
            
            # Unknown state
            logger.warning(f"[check_app_approval_status] Unknown state at URL: {current_url}")
            return {
                "status": "pending",
                "message": "Checking approval status...",
            }
            
        except Exception as e:
            logger.error(f"[check_app_approval_status] Error: {e}")
            return {
                "status": "error",
                "message": f"Error checking approval status: {str(e)}",
            }

    def wait_for_app_approval(self, timeout_seconds: int = 120, poll_interval: float = 2.0) -> dict:
        """
        Wait for the user to approve or reject the sign-in request on their LinkedIn app.
        
        Args:
            timeout_seconds: Maximum time to wait for approval
            poll_interval: Time between status checks
            
        Returns:
            dict with keys:
                - status: "approved" | "rejected" | "timeout" | "error"
                - message: Human-readable message
        """
        import time
        start_time = time.time()
        
        logger.info(f"[wait_for_app_approval] Starting to wait for approval (timeout: {timeout_seconds}s)")
        
        while time.time() - start_time < timeout_seconds:
            result = self.check_app_approval_status()
            
            if result["status"] == "approved":
                logger.info("[wait_for_app_approval] Approval detected!")
                return result
            elif result["status"] == "rejected":
                logger.warning("[wait_for_app_approval] Rejection detected!")
                return result
            elif result["status"] == "expired":
                logger.warning("[wait_for_app_approval] Session expired!")
                return result
            elif result["status"] == "error":
                if result.get("details") == "state_changed_to_pin":
                    return result
                # For other errors, continue waiting
                logger.debug(f"[wait_for_app_approval] Error during check: {result['message']}")
            elif result["status"] == "checkpoint_action_required":
                logger.warning("[wait_for_app_approval] Manual checkpoint action required.")
                return result
            
            # Still pending - wait and retry
            time.sleep(poll_interval)
        
        logger.warning(f"[wait_for_app_approval] Timeout after {timeout_seconds}s")
        return {
            "status": "timeout",
            "message": f"Approval not received within {timeout_seconds} seconds. Please try again.",
        }

    def _ensure_login_form_visible(self) -> None:
        try:
            self.page.wait_for_selector('input[name="session_key"]', timeout=15000)
            self.page.wait_for_selector('input[name="session_password"]', timeout=15000)
            return
        except PlaywrightTimeoutError:
            logger.warning("LinkedIn login inputs not visible; checking for captcha.")
            if self._solve_recaptcha_if_present():
                try:
                    self.page.wait_for_selector('input[name="session_key"]', timeout=10000)
                    self.page.wait_for_selector('input[name="session_password"]', timeout=10000)
                    logger.info("Login form became visible after solving captcha.")
                    return
                except PlaywrightTimeoutError:
                    logger.error(
                        "Login inputs still missing after captcha solve. Current URL: %s",
                        self.page.url,
                    )
                    raise LinkedInCaptchaError(
                        "LinkedIn blocked login (captcha/verification required)."
                    )
            current_url = self.page.url
            logger.error(
                "Unable to locate LinkedIn login inputs (url=%s).", current_url
            )
            raise LinkedInCaptchaError(
                "LinkedIn presented a checkpoint or captcha; manual verification required."
            )

    def scrape_search_results(
        self,
        search_url: str,
        *,
        max_results: int = 50,
        scroll_delay_range: tuple[float, float] = (1.5, 3.0),
    ) -> list[LinkedInSearchLead]:
        """
        Scrape LinkedIn search (people) results and return normalized profile leads.

        Args:
            search_url: LinkedIn search URL (e.g. https://www.linkedin.com/search/results/people/...)
            max_results: Max number of leads to return.
            scroll_delay_range: Range of delays in seconds between scrolls to avoid rate limiting.

        Raises:
            LinkedInAuthError: Session is not authenticated.
            LinkedInCaptchaError: Captcha or checkpoint encountered.
            LinkedInSearchEmptyError: No people results found.
            LinkedInSearchError: Generic scraping failure.
        """
        if max_results <= 0:
            raise ValueError("max_results must be positive.")

        if not self.is_alive():
            raise LinkedInSearchError("Browser session is not active. Call login() before scraping.")

        if not self.page:
            raise LinkedInSearchError("Playwright page is not initialized.")

        logger.info("Navigating to LinkedIn search URL for lead import.")
        try:
            self.page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        except PlaywrightError as exc:
            raise LinkedInSearchError(f"Failed to load search URL: {exc}") from exc

        self._detect_captcha_or_logout()

        leads: list[LinkedInSearchLead] = []
        seen_urls: set[str] = set()

        # LinkedIn occasionally shows an empty state message.
        empty_selectors = [
            "div:has-text('No results found')",
            "div:has-text('Try adjusting your search')",
            "div:has-text('No results for your query')",
        ]

        for selector in empty_selectors:
            locator = self.page.locator(selector)
            if locator.count() > 0 and locator.first.is_visible():
                raise LinkedInSearchEmptyError("LinkedIn search returned no results.")

        # Scroll and collect results until we reach max_results or no more new entries appear.
        stagnant_iterations = 0
        processed_indices = set()
        scrolls_per_page_limit = 25
        scrolls_remaining = scrolls_per_page_limit

        # LinkedIn keeps changing class names, so rely on role/structure and href filters
        try:
            self.page.wait_for_selector("main li", timeout=15000)
        except Exception:
            logger.debug("Result list selector timeout; continuing with best-effort scraping.")

        base_locator = self.page.locator(
            "li.reusable-search__result-container, main li, div[role='listitem']"
        )
        result_locator = base_locator.filter(has=self.page.locator("a[href*='/in/']"))

        while len(leads) < max_results:
            self._detect_captcha_or_logout()

            try:
                total_results = result_locator.count()
            except Exception as exc:
                raise LinkedInSearchError(f"Failed to read search results: {exc}") from exc

            new_entries_found = False

            for index in range(total_results):
                if index in processed_indices:
                    continue

                processed_indices.add(index)
                item = result_locator.nth(index)

                link_locator = item.locator("a[href*='/in/']")
                link_count = link_locator.count()
                profile_href = None

                for link_index in range(link_count):
                    href = link_locator.nth(link_index).get_attribute("href")
                    if not href:
                        continue
                    if "/in/" not in href:
                        continue
                    if href.startswith("http"):
                        profile_href = href
                    else:
                        profile_href = f"https://www.linkedin.com{href if href.startswith('/') else '/' + href}"
                    break

                if not profile_href:
                    continue

                normalized_url = self._normalize_profile_url(profile_href)
                if not normalized_url or normalized_url in seen_urls:
                    continue

                fallback_lines = self._extract_visible_lines(item)

                name = self._scrape_first_text(
                    item,
                    [
                        "span.entity-result__title-text span[aria-hidden='true']",
                        "span.entity-result__title-text",
                        "div[role='heading'] span[aria-hidden='true']",
                        "div[role='heading'] span",
                        "[data-test-search-result-title]",
                    ],
                )
                if not name and link_locator.count() > 0:
                    name = self._scrape_safe_text(link_locator.first)

                headline = self._scrape_first_text(
                    item,
                    [
                        "div.entity-result__primary-subtitle",
                        "span[data-test-search-result-subline]",
                        "div:has-text('Current:') span[aria-hidden='true']",
                        "div:has-text('Current:')",
                    ],
                )
                if not headline:
                    headline = next(
                        (line for line in fallback_lines if line.lower().startswith("current:")),
                        None,
                    )

                location = self._scrape_first_text(
                    item,
                    [
                        "div.entity-result__secondary-subtitle",
                        "span[data-test-search-result-location]",
                    ],
                )
                if not location:
                    for line in fallback_lines:
                        lowered = line.lower()
                        if lowered.startswith("current:"):
                            continue
                        if "connect" in lowered or "mutual connection" in lowered:
                            continue
                        if name and line.startswith(name):
                            continue
                        if "•" in line:
                            continue
                        if (
                            "," in line
                            or "united" in lowered
                            or "area" in lowered
                            or "region" in lowered
                        ):
                            location = line
                            break

                leads.append(
                    LinkedInSearchLead(
                        url=normalized_url,
                        name=name,
                        headline=headline,
                        location=location,
                    )
                )
                seen_urls.add(normalized_url)
                new_entries_found = True

                if len(leads) >= max_results:
                    break

            if len(leads) >= max_results:
                break

            if not new_entries_found:
                stagnant_iterations += 1
            else:
                stagnant_iterations = 0

            if len(leads) >= max_results:
                break

            if scrolls_remaining <= 0 or stagnant_iterations >= 3:
                logger.info("No new leads after scrolling; attempting to load next page.")
                paged = self._go_to_next_search_page()
                if paged:
                    processed_indices.clear()
                    scrolls_remaining = scrolls_per_page_limit
                    stagnant_iterations = 0
                    continue
                logger.info("No additional pages available; stopping pagination.")
                break

            scroll_delay = random.uniform(*scroll_delay_range)
            logger.info(
                f"Collected {len(leads)} leads so far. Scrolling for more (delay {scroll_delay:.2f}s)."
            )

            try:
                self.page.mouse.wheel(0, 2500)
                self.page.wait_for_timeout(int(scroll_delay * 1000))
                scrolls_remaining -= 1
            except Exception:
                # If scrolling fails, break but keep collected leads.
                break

        if not leads:
            raise LinkedInSearchEmptyError("LinkedIn search returned no people profiles.")

        if len(leads) > max_results:
            leads = leads[:max_results]

        logger.info(f"Scraped {len(leads)} LinkedIn leads from search results.")
        return leads

    def goto_profile(self, profile_url: str) -> Page | bool:
        """
        Go to target profile page - returns that page, or False if unsuccessful
        """
        normalized = self._normalize_profile_url(profile_url) or profile_url
        normalized = self._append_locale_param(normalized)
        self.current_profile_url = normalized

        # Visit profile URL
        self.page.goto(normalized, wait_until="domcontentloaded")

        # Handle LinkedIn Authwall redirect
        if "linkedin.com/authwall" in self.page.url:
            logger.warning("Hit authwall, trying to bypass...")

            # Try to click "Sign in" / "Continue"
            try:
                btn = self.page.locator("button:has-text('Sign in'), a:has-text('Sign in'), button:has-text('Continue')")
                btn.first.scroll_into_view_if_needed()
                btn.first.click()
                self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                if self.page.url.startswith("https://www.linkedin.com/in/"):
                    logger.info("Bypassed authwall")
                    return self.page
                if "linkedin.com/authwall" in self.page.url:
                    logger.warning("Still on authwall...")
                    if self.page.locator("h1:has-text('Join Linkedin')").count() > 0:
                        logger.info("Detected Join Linkedin prompt.")
                        sign_in_btn = self.page.locator("button:has-text('Sign in'), a:has-text('Sign in')")
                        sign_in_btn.first.scroll_into_view_if_needed()
                        sign_in_btn.first.click()
                        self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                        if self.page.locator("h1:has-text('Sign in')").count() > 0:
                            logger.info("Detected Sign in prompt.")
                            self.page.fill('input[name="session_key"]', self.email)
                            self.human_delay()
                            self.page.fill('input[name="session_password"]', self.password)
                            self.human_delay()
                            self.page.click('button[type="submit"]', has_text="Sign in")
                            self.human_delay()
                            self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                            if self.page.url.startswith("https://www.linkedin.com/in/"):
                                logger.info("Bypassed authwall")
                                return self.page
                    else:
                        logger.warning("Different authwall scenario...")
                        return False

                # Welcome screen - redirect to linkedin.com
                if "linkedin.com" in self.page.url:
                    welcome_text = self.page.locator("h1").first
                    if welcome_text.count() == 0:
                        logger.error("Login redirect:Welcome text not found...")
                        return False
                    welcome_text_content = welcome_text.text_content()
                    if "Welcome to your professional community" in welcome_text_content:
                        logger.info("Login redirect: Detected welcome screen, trying to click 'Sign in as'...")
                        sign_in_as_link = self.page.locator(("a[href='https://www.linkedin.com/login']")).first
                        if sign_in_as_link:
                            sign_in_as_link.click()
                            self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                            if self.page.url.startswith("https://www.linkedin.com/in/"):
                                logger.info("Bypassed authwall")
                                return self.page
            except Exception as e:
                logger.error(f"Could not bypass authwall: {e}")

        return self.page
    
    def fetch_profile_info(self, profile_url: str) -> dict[str, Any] | None:
        """
        Get target profile information - name, title, location, about
        """
        normalized_url = self._normalize_profile_url(profile_url)
        profile_data: dict[str, Any] = {"profile_url": normalized_url}

        self.goto_profile(profile_url)
        self.human_delay()

        top_card = None

        # --- Top card: Name, Lastname, Title, Location ---
        try:
            top_card = self._find_top_card()
            if not top_card:
                raise RuntimeError("Top card locator not found")

            full_name = self._extract_text_from_selectors(top_card, ["h1", "h1 span"])
            if full_name:
                name_parts = full_name.strip().split()
                profile_data["name"] = name_parts[0]
                profile_data["lastname"] = " ".join(name_parts[1:]) if len(name_parts) > 1 else None
            else:
                profile_data["name"] = None
                profile_data["lastname"] = None

            title_text = self._extract_text_from_selectors(
                top_card,
                [
                    "div.text-body-medium.break-words",
                    "div[data-test-profile-subheadline]",
                    "div.text-body-medium",
                    "div.mt2 ul li",
                ],
            )
            profile_data["title"] = title_text

            location_text = self._extract_text_from_selectors(
                top_card,
                [
                    "span.text-body-small.inline.t-black--light.break-words",
                    "span[data-test-profile-location]",
                    "span.text-body-small",
                    "div.pv-top-card--list li.t-16.t-black.t-normal",
                ],
            )
            profile_data["location"] = location_text
            logger.info("Top card info added...")
        except Exception as exc:
            logger.warning(f"Top card info not found: {exc}")

        # --- About Section ---
        try:
            about_area = self.page.locator(
                "section.artdeco-card.pv-profile-card",
            ).filter(has=self.page.locator("h2.pvs-header__title >> span.visually-hidden", has_text="About")).first
            about_area_narrow = about_area.locator("span.visually-hidden")
            profile_data["about"] = about_area_narrow.nth(1).inner_text()
            logger.info("About section added...")
        except Exception:
            logger.warning("About section not found...")

        # --- Connection / Message / Pending Buttons ---
        try:
            status_root = top_card or self.page
            connect_selectors = [
                "button[aria-label*='Invite to connect']",
                "button:has-text('Connect')",
                "button[data-control-name*='connect']",
                "button[data-view-name*='connect']",
                "div[data-view-name*='edge-creation-connect-action'] button",
                "button:has-text('Collegati')",
                "button:has-text('Connetti')",
                "button[aria-label*='Collegati']",
                "button[aria-label*='Connetti']",
                "a[href*='/preload/custom-invite']",
                "a[aria-label*='Invite to connect']",
                "a[aria-label*='Collegati']",
                "a[aria-label*='Connetti']",
            ]
            connect_btn = status_root.locator(", ".join(connect_selectors))

            message_selectors = [
                "a[data-view-name='profile-primary-message']",
                "button[data-view-name='profile-primary-message']",
                "button:has-text('Message')",
                "button:has-text('Messaggio')",
                "button:has-text('Invia messaggio')",
                "button[aria-label*='Message']",
                "button[aria-label*='Messaggio']",
                "button[aria-label*='Invia messaggio']",
                "button[data-control-name*='message']",
                "button[data-view-name*='message']",
                "div[data-view-name*='message'] button",
                "div[data-view-name*='message'] a",
                "a[aria-label*='Message']",
                "a[aria-label*='Messaggio']",
                "a[aria-label*='Invia messaggio']",
                "a[data-control-name*='message']",
                "a[data-view-name*='message']",
                "a[data-view-name='profile-secondary-message']",
                "a[href^='/messaging/compose']",
                "a[href*='/messaging/']",
                "span:has-text('Message')",
                "span:has-text('Messaggio')",
            ]
            message_btn = None
            for sel in message_selectors:
                candidate = status_root.locator(sel).first
                if candidate.count() > 0:
                    message_btn = candidate
                    break

            pending_selectors = [
                "button:has-text('Pending')",
                "button[aria-label*='Pending']",
                "button[data-control-name*='pending']",
                "a[data-control-name*='pending']",
                "button:has-text('In attesa')",
                "button:has-text('Richiesta inviata')",
                "button[aria-label*='In attesa']",
                "button[aria-label*='Richiesta inviata']",
            ]
            pending_btn = status_root.locator(", ".join(pending_selectors))

            more_dropdown = status_root.locator('[id*="ember"].artdeco-dropdown')
            texts: list[str] = []
            if more_dropdown.count() > 0:
                list_items = more_dropdown.locator('[aria-hidden="true"] ul li')
                try:
                    texts = [text.strip() for text in list_items.all_text_contents()]
                except Exception:
                    texts = []

            for text in texts:
                lowered = text.lower()
                if "remove connection" in lowered or "rimuovi connessione" in lowered:
                    profile_data["connected"] = True
                    profile_data["connection_pending"] = False
                    break
                if "pending" in lowered or "in attesa" in lowered or "richiesta inviata" in lowered:
                    profile_data["connection_pending"] = True
                    profile_data["connected"] = False
                    break
                if "connect" in lowered or "collegati" in lowered or "connetti" in lowered:
                    profile_data["connected"] = False

            connect_count = connect_btn.count() if connect_btn else 0
            pending_count = pending_btn.count() if pending_btn else 0
            message_present = message_btn is not None
            follow_present = self._has_follow_button([status_root])
            follow_only = False

            if connect_count > 0:
                profile_data["connected"] = False
            if pending_count > 0:
                profile_data["connection_pending"] = True
                profile_data["connected"] = False
            if (
                message_present
                and connect_count == 0
                and not profile_data.get("connection_pending")
                and not follow_present
            ):
                profile_data["connected"] = True

            if (
                follow_present
                and connect_count == 0
                and not profile_data.get("connection_pending")
                and not profile_data.get("connected")
            ):
                follow_only = True
                profile_data["connected"] = False

            profile_data["follow_only"] = follow_only

            logger.info("Profile status data added...")
        except Exception as exc:
            logger.error(f"Error during profile status data extraction: {exc}")

        if "connected" not in profile_data:
            profile_data["connected"] = None
        if "connection_pending" not in profile_data:
            profile_data["connection_pending"] = None
        if "follow_only" not in profile_data:
            profile_data["follow_only"] = False

        return profile_data

    def fetch_contact_info(self, profile_url: str) -> dict[str, Any]:
        """
        Fetch and normalize contact info from a LinkedIn profile.
        """
        logger.info(f"Fetching contact info for {profile_url}")

        if not self.is_alive():
            raise LinkedInServiceError("Browser session is not active. Call login() before fetching contact info.")

        self.goto_profile(profile_url)
        self.human_delay()
        self._detect_captcha_or_logout()

        if not self._open_contact_info_modal():
            logger.info(f"Contact info modal not available for {profile_url}")
            return {"raw_sections": [], "normalized": {}, "modal_html": None}

        try:
            self.page.wait_for_selector("section.pv-contact-info__contact-type", timeout=10000)
        except PlaywrightError as exc:
            logger.warning(f"Contact info sections not found for {profile_url}: {exc}")

        sections = self._collect_contact_sections()
        normalized = self._normalize_contact_sections(sections)
        modal_html = self._get_contact_modal_html()
        self._close_contact_info_modal()

        return {
            "raw_sections": sections,
            "normalized": normalized,
            "modal_html": modal_html,
        }

    def _open_contact_info_modal(self) -> bool:
        try:
            self.page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            logger.debug("Unable to scroll to top before opening contact info", exc_info=True)

        overlay_url = self._build_contact_overlay_url(self.current_profile_url)

        selectors = [
            'a[data-control-name="contact_see_more"]',
            'button[data-control-name="contact_see_more"]',
            'a[href*="overlay/contact-info"]',
            'button[href*="overlay/contact-info"]',
            "a:has-text('Contact info')",
            "button:has-text('Contact info')",
            "div[role='button']:has-text('Contact info')",
            "span:has-text('Contact info')",
            "a:has-text('Informazioni di contatto')",
            "button:has-text('Informazioni di contatto')",
            "div[role='button']:has-text('Informazioni di contatto')",
            "span:has-text('Informazioni di contatto')",
        ]

        target_selectors = [
            "div.artdeco-modal",
            "div[data-view-name='profile-contact-info-details-view']",
            "dialog[data-testid='dialog']",
        ]

        def wait_for_overlay() -> bool:
            try:
                self.page.wait_for_selector(", ".join(target_selectors), timeout=10000)
                return True
            except Exception:
                return False

        if overlay_url:
            try:
                logger.info("Opening contact info via overlay URL: %s", overlay_url)
                overlay_target = self._append_locale_param(overlay_url)
                self.page.goto(overlay_target or overlay_url, wait_until="networkidle")
                self.human_delay(1, 2)
                self._detect_captcha_or_logout()
                if wait_for_overlay():
                    return True
            except Exception:
                logger.debug("Direct overlay navigation failed", exc_info=True)
            finally:
                if self.current_profile_url:
                    try:
                        self.page.goto(self.current_profile_url, wait_until="domcontentloaded")
                        self.human_delay(0.5, 1.5)
                    except Exception:
                        logger.debug("Failed to return to profile after overlay attempt", exc_info=True)

        for selector in selectors:
            locator = self.page.locator(selector)
            if locator.count() == 0:
                continue
            try:
                locator.first.click()
                self.human_delay()
                self._detect_captcha_or_logout()
                if wait_for_overlay():
                    return True
            except Exception as exc:
                logger.debug(f"Failed to open contact info modal with selector {selector}: {exc}")

        text_variants = [
            "Contact info",
            "Contact Info",
            "Informazioni di contatto",
            "Informazioni sui contatti",
        ]
        for text_value in text_variants:
            try:
                text_locator = self.page.get_by_text(text_value, exact=False)
                if text_locator.count() == 0:
                    continue
                locator = text_locator.first
                locator.scroll_into_view_if_needed(timeout=3000)
                locator.click()
                self.human_delay()
                self._detect_captcha_or_logout()
                if wait_for_overlay():
                    return True
            except Exception:
                logger.debug("Failed to open contact modal via text locator '%s'", text_value, exc_info=True)

        # Fallback to role-based queries (handles translated text/aria-labels)
        try:
            role_locator = self.page.get_by_role("link", name=re.compile("contact info", re.IGNORECASE))
            if role_locator.count() > 0:
                role_locator.first.click()
                self.human_delay()
                self._detect_captcha_or_logout()
                if wait_for_overlay():
                    return True
        except Exception:
            logger.debug("Contact info link via role locator not found", exc_info=True)

        try:
            role_button = self.page.get_by_role(
                "button",
                name=re.compile("contact info|informazioni di contatto", re.IGNORECASE),
            )
            if role_button.count() > 0:
                role_button.first.click()
                self.human_delay()
                self._detect_captcha_or_logout()
                if wait_for_overlay():
                    return True
        except Exception:
            logger.debug("Contact info button via role locator not found", exc_info=True)

        return False

    def _build_contact_overlay_url(self, profile_url: Optional[str]) -> Optional[str]:
        normalized = self._normalize_profile_url(profile_url)
        if not normalized:
            return None
        return f"{normalized}/overlay/contact-info/"

    def _collect_contact_sections(self) -> list[dict[str, Any]]:
        sections_data: list[dict[str, Any]] = []
        section_locator = self.page.locator("section.pv-contact-info__contact-type")
        count = section_locator.count()

        if count == 0:
            overlay_sections = self._collect_contact_sections_overlay()
            if overlay_sections:
                return overlay_sections
            return sections_data

        for idx in range(count):
            section = section_locator.nth(idx)
            label = self._scrape_safe_text(section.locator("header h3, h3, h2"))
            entries: list[dict[str, Any]] = []
            seen_values: set[str] = set()

            link_locator = section.locator("a")
            for link_index in range(link_locator.count()):
                anchor = link_locator.nth(link_index)
                try:
                    text = (anchor.inner_text() or "").strip()
                except Exception:
                    text = ""
                href = anchor.get_attribute("href")
                entry_type = (
                    anchor.get_attribute("data-field")
                    or anchor.get_attribute("data-control-name")
                    or anchor.get_attribute("data-tracking-control-name")
                )

                if text or href:
                    key = f"{text}|{href}"
                    if key not in seen_values:
                        seen_values.add(key)
                        entries.append({"text": text, "href": href, "type": entry_type})

            text_locator = section.locator("span, time, p")
            for text_index in range(text_locator.count()):
                try:
                    text_value = (text_locator.nth(text_index).inner_text() or "").strip()
                except Exception:
                    text_value = ""
                if not text_value:
                    continue
                if any(text_value == entry.get("text") for entry in entries):
                    continue
                entries.append({"text": text_value, "href": None, "type": None})

            if entries:
                sections_data.append({"label": label or "Unknown", "entries": entries})

        return sections_data

    def _collect_contact_sections_overlay(self) -> list[dict[str, Any]]:
        try:
            data = self.page.evaluate(
                """
                () => {
                    const container = document.querySelector('div[data-view-name="profile-contact-info-details-view"]');
                    if (!container) return null;
                    const seen = new Set();
                    const result = [];

                    const blocks = container.querySelectorAll('[data-testid="lazy-column"] div');
                    blocks.forEach((block) => {
                        const labelEl = block.querySelector('p');
                        if (!labelEl) return;
                        const label = (labelEl.textContent || '').trim();
                        if (!label) return;

                        const entries = [];
                        const anchors = block.querySelectorAll('a');
                        anchors.forEach((link) => {
                            const text = (link.textContent || '').trim();
                            const href = link.getAttribute('href');
                            const key = `${label}|${text}|${href || ''}`;
                            if (seen.has(key)) return;
                            seen.add(key);
                            entries.push({ text, href, type: null });
                        });

                        if (!entries.length) {
                            const paragraphs = block.querySelectorAll('p');
                            paragraphs.forEach((p, idx) => {
                                if (idx === 0) return;
                                const text = (p.textContent || '').trim();
                                if (!text) return;
                                const key = `${label}|${text}`;
                                if (seen.has(key)) return;
                                seen.add(key);
                                entries.push({ text, href: null, type: null });
                            });
                        }

                        if (entries.length) {
                            result.push({ label, entries });
                        }
                    });

                    return result;
                }
                """
            )
        except Exception:
            logger.debug("Failed collecting contact info from overlay view", exc_info=True)
            return []

        sections: list[dict[str, Any]] = []
        if not data:
            return sections

        for section in data:
            label = self._clean_text(section.get("label"))
            entries_data = section.get("entries") or []
            cleaned_entries: list[dict[str, Any]] = []
            for entry in entries_data:
                text = self._clean_text(entry.get("text"))
                href = entry.get("href")
                entry_type = entry.get("type")
                if not text and not href:
                    continue
                cleaned_entries.append({"text": text, "href": href, "type": entry_type})
            if cleaned_entries:
                sections.append({"label": label or "Unknown", "entries": cleaned_entries})
        return sections

    def _normalize_contact_sections(self, sections: list[dict[str, Any]]) -> dict[str, Any]:
        normalized: dict[str, Any] = {
            "emails": [],
            "phones": [],
            "websites": [],
            "addresses": [],
            "messaging": [],
        }
        primary_email: str | None = None
        birthday_value: str | None = None

        for section in sections:
            label = (section.get("label") or "").lower()
            entries = section.get("entries", [])

            if "email" in label:
                for entry in entries:
                    email = self._extract_email(entry)
                    if email:
                        normalized["emails"].append({"value": email, "label": section.get("label")})
                        if not primary_email:
                            primary_email = email
            elif "phone" in label or "mobile" in label:
                for entry in entries:
                    phone = self._extract_phone(entry)
                    if phone:
                        normalized["phones"].append(phone)
            elif "website" in label or "url" in label:
                for entry in entries:
                    website = self._extract_website(entry)
                    if website:
                        normalized["websites"].append(website)
            elif "address" in label or "location" in label:
                for entry in entries:
                    cleaned = self._clean_text(entry.get("text"))
                    if cleaned:
                        normalized["addresses"].append({"value": cleaned, "label": section.get("label")})
            elif "birthday" in label:
                for entry in entries:
                    if entry.get("text"):
                        birthday_value = entry["text"].strip()
            elif any(keyword in label for keyword in ("messaging", "twitter", "wechat", "signal")):
                for entry in entries:
                    messaging = self._extract_messaging(entry, section.get("label"))
                    if messaging:
                        normalized["messaging"].append(messaging)
            else:
                other_entries = normalized.setdefault("other", {})
                other_entries[section.get("label") or "Other"] = entries

        if normalized["emails"]:
            normalized["primary_email"] = primary_email
        if birthday_value:
            normalized["birthday"] = birthday_value

        compact_normalized = {
            key: value for key, value in normalized.items() if value not in (None, [], {})
        }
        return compact_normalized

    def _get_contact_modal_html(self) -> str | None:
        try:
            modal = self.page.locator("div.artdeco-modal").first
            if modal:
                return modal.inner_html()
        except Exception:
            logger.debug("Unable to capture contact info modal HTML", exc_info=True)
        return None

    def _close_contact_info_modal(self) -> None:
        try:
            close_button = self.page.locator("button[aria-label='Dismiss'], button[aria-label='Close']")
            if close_button.count() > 0:
                close_button.first.click()
                self.human_delay(0.5, 1.5)
            else:
                self.page.keyboard.press("Escape")
                self.human_delay(0.5, 1.0)
        except Exception:
            logger.debug("Failed to close contact info modal cleanly", exc_info=True)

    def _extract_email(self, entry: dict[str, Any]) -> str | None:
        text = entry.get("text") or ""
        href = entry.get("href") or ""
        candidate = ""
        if href and href.lower().startswith("mailto:"):
            candidate = href.split("mailto:", 1)[1]
        elif text:
            candidate = text
        candidate = candidate.split("?")[0].strip()
        if candidate and "@" in candidate:
            return candidate
        return None

    def _extract_phone(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        text = entry.get("text") or ""
        cleaned = re.sub(r"[^\d+]", "", text)
        if not cleaned:
            return None
        return {"value": cleaned, "raw": text.strip(), "label": entry.get("type") or entry.get("text")}

    def _extract_website(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        href = entry.get("href")
        text = self._clean_text(entry.get("text"))
        if not href and not text:
            return None
        return {"url": href or text, "label": entry.get("type") or entry.get("text")}

    def _extract_messaging(self, entry: dict[str, Any], label: str | None) -> dict[str, Any] | None:
        text = self._clean_text(entry.get("text"))
        href = entry.get("href")
        if not text and not href:
            return None
        return {"handle": text, "url": href, "label": label}

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip()
        return cleaned or None

    # ---------- SEND CONNECTION REQUEST ----------
    def send_connection_request(self, profile_url: str, message=None) -> bool:
        """
        Send connection request, from outreach to target profile
        """
        try:
            self.last_connect_error = None
            normalized_url = self._normalize_profile_url(profile_url) or profile_url
            logger.info(f"Visiting profile {normalized_url}...")
            self.goto_profile(normalized_url)
            self.human_delay()

            self._log_connect_buttons("send_connection_request:start")

            top_card = self._find_top_card()
            if not top_card:
                logger.warning("Top card not found with primary selectors; using page root as fallback")

            scopes: list[Locator] = []
            if top_card:
                scopes.append(top_card)
            sticky_headers = self.page.locator("div.pvs-sticky-header__wrapper, div.pvs-profile-actions")
            if sticky_headers.count() > 0:
                for idx in range(min(sticky_headers.count(), 3)):
                    scopes.append(sticky_headers.nth(idx))
            if not scopes:
                scopes.append(self.page)

            connect_selectors = [
                "div.pvs-profile-actions button:has-text('Connect')",
                "div.pvs-profile-actions button:has-text('Collegati')",
                "div.pvs-profile-actions button:has-text('Connetti')",
                "div.pvs-profile-actions button[aria-label*='Invite to connect']",
                "div[data-view-name*='relationship-building'] button:has-text('Connect')",
                "div[data-view-name*='relationship-building'] button[aria-label*='Invite']",
                "div[data-view-name*='edge-creation-connect-action'] button",
                "button[data-view-name*='connect']",
                "button[aria-label*='Invite to connect']",
                "button[aria-label*='Connect']",
                "button[aria-label*='Collegati']",
                "button[aria-label*='Connetti']",
                "button:has-text('Connect')",
                "button:has-text('Collegati')",
                "button:has-text('Connetti')",
                "a[href*='/preload/custom-invite']",
                "a[aria-label*='Invite to connect']",
                "a[aria-label*='Collegati']",
                "a[aria-label*='Connetti']",
            ]
            connect_btn = None
            selector_label = None
            for scope in scopes:
                if not scope:
                    continue
                for sel in connect_selectors:
                    candidate = scope.locator(sel).first
                    if candidate.count() > 0:
                        connect_btn = candidate
                        selector_label = sel
                        logger.info(f"Connect button candidate found using selector: {sel}")
                        break
                if connect_btn:
                    break

            if connect_btn and self._click_connect_button(connect_btn, source=f"primary:{selector_label or 'unknown'}"):
                return self._finalize_connection_flow(profile_url, message)

            logger.warning("Primary connect button not found; trying More actions dropdown")
            if self._connect_via_more_actions(scopes, profile_url, message):
                return True

            follow_only = self._has_follow_button(scopes)
            self.last_connect_error = "no_connect_button" if follow_only else "connect_button_not_found"
            logger.error("Connect option unavailable for %s", profile_url)
            return False
        except Exception as e:
            logger.error(f"Error sending connection request to {profile_url}: {e}", exc_info=True)
            if not self.last_connect_error:
                self.last_connect_error = "connection_request_failed"
            return False

    def _finalize_connection_flow(self, profile_url: str, message: str | None) -> bool:
        """
        Complete the connection request flow by handling the modal or confirming status.
        """
        if message:
            if self.send_additional_note_on_conn_request(profile_url, message):
                return True
        else:
            if self.handle_send_without_note_modal(profile_url):
                return True
        logger.info("Connection modal flow did not complete cleanly; checking status directly.")
        return self._confirm_connection_request(profile_url)

    def _connect_via_more_actions(self, scopes: list[Locator], profile_url: str, message: str | None) -> bool:
        more_actions_btn = self._locate_more_actions_button(scopes)
        if not more_actions_btn:
            logger.error("More actions button not found while attempting connection request")
            if not self.last_connect_error:
                self.last_connect_error = "connect_button_not_found"
            return False
        try:
            more_actions_btn.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            logger.debug("Unable to scroll More actions button into view", exc_info=True)
        for attempt in range(3):
            try:
                if attempt == 0:
                    more_actions_btn.click(timeout=4000)
                elif attempt == 1:
                    more_actions_btn.click(force=True, timeout=4000)
                else:
                    handle = more_actions_btn.element_handle()
                    if handle:
                        self.page.evaluate("(el) => el.click()", handle)
                    else:
                        raise PlaywrightError("More actions element handle missing")
                logger.info("Opened More actions dropdown for connection flow")
                break
            except Exception as exc:
                logger.warning("Attempt %s to click More actions button failed: %s", attempt + 1, exc)
                self.human_delay(0.5, 1.0)
        else:
            logger.error("Unable to open More actions dropdown for connection request")
            return False

        self.human_delay(0.5, 1.0)
        dropdown_selectors = [
            'div[role="menu"] button:has-text("Connect")',
            'div[role="menu"] button:has-text("Collegati")',
            'div[role="menu"] button:has-text("Connetti")',
            'div[role="menu"] li span:has-text("Connect")',
            'div[role="menu"] li span:has-text("Collegati")',
            'div[role="menu"] li span:has-text("Connetti")',
            'div[role="button"][aria-label*="Invite"][aria-label*="connect"]',
            'li button[data-control-name*="connect"]',
            'li button[data-view-name*="connect"]',
        ]
        connect_option = None
        selector_label = None
        for sel in dropdown_selectors:
            candidate = self.page.locator(sel).first
            if candidate.count() > 0:
                connect_option = candidate
                selector_label = sel
                logger.info(f"Connect option found inside More dropdown using selector: {sel}")
                break
        if not connect_option:
            logger.error("Connect option not found inside More actions dropdown")
            if not self.last_connect_error:
                self.last_connect_error = "connect_button_not_found"
            return False
        if not self._click_connect_button(connect_option, source=f"more_dropdown:{selector_label or 'unknown'}"):
            if not self.last_connect_error:
                self.last_connect_error = "connect_button_not_found"
            return False
        return self._finalize_connection_flow(profile_url, message)
        
    # def check_connection_status(self, profile_url: str) -> str:
    #     """Check if user is connected."""
    #     self.page.goto(profile_url)
    #     time.sleep(2)
    #     connect_btn = top_card.locator(
    #             "button[aria-label*='Invite to connect'], button:has-text('Connect')"
    #         ).first
    #     connect_btn = self.page.query_selector('button:has-text("Connect")')
    #     if not connect_btn:
    #         logger.info("Connection established.")
    #         return "connected"
    #     logger.info("Connection still pending.")
    #     return "pending"

    def _confirm_connection_request(self, profile_url: str, timeout_seconds: int = 15) -> bool:
        """
        Verify that LinkedIn reflected the invitation after the send action.
        """
        deadline = time.time() + timeout_seconds
        normalized_url = self._normalize_profile_url(profile_url) or profile_url

        if normalized_url and normalized_url not in (self.page.url or ""):
            try:
                logger.info("Reloading profile %s to verify connection status", normalized_url)
                self.goto_profile(normalized_url)
                self.human_delay()
            except Exception:
                logger.debug("Failed to reload profile before confirming connection", exc_info=True)

        while time.time() < deadline:
            self.human_delay(1, 2)

            main_part = self.page.locator("main")
            if main_part.count() == 0:
                continue

            top_card = main_part.first.locator("section.artdeco-card")
            if top_card.count() == 0:
                continue

            connect_btn = top_card.first.locator(
                "button[aria-label*='Invite to connect'], button:has-text('Connect')"
            )
            pending_btn = top_card.first.locator(
                "button[aria-label*='Pending'], button:has-text('Pending')"
            )

            if pending_btn.count() > 0:
                logger.info(f"Connection request to {profile_url} is now pending.")
                return True

            more_dropdown = top_card.first.locator('[id*="ember"].artdeco-dropdown')
            if more_dropdown.count() > 0:
                list_items = more_dropdown.first.locator('[aria-hidden="true"] ul li')
                texts = [text.strip() for text in list_items.all_text_contents()] if list_items.count() > 0 else []
                if any("Remove Connection" in text for text in texts):
                    logger.info(f"{profile_url} already marked as connected.")
                    return True
                if any("Pending" in text for text in texts):
                    logger.info(f"Dropdown shows pending status for {profile_url}.")
                    return True

            if connect_btn.count() == 0 and more_dropdown.count() == 0:
                logger.info(f"Connect option disappeared for {profile_url}; assuming success.")
                return True

        logger.warning(f"Connection status did not update after sending invitation to {profile_url}.")
        return False

    def handle_send_without_note_modal(self, profile_url: str) -> bool:
        """
        Send message, declining additional note
        """
        modal_selector = 'div[role="dialog"][aria-labelledby*="send-invite-modal"]'
        try:
            self.page.wait_for_selector(modal_selector, timeout=8000)
        except PlaywrightTimeoutError:
            logger.error("Connection request modal did not appear in time; verifying status directly")
            return self._confirm_connection_request(profile_url)
        try:
            modal_window = self.page.locator(modal_selector)
            if modal_window.count() == 0:
                logger.error("Connection request 'additional notes' modal not found; verifying status directly")
                return self._confirm_connection_request(profile_url)
            logger.info("Found connection request modal")
            send_without_note_btn = modal_window.first.locator('button[aria-label*="Send without a note"]')
            if send_without_note_btn.count() == 0:
                logger.error("Send without note button not found in modal")
                return False
            send_without_note_btn.first.click()
            logger.info(f"Sent connection request to {profile_url}")
            try:
                send_without_note_btn.first.wait_for(state="detached", timeout=10000)
            except Exception:
                pass
            return self._confirm_connection_request(profile_url)
        except Exception as e:
            logger.error(f"Error occurred while handling 'send without note' modal: {e}")
            return False
        
    def send_additional_note_on_conn_request(self, profile_url, message: str) -> bool:
        """
        Send additional message, when sending connection request
        """
        try:
            # Validate message length first
            if len(message) > 300:
                logger.error("Message is too long, not sending. Needs to be 300 characters or less.")
                return False
            
            modal_outlet = self.page.locator('div[id*="modal-outlet"]')
            if modal_outlet.count() == 0:
                logger.error("Connection request 'additional notes' modal outlet not found")
                return False
            logger.info("Found connection request modal outlet")
            
            modal_window = modal_outlet.first.locator('div[role="dialog"][aria-labelledby*="send-invite-modal"]')
            if modal_window.count() == 0:
                logger.error("Connection request 'additional notes' modal not found")
                return False
            logger.info("Found connection request modal")
            
            add_note_btn = modal_window.first.locator('button[aria-label*="Add"][aria-label*="note"]')
            if add_note_btn.count() == 0:
                logger.error("Add note button not found in modal")
                return False    
            logger.info("Add note button found in modal")
            add_note_btn.first.click()
            self.human_delay(2, 3)  # Wait for textarea to appear
            
            # Try multiple selector strategies for the textarea
            text_area = None
            
            # Strategy 1: Look for textarea with name="message"
            text_area = modal_window.locator('textarea[name="message"]')
            if text_area.count() > 0:
                logger.info("Found textarea using name='message'")
            else:
                # Strategy 2: Look for textarea with id="custom-message"
                text_area = modal_window.locator('textarea[id="custom-message"]')
                if text_area.count() > 0:
                    logger.info("Found textarea using id='custom-message'")
                else:
                    # Strategy 3: Look for any textarea inside the modal
                    text_area = modal_window.locator('textarea')
                    if text_area.count() > 0:
                        logger.info(f"Found {text_area.count()} textarea(s) in modal using generic selector")
                    else:
                        # Strategy 4: Look within the relative div
                        relative_area = modal_window.locator('div.relative')
                        if relative_area.count() > 0:
                            logger.info("Found relative area, searching for textarea inside")
                            text_area = relative_area.first.locator('textarea')
                            if text_area.count() == 0:
                                # Try with class containing 'ember'
                                text_area = relative_area.first.locator('textarea[class*="ember"]')
                        
                        if text_area.count() == 0:
                            logger.error("Text area not found in modal after trying all strategies")
                            # Log the modal HTML for debugging
                            modal_html = modal_window.first.inner_html()
                            logger.debug(f"Modal HTML snippet: {modal_html[:500]}")
                            return False
            
            logger.info(f"Text area found, attempting to fill with message (length: {len(message)})")
            
            # Wait for textarea to be visible and enabled
            text_area.first.wait_for(state="visible", timeout=5000)
            
            # Click to focus
            text_area.first.click()
            self.human_delay(1, 2)
            
            # Clear any existing text
            text_area.first.fill("")
            self.human_delay()
            
            # Fill the message using type for more human-like behavior
            text_area.first.press_sequentially(message, delay=50)
            self.human_delay(1, 2)
            
            # Verify the text was entered
            entered_text = text_area.first.input_value()
            if entered_text != message:
                logger.warning(f"Text verification failed. Expected: '{message}', Got: '{entered_text}'")
                # Try filling again
                text_area.first.fill(message)
                self.human_delay()
            
            send_btn = modal_window.first.locator('button[aria-label*="Send"]')
            if send_btn.count() == 0:
                logger.error("Send button not found in modal")
                return False
            logger.info("Send button found in modal")
            send_btn.first.click()
            self.human_delay()
            logger.info(f"Sent additional note to {profile_url}")
            try:
                send_btn.first.wait_for(state="detached", timeout=10000)
            except Exception:
                pass
            return self._confirm_connection_request(profile_url)
        except Exception as e:
            logger.error(f"Error occurred while sending additional note: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _close_existing_message_overlays(self):
        """Close any existing messaging overlays to prevent interference with new ones."""
        try:
            # Note: Do NOT hide #interop-outlet - it's needed for the message overlay to appear!
            # Instead, just close any open conversation windows.
            
            # Find and close any open message composer overlays
            overlay_selectors = [
                "div.msg-overlay-bubble-header button[data-control-name='overlay.close_conversation_window']",
                "div.msg-overlay-bubble-header button[aria-label*='Close']",
                "div.msg-overlay-bubble-header button[aria-label*='Chiudi']",
                "div.msg-overlay-conversation-bubble button.msg-overlay-bubble-header__control--close",
                "button.msg-overlay-bubble-header__control[aria-label*='close' i]",
                "button.msg-overlay-bubble-header__control[aria-label*='minimize' i]",
            ]
            for sel in overlay_selectors:
                try:
                    close_btns = self.page.locator(sel)
                    count = close_btns.count()
                    if count > 0:
                        logger.info(f"Found {count} existing message overlay(s); closing them")
                        for i in range(count):
                            try:
                                close_btns.nth(i).click(timeout=2000)
                                self.human_delay(0.3, 0.5)
                            except Exception:
                                pass
                except Exception:
                    pass
            
            # Also try pressing Escape to dismiss any popups
            try:
                self.page.keyboard.press("Escape")
                self.human_delay(0.3, 0.5)
            except Exception:
                pass
                
        except Exception as e:
            logger.debug(f"Error closing existing overlays: {e}", exc_info=True)

    def _wait_for_message_composer(self, timeout_ms: int = 10000) -> bool:
        """Wait for a message composer to appear and return True if found."""
        composer_indicators = [
            "div.msg-overlay-bubble-header",
            "div.msg-form__contenteditable",
            "div.msg-overlay-conversation-bubble",
            "div[role='textbox'][aria-label*='message' i]",
            "div[role='textbox'][aria-label*='Write' i]",
            "div.msg-form__msg-content-container div[contenteditable='true']",
        ]
        try:
            selector = ", ".join(composer_indicators)
            self.page.wait_for_selector(selector, timeout=timeout_ms)
            logger.info("Message composer detected")
            return True
        except Exception:
            logger.debug("Message composer not found within timeout")
            return False

    def _navigate_to_compose_url(self, href: str) -> bool:
        """Navigate directly to the messaging compose URL."""
        try:
            # Make sure we have a full URL
            if href.startswith('/'):
                compose_url = f"https://www.linkedin.com{href}"
            else:
                compose_url = href
            
            # Remove the interop=msgOverlay parameter since we're navigating directly
            # This forces full page navigation instead of overlay
            if '&interop=msgOverlay' in compose_url:
                compose_url = compose_url.replace('&interop=msgOverlay', '')
            if '?interop=msgOverlay' in compose_url:
                compose_url = compose_url.replace('?interop=msgOverlay', '?')
            
            logger.info(f"Navigating directly to compose URL: {compose_url}")
            self.page.goto(compose_url, wait_until="networkidle", timeout=30000)
            self.human_delay(2.0, 3.0)
            
            if self._wait_for_message_composer(timeout_ms=10000):
                self._confirm_typeahead_selection()
                return True
            
            logger.warning("Composer not found after direct navigation")
            return False
            
        except Exception as e:
            logger.error(f"Direct navigation failed: {e}")
            return False

    def _fallback_navigate_to_compose(self, profile_url: str) -> bool:
        """
        Fallback: extract profile URN and navigate directly to messaging compose page.
        This is used when clicking the message button doesn't work.
        """
        try:
            logger.info("Attempting fallback: navigating directly to messaging compose page")
            
            # Try to extract the profile URN from profile page
            profile_urn = None
            
            # Method 1: Get from an existing message link on the page
            try:
                msg_links = self.page.locator("a[href*='/messaging/compose'][href*='profileUrn']")
                if msg_links.count() > 0:
                    href = msg_links.first.get_attribute("href")
                    if href and "profileUrn=" in href:
                        import urllib.parse
                        parsed = urllib.parse.urlparse(href)
                        params = urllib.parse.parse_qs(parsed.query)
                        if "profileUrn" in params:
                            profile_urn = params["profileUrn"][0]
                            logger.info(f"Extracted profile URN from link: {profile_urn}")
            except Exception:
                logger.debug("Could not extract URN from message links", exc_info=True)
            
            # Method 2: Get from page data
            if not profile_urn:
                try:
                    # Try to get from various page elements
                    script_content = self.page.evaluate("""
                        () => {
                            // Try to find URN in page scripts or data attributes
                            const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                            for (const script of scripts) {
                                if (script.textContent.includes('profileUrn')) {
                                    return script.textContent;
                                }
                            }
                            return null;
                        }
                    """)
                    if script_content and "urn:li:" in script_content:
                        import re
                        match = re.search(r'urn:li:fsd_profile:[A-Za-z0-9_-]+', script_content)
                        if match:
                            profile_urn = match.group(0)
                            logger.info(f"Extracted profile URN from page data: {profile_urn}")
                except Exception:
                    logger.debug("Could not extract URN from page data", exc_info=True)
            
            if not profile_urn:
                logger.warning("Could not extract profile URN for direct navigation fallback")
                return False
            
            # Navigate directly to compose
            import urllib.parse
            compose_url = f"https://www.linkedin.com/messaging/compose/?profileUrn={urllib.parse.quote(profile_urn)}"
            logger.info(f"Navigating directly to: {compose_url}")
            
            self.page.goto(compose_url, wait_until="networkidle", timeout=30000)
            self.human_delay(2.0, 3.0)
            
            # Check if composer is now available
            if self._wait_for_message_composer(timeout_ms=10000):
                self._confirm_typeahead_selection()
                return True
            
            logger.warning("Composer not found even after direct navigation")
            return False
            
        except Exception as e:
            logger.error(f"Fallback navigation failed: {e}")
            return False
        
    def open_messaging_interface(self, profile_url: str) -> bool:
        """
        Open the messaging interface for a profile.
        Only works for already connected profiles
        """
        try:
            # If not already on profile page, go there
            if profile_url not in self.page.url:
                logger.info(f"Visiting profile {profile_url}...")
                self.goto_profile(profile_url)
                self.human_delay()

            # Close any existing messaging overlays to prevent interference
            self._close_existing_message_overlays()

            self._log_message_buttons("open_messaging_interface:start")

            # Scroll to top to ensure sticky header buttons are visible
            try:
                self.page.evaluate("window.scrollTo(0, 0)")
                self.human_delay(0.5, 1.0)
            except Exception:
                logger.debug("Unable to scroll to top before locating message button", exc_info=True)

            top_card = self._find_top_card()
            if not top_card:
                logger.warning("Top card not found with primary selectors; falling back to page root")
            else:
                primary_selectors = [
                    "a[data-view-name='profile-primary-message']",
                    "button[data-view-name='profile-primary-message']",
                    "div.pvs-profile-actions button:has-text('Message')",
                    "div.pvs-profile-actions button[aria-label*='Message']",
                    "div.pvs-profile-actions button[data-control-name*='message']",
                    "div.pvs-profile-actions button:has-text('Messaggio')",
                    "div.pvs-profile-actions a[aria-label*='Message']",
                    "div.pvs-profile-actions a[aria-label*='Messaggio']",
                    "div.pvs-profile-actions a[href^='/messaging/compose']",
                ]
                for sel in primary_selectors:
                    candidate = top_card.locator(sel).first
                    if candidate.count() > 0:
                        if self._should_skip_message_button(candidate):
                            logger.info("Skipping premium-only Message button for selector: %s", sel)
                            continue
                        logger.info(f"Primary top-card message button found using selector: {sel}")
                        
                        # Check if the button is a link (will navigate) or a button (will open overlay)
                        is_link = False
                        try:
                            tag_name = candidate.evaluate("el => el.tagName.toLowerCase()")
                            href = candidate.get_attribute("href")
                            is_link = tag_name == "a" and href and "/messaging/" in href
                            if is_link:
                                logger.info(f"Message button is a link; expecting page navigation to {href}")
                        except Exception:
                            logger.debug("Unable to determine if message button is a link", exc_info=True)
                        
                        # Try clicking once, if it doesn't work, use direct navigation
                        if self._click_message_button(candidate, source=f"top_card_primary:{sel}"):
                            self.human_delay(1.5, 2.5)
                            
                            # Check if composer appeared
                            if self._wait_for_message_composer(timeout_ms=8000):
                                self._confirm_typeahead_selection()
                                return True
                            
                            # If not, check if page navigated
                            current_url = self.page.url
                            if '/messaging/' in current_url:
                                logger.info(f"Navigated to messaging page: {current_url}")
                                try:
                                    self.page.wait_for_load_state("networkidle", timeout=10000)
                                except Exception:
                                    pass
                                self.human_delay(1.0, 2.0)
                                self._confirm_typeahead_selection()
                                return True
                            
                            # Click worked but no overlay - try direct navigation
                            logger.warning("Click succeeded but composer did not appear; trying direct navigation")
                            href = candidate.get_attribute("href")
                            if href and '/messaging/compose' in href:
                                return self._navigate_to_compose_url(href)
                        
                        # If click failed, continue to next selector
                        continue

            message_btn = None
            matched_selector = None
            message_selectors = [
                "button:has-text('Message')",
                "button:has-text('Messaggio')",
                "button:has-text('Invia messaggio')",
                "button[aria-label*='Message']",
                "button[aria-label*='Messaggio']",
                "button[aria-label*='Invia messaggio']",
                "a[aria-label*='Message']",
                "a[aria-label*='Messaggio']",
                "a[aria-label*='Invia messaggio']",
                "a[data-control-name='message']",
                "a[data-view-name*='message']",
                "a[data-view-name='profile-secondary-message']",
                "button[data-control-name='message']",
                "button[data-view-name*='message']",
                "div[data-view-name*='message'] a",
                "div[data-view-name*='message'] button",
                "a[href^='/messaging/compose']",
                "a[href*='/messaging/']",
            ]
            scopes = []
            if top_card:
                scopes.append(top_card)
            sticky_headers = self.page.locator("div.pvs-sticky-header__wrapper, div.pvs-profile-actions")
            if sticky_headers.count() > 0:
                for idx in range(min(sticky_headers.count(), 3)):
                    scopes.append(sticky_headers.nth(idx))
            scopes.append(self.page)
            for scope in scopes:
                if not scope:
                    continue
                for sel in message_selectors:
                    candidate = scope.locator(sel).first
                    if candidate.count() > 0:
                        if self._should_skip_message_button(candidate):
                            logger.info("Skipping premium-only Message button for selector: %s", sel)
                            continue
                        message_btn = candidate
                        matched_selector = sel
                        logger.info(f"Message button found using selector: {sel}")
                        break
                if message_btn:
                    break

            if message_btn:
                selector_label = matched_selector or "unknown"
                if self._click_message_button(message_btn, source=f"fallback_scope:{selector_label}"):
                    self.human_delay()
                    try:
                        self.page.wait_for_selector(
                            "div.msg-overlay-bubble-header, div.msg-form__contenteditable",
                            timeout=10000,
                        )
                    except Exception:
                        logger.debug("Message composer did not appear immediately after click", exc_info=True)
                    self._confirm_typeahead_selection()
                    return True
                return False

            logger.warning("Message button not found; trying More actions dropdown")
            more_actions_btn = None
            for sel in [
                'button[aria-label*="More actions"]',
                'button[aria-label*="More"]',
                'button[data-test-icon="ellipsis-h"]',
                "button:has-text('Altro')",
            ]:
                candidate = self.page.locator(sel).first
                if candidate.count() > 0:
                    more_actions_btn = candidate
                    break
            if not more_actions_btn:
                logger.warning("Primary More actions selectors failed; trying sticky header scope.")
                sticky_more = self.page.locator(
                    "div.pvs-sticky-header__actions button:has-text('More'), "
                    "div.pvs-sticky-header__actions button[aria-label*='More actions'], "
                    "div.pvs-sticky-header__actions button:has-text('Altro')"
                )
                if sticky_more.count() > 0:
                    more_actions_btn = sticky_more.first
                else:
                    logger.error("More actions button not found")
                    return False
            more_actions_btn.click()
            self.human_delay()

            dropdown_selectors = [
                'div[role="button"][aria-label*="Message"]',
                'li button:has-text("Message")',
                'li span:has-text("Message")',
                'li button:has-text("Messaggio")',
                'li span:has-text("Messaggio")',
            ]
            message_btn = None
            dropdown_selector = None
            for sel in dropdown_selectors:
                candidate = self.page.locator(sel).first
                if candidate.count() > 0:
                    if self._should_skip_message_button(candidate):
                        logger.info("Skipping premium-only Message button inside dropdown for selector: %s", sel)
                        continue
                    message_btn = candidate
                    dropdown_selector = sel
                    break
            if not message_btn:
                logger.error("Message option not found inside More actions dropdown")
                # Final fallback: try navigating directly to messaging compose
                return self._fallback_navigate_to_compose(profile_url)
            try:
                message_btn.scroll_into_view_if_needed(timeout=3000)
            except Exception:
                logger.debug("Unable to scroll dropdown option into view", exc_info=True)
            selector_label = dropdown_selector or "More dropdown"
            if self._click_message_button(message_btn, source=f"more_dropdown:{selector_label}"):
                self.human_delay()
                if self._wait_for_message_composer(timeout_ms=8000):
                    self._confirm_typeahead_selection()
                    return True
            
            # Final fallback: try navigating directly
            return self._fallback_navigate_to_compose(profile_url)
        except Exception as e:
            logger.error(f"Error opening messaging interface for {profile_url}: {e}")
            return self._fallback_navigate_to_compose(profile_url)

    def _confirm_typeahead_selection(self):
        """
        When LinkedIn opens the composer in 'new message' mode, focus the suggestions
        list and confirm the first entry so the text area becomes available.
        """
        try:
            search_field = self.page.locator("input.msg-connections-typeahead__search-field").first
            if search_field.count() > 0 and search_field.is_visible():
                logger.debug("Typeahead search field visible; confirming recipient with Enter")
                search_field.press("Enter")
                self.human_delay(0.5, 1.0)
        except Exception:
            logger.debug("Unable to confirm typeahead selection", exc_info=True)

    def _click_message_button(self, locator: Locator, source: str = "") -> bool:
        target = locator
        try:
            if locator.count() > 1:
                target = locator.first
        except Exception:
            pass
        if target.count() == 0:
            return False
        try:
            logger.info(
                "Attempting to click Message button%s %s",
                f" from {source}" if source else "",
                self._element_snapshot(target),
            )
        except Exception:
            logger.debug("Unable to capture element snapshot before click", exc_info=True)
        try:
            target.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            logger.debug("Unable to scroll message button into view", exc_info=True)
        try:
            target.wait_for(state="visible", timeout=5000)
        except Exception:
            logger.debug("Message button located but not visibly rendered; forcing click", exc_info=True)

        for attempt in range(4):
            try:
                if attempt == 0:
                    target.click(timeout=4000)
                elif attempt == 1:
                    target.click(force=True, timeout=4000)
                elif attempt == 2:
                    # Use dispatch_event to bypass any interceptors
                    target.dispatch_event("click")
                else:
                    # Final attempt: direct JS click
                    handle = target.element_handle()
                    if handle:
                        self.page.evaluate("(el) => el.click()", handle)
                    else:
                        raise PlaywrightError("Message button element handle missing")
                logger.info("Clicked Message button%s", f" from {source}" if source else "")
                return True
            except Exception as exc:
                logger.warning(f"Attempt {attempt+1} to click Message button failed: {exc}")
                self.human_delay(0.5, 1.0)
        logger.error("Unable to click Message button after multiple attempts")
        return False

    def enter_message_and_send(self, profile_url: str, message: str, message_retries: int = 3) -> bool:
        """
        Enter message in the chatbox and hit Enter/Send
        """
        # Log current URL to help diagnose overlay vs full page navigation
        try:
            current_url = self.page.url
            logger.info(f"Current URL after opening message interface: {current_url}")
            is_messaging_page = '/messaging/' in current_url
        except Exception:
            is_messaging_page = False
            logger.debug("Unable to determine current URL", exc_info=True)

        # If we navigated to the full messaging page, wait for it to load
        if is_messaging_page:
            logger.info("Detected full messaging page navigation; waiting for page to load")
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                logger.debug("Network idle wait timed out", exc_info=True)
            self.human_delay(1.0, 2.0)

        # Try a union of possible composer selectors
        try:
            self.page.wait_for_selector("div.msg-form__contenteditable", timeout=15000)
        except Exception:
            logger.debug("msg-form__contenteditable not visible yet; continuing with generic selectors")

        # Extended selector list for both overlay and full messaging page
        composer_selectors = [
            # Standard overlay selectors
            'div.msg-form__contenteditable',
            'div.msg-form__contenteditable[contenteditable="true"]',
            'div[role="textbox"][aria-label*="Write" i]',
            'div[role="textbox"][aria-label*="Scrivi" i]',
            'div[role="textbox"][aria-label*="Messaggio" i]',
            'div[role="textbox"][aria-label*="message" i]',
            # Full messaging page selectors
            'div.msg-form__msg-content-container div[contenteditable="true"]',
            'div.msg-form__msg-content-container--scrollable div[contenteditable="true"]',
            'form.msg-form div[contenteditable="true"]',
            'div[data-artdeco-is-focused] div[contenteditable="true"]',
            'div.msg-s-message-list-content + div div[contenteditable="true"]',
            # Generic fallback selectors (more specific to avoid false positives)
            'div.msg-overlay-conversation-bubble div[contenteditable="true"]',
            'div.msg-convo-wrapper div[contenteditable="true"]',
            'div[contenteditable="true"][data-placeholder*="message" i]',
            'div[contenteditable="true"][aria-placeholder*="message" i]',
            'p[contenteditable="true"]',
            # Very generic - try last
            'div[contenteditable="true"]:not([aria-hidden="true"])',
        ]
        message_textbox = None
        selector_results = []
        for sel in composer_selectors:
            locator_group = self.page.locator(sel)
            try:
                count = locator_group.count()
            except Exception:
                count = 0
            if count > 0:
                selector_results.append(f"{sel}: {count} found")
            if count == 0:
                continue
            for idx in range(min(count, 4)):
                candidate = locator_group.nth(idx)
                try:
                    candidate.wait_for(state="visible", timeout=1500)
                except Exception:
                    logger.debug("Candidate composer for selector %s index %s not visible yet", sel, idx, exc_info=True)
                    continue
                if candidate.count() > 0:
                    message_textbox = candidate
                    logger.info(f"Message textbox found using selector: {sel} (index {idx})")
                    break
            if message_textbox:
                break
        if not message_textbox:
            logger.error("Couldn't find message textbox using known selectors")
            # Log all selector results for debugging
            for result in selector_results:
                logger.info(f"  Selector scan result: {result}")
            # Try to capture what contenteditable elements exist on the page
            try:
                all_contenteditables = self.page.locator('[contenteditable="true"]')
                ce_count = all_contenteditables.count()
                logger.info(f"  Total contenteditable elements on page: {ce_count}")
                for i in range(min(ce_count, 5)):
                    try:
                        el = all_contenteditables.nth(i)
                        info = self._element_snapshot(el)
                        logger.info(f"    contenteditable #{i}: {info}")
                    except Exception:
                        pass
            except Exception:
                pass
            return False
        # Ensure the composer isn't covered by the new "Add recipients" typeahead overlay
        overlay_visible = False
        for _ in range(3):
            overlay = self.page.locator("div.msg-connections-typeahead__search-results")
            if overlay.count() > 0 and overlay.first.is_visible():
                logger.debug("Connections typeahead overlay detected; dismissing with Escape")
                self.page.keyboard.press("Escape")
                self.human_delay(0.5, 1.0)
                overlay_visible = True
            else:
                overlay_visible = False
                break

        if overlay_visible:
            choice = self.page.locator("div.msg-connections-typeahead__search-results button, div.msg-connections-typeahead__search-results li")
            if choice.count() > 0:
                logger.debug("Selecting first entry from typeahead search results")
                choice.first.click()
                self.human_delay(0.5, 1.0)
        else:
            self._confirm_typeahead_selection()

        try:
            message_textbox.click(timeout=4000)
        except Exception as exc:
            logger.debug("Primary click on composer failed: %s; trying JS focus", exc_info=True)
            try:
                handle = message_textbox.element_handle()
                if handle:
                    self.page.evaluate("(el) => el.focus()", handle)
                    self.page.evaluate("(el) => el.click()", handle)
            except Exception:
                logger.debug("JS focus on composer failed", exc_info=True)
            else:
                self.human_delay(0.5, 1.0)
        else:
            self.human_delay()

        # Clean message box
        handled_via_keyboard = False
        composer_handle = None
        try:
            composer_handle = message_textbox.element_handle()
        except Exception:
            logger.debug("Unable to obtain element handle for composer", exc_info=True)

        if composer_handle:
            try:
                self.page.evaluate("(el) => el.focus()", composer_handle)
            except Exception:
                logger.debug("JS focus on composer failed", exc_info=True)

        try:
            message_textbox.click(timeout=4000)
            self.human_delay(0.5, 1.0)
        except Exception:
            logger.debug("Composer click failed during keyboard entry", exc_info=True)

        try:
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Backspace")
        except Exception:
            try:
                self.page.keyboard.press("Meta+A")
                self.page.keyboard.press("Backspace")
            except Exception:
                logger.debug("Keyboard shortcuts for clearing composer failed", exc_info=True)

        try:
            self.page.keyboard.type(message, delay=50)
            handled_via_keyboard = True
        except Exception:
            logger.debug("Keyboard typing into composer failed", exc_info=True)

        if not handled_via_keyboard:
            try:
                message_textbox.fill("")
            except Exception:
                logger.debug("fill() on message textbox failed; falling back to type-delete", exc_info=True)
                try:
                    message_textbox.type("")
                except Exception:
                    logger.debug("type('') on composer failed", exc_info=True)
            try:
                message_textbox.press_sequentially(message, delay=50)
            except Exception:
                logger.debug("press_sequentially failed; using direct type", exc_info=True)
                try:
                    message_textbox.type(message, delay=50)
                except Exception:
                    logger.debug("Direct typing into composer still failing", exc_info=True)
        else:
            self.human_delay()

        # Ensure LinkedIn registers that text was entered (some locales require explicit input events)
        try:
            composer_handle = message_textbox.element_handle(timeout=2000)
        except Exception:
            composer_handle = None
        if composer_handle:
            try:
                self.page.wait_for_function(
                    "(el) => (el.innerText || '').trim().length > 0",
                    arg=composer_handle,
                    timeout=2000,
                )
            except Exception:
                logger.debug("Composer still empty after typing; applying JS fallback")
                try:
                    self.page.evaluate(
                        """
                        (el, value) => {
                            const paragraph = document.createElement('p');
                            paragraph.textContent = value;
                            el.innerHTML = '';
                            el.appendChild(paragraph);
                            const InputEvt = typeof InputEvent === 'function' ? InputEvent : Event;
                            el.dispatchEvent(new InputEvt('input', { bubbles: true, cancelable: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                        """,
                        composer_handle,
                        message,
                    )
                except Exception:
                    logger.debug("JS fallback to inject composer text failed", exc_info=True)
        self.human_delay(2, 4)
        composer_root = None
        try:
            composer_root_candidate = message_textbox.locator(
                "xpath=ancestor::form[contains(@class,'msg-form')]"
            )
            if composer_root_candidate.count() > 0:
                composer_root = composer_root_candidate.first
        except Exception:
            logger.debug("Unable to resolve composer root form", exc_info=True)
        send_button_selectors = [
            "button.msg-form__send-button",
            'button[type="submit"][class*="send-button"]',
            "button:has-text('Send')",
            "button:has-text('Invia')",
            "button[aria-label*='Send']",
            "button[aria-label*='Invia']",
        ]
        for attempt in range(message_retries):
            msg_submit_btn = self._locate_send_button(
                send_button_selectors=send_button_selectors,
                composer_root=composer_root,
            )
            if msg_submit_btn:
                if self._click_send_button(msg_submit_btn):
                    logger.info("Send button clicked; assuming success for %s", profile_url)
                    return True
                logger.warning("Send button click attempt failed; retrying search")
                self.human_delay()
                continue

            logger.warning("Couldn't find message submit button; using keyboard fallback")
            try:
                logger.debug(
                    "Global send button count snapshot: %s",
                    self.page.locator('button.msg-form__send-button').count(),
                )
            except Exception:
                logger.debug("Failed to count msg-form__send-button globally", exc_info=True)
            try:
                message_textbox.click(timeout=2000, force=True)
            except Exception:
                logger.debug("Composer click failed before fallback send", exc_info=True)
                handle = None
                try:
                    handle = message_textbox.element_handle()
                except Exception:
                    handle = None
                if handle:
                    try:
                        self.page.evaluate("(el) => el.focus()", handle)
                    except Exception:
                        logger.debug("JS focus on composer failed during fallback", exc_info=True)
            try:
                self.page.keyboard.press("Control+Enter")
            except Exception:
                logger.debug("Ctrl+Enter send fallback failed; trying Enter", exc_info=True)
                try:
                    self.page.keyboard.press("Enter")
                except Exception:
                    logger.debug("Enter key fallback failed as well", exc_info=True)
            self.human_delay(0.5, 1.0)
            logger.info("Pressed Ctrl+Enter to send message")

            if self._conversation_contains_message(message):
                logger.info(
                    "Detected outgoing bubble for %s after fallback send; treating as success",
                    profile_url,
                )
                return True

            logger.warning(f"Attempt {attempt+1} without send button failed, retrying...")
            self.human_delay()
        if self._conversation_contains_message(message):
            logger.info(
                "Detected outgoing bubble for %s after all retries; treating as success",
                profile_url,
            )
            return True
        logger.error(f"Failed to send message after {message_retries} retries.")
        return False

    def _locate_send_button(
        self,
        *,
        send_button_selectors: List[str],
        composer_root: Optional[Locator],
    ) -> Optional[Locator]:
        scope_candidates: list[tuple[str, Locator]] = []
        if composer_root:
            scope_candidates.append(("composer_form", composer_root))
        scope_candidates.append(("page", self.page))
        for sel in send_button_selectors:
            for scope_label, scope in scope_candidates:
                locator_group = scope.locator(sel)
                try:
                    count = locator_group.count()
                except Exception:
                    logger.debug(
                        "Unable to count send button selector %s inside %s",
                        sel,
                        scope_label,
                        exc_info=True,
                    )
                    continue
                logger.debug(
                    "Send button selector %s inside %s -> count %s",
                    sel,
                    scope_label,
                    count,
                )
                if count == 0:
                    continue
                for idx in range(min(count, 3)):
                    candidate = locator_group.nth(idx)
                    try:
                        candidate.wait_for(state="visible", timeout=1500)
                    except Exception:
                        logger.debug(
                            "Send button candidate selector %s scope %s index %s not visible yet",
                            sel,
                            scope_label,
                            idx,
                            exc_info=True,
                        )
                        continue
                    logger.info(f"Send button found using selector: {sel} (scope {scope_label}, index {idx})")
                    return candidate
        return None

    def _click_send_button(self, button: Locator) -> bool:
        try:
            button.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            logger.debug("Unable to scroll send button into view", exc_info=True)
        try:
            button.wait_for(state="visible", timeout=3000)
        except Exception:
            logger.debug("Send button not visible yet; continuing", exc_info=True)

        handle = None
        try:
            handle = button.element_handle(timeout=2000)
        except Exception:
            logger.debug("Unable to grab element handle for send button", exc_info=True)
        if handle:
            try:
                self.page.wait_for_function(
                    "(btn) => !btn.disabled",
                    arg=handle,
                    timeout=4000,
                )
            except Exception:
                logger.debug("Send button remained disabled before click", exc_info=True)
        try:
            button.click(timeout=4000)
            logger.info("Clicked Send button explicitly to send message")
            return True
        except Exception as exc:
            logger.warning(f"Primary click on send button failed: {exc}; forcing click.")
            try:
                button.click(force=True, timeout=4000)
                logger.info("Force-clicked Send button")
                return True
            except Exception:
                logger.warning("Force click on send button also failed", exc_info=True)
                if handle:
                    try:
                        self.page.evaluate("(btn) => btn.click()", handle)
                        logger.info("Triggered JS click on send button")
                        return True
                    except Exception:
                        logger.debug("JS click on send button failed", exc_info=True)
        return False

    @staticmethod
    def _normalize_message_text(value: Optional[str]) -> str:
        if not value:
            return ""
        return " ".join(value.split()).strip().lower()

    def _conversation_contains_message(
        self,
        expected_message: str,
        lookback: int = 5,
        freshness_seconds: int = 300,
    ) -> bool:
        """
        Inspect the visible conversation thread to see if the outgoing message we just typed
        is already rendered, even if LinkedIn never emitted the toast notification.
        """
        if not self.page:
            return False
        normalized_expected = self._normalize_message_text(expected_message)
        if not normalized_expected:
            return False

        selectors = [
            "ul.msg-s-message-list__event-list li.msg-s-message-list__event",
            "li.msg-s-message-list__event",
        ]
        now = datetime.now(timezone.utc)
        for sel in selectors:
            try:
                events = self.page.locator(sel)
                count = events.count()
            except Exception:
                continue
            if count == 0:
                continue
            start_idx = max(0, count - lookback)
            for idx in range(start_idx, count):
                event = events.nth(idx)
                body_text = ""
                try:
                    body_text = event.locator("div.msg-s-event-listitem__body").inner_text()
                except Exception:
                    try:
                        body_text = event.inner_text()
                    except Exception:
                        body_text = ""
                normalized_body = self._normalize_message_text(body_text)
                if not normalized_body:
                    continue
                if normalized_expected not in normalized_body:
                    continue
                if not self._event_recent(event, now, freshness_seconds):
                    continue
                if self._event_is_outgoing(event):
                    return True
        return False

    def _event_recent(
        self,
        event: Locator,
        now: datetime,
        freshness_seconds: int,
    ) -> bool:
        timestamp_attr = None
        for attr in ("data-timestamp", "data-event-time", "data-time"):
            try:
                timestamp_attr = event.get_attribute(attr)
            except Exception:
                timestamp_attr = None
            if timestamp_attr:
                break
        if timestamp_attr:
            try:
                ts_val = float(timestamp_attr)
                if ts_val > 1e12:
                    ts_val /= 1000.0
                event_dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
                return abs((now - event_dt).total_seconds()) <= freshness_seconds
            except Exception:
                logger.debug("Unable to parse message event timestamp", exc_info=True)
        return True

    def _event_is_outgoing(self, event: Locator) -> bool:
        try:
            label = event.locator("span.msg-s-message-group__name").first
            if label.count() > 0:
                text = (label.inner_text() or "").strip().lower()
                if text in {"you", "tu", "vos", "voi", "usted", "você"} or text.startswith("you "):
                    return True
        except Exception:
            pass
        try:
            meta = event.locator("div.msg-s-message-group__meta").first
            if meta.count() > 0:
                classes = meta.get_attribute("class") or ""
                if "msg-s-message-group__meta--outgoing" in classes:
                    return True
        except Exception:
            pass
        # Default to True for the most recent entries
        return True
    
    def send_message(self, profile_url: str, message: str) -> bool:
        """
        Send a message to a profile.
        Only works for already connected profiles
        """
        try:
            msg_interface_opened = self.open_messaging_interface(profile_url)
            if not msg_interface_opened:
                logger.error(f"Could not send message: cannot open messaging interface for {profile_url}")
                return False
            msg_status = self.enter_message_and_send(profile_url, message)
            return msg_status
        except Exception as e:
            logger.error(f"Error messaging {profile_url}: {e}")
            return False
        
    def _normalize_date_string(self, value: str) -> str:
        """
        Convert relative dates (TODAY, MONDAY, etc.) to absolute dates.
        """
        value = value.strip().upper()
        today = datetime.today()
        
        # Handle TODAY
        if value == "TODAY":
            return today.strftime("%b %d, %Y").upper()
        
        # Handle weekday names
        weekdays = ["MONDAY", "TUESDAY", "WEDNESDAY", 
                    "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
        if value in weekdays:
            target_weekday = weekdays.index(value)
            today_weekday = today.weekday()
            days_diff = (today_weekday - target_weekday) % 7
            if days_diff == 0:
                days_diff = 7  # Last week, not today
            target_date = today - timedelta(days=days_diff)
            return target_date.strftime("%b %d, %Y").upper()
        
        # Already in correct format or unknown format
        return value

    def get_all_messages_from_chat(self, profile_url: str) -> list[dict[str, Any]] | bool:
        """
        Get all messages from one chat
        """
        def unique_non_none(seq):
            seen = set()
            return [x for x in seq if x is not None and not (x in seen or seen.add(x))]
        try:
            normalized_target_url = self._normalize_profile_url(profile_url)
            logger.info(f"Fetching all messages from chat with {profile_url}...")
            msg_interface_opened = self.open_messaging_interface(profile_url)
            if not msg_interface_opened:
                logger.error(f"Could not send message: cannot open messaging interface for {profile_url}")
                return False

            messages_container = self.page.locator('div.msg-s-message-list-container')
            if messages_container.count() == 0:
                logger.error("Messages container not found...")
                return False

            chat_box = messages_container.first.locator("div.msg-s-message-list")
            prev_count = 0

            while True:
                chat_box.evaluate("el => el.scrollBy(0, -5000)")
                self.page.wait_for_timeout(1000)

                messages = chat_box.locator("li.msg-s-message-list__event")
                count = messages.count()
                if count == prev_count:
                    break
                prev_count = count

            logger.info(f"Total messages found: {count}")

            if count == 0:
                logger.info("No messages found in the chat")
                return []

            all_messages = []
            all_urls = []
            for i in range(count):
                item = messages.nth(i)
                try:
                    date_item = item.locator("time.msg-s-message-list__time-heading")
                    if date_item.count() == 0:
                        date_text = all_messages[i-1]["date"] if i > 0 and len(all_messages) > 0 else None
                    else:
                        date_text = date_item.first.inner_text().strip()
                        # Normalize relative dates (TODAY, MONDAY, etc.)
                        date_text = self._normalize_date_string(date_text)
                        # Add year if missing
                        if len(date_text.split(",")) == 1:
                            date_text = date_text + ", " + str(datetime.now().year)

                    msg_item = item.locator("div.msg-s-event-listitem")
                    if msg_item.count() == 0:
                        logger.warning(f"No event listitem found for message {i}, skipping")
                        continue

                    a_tag = msg_item.first.locator("a")
                    if a_tag.count() == 0:
                        logger.warning(f"No a tag found for message {i}, skipping")
                        # continue
                    
                    href = a_tag.first.get_attribute("href")
                    if href is None:
                        logger.warning(f"No href found for message {i}, skipping")
                        # continue

                    all_urls.append(href.strip())
                    msg_metadata = msg_item.first.locator("div.msg-s-message-group__meta")
                    if msg_metadata.count() == 0:
                        logger.warning(f"No metadata found for message {i}, skipping")
                        continue

                    sender = msg_metadata.first.locator("a")
                    if sender.count() == 0:
                        sender = all_messages[i-1]["sender"] if i > 0 and len(all_messages) > 0 else None
                    else:
                        sender = sender.first.inner_text()

                    time_element = msg_metadata.first.locator("time")
                    if time_element.count() == 0:
                        time = all_messages[i-1]["time"] if i > 0 and len(all_messages) > 0 else None
                    else:
                        time = time_element.first.inner_text().strip()

                    # Skip if we don't have required fields
                    if not date_text or not time:
                        logger.warning(f"Missing date or time for message {i}, skipping")
                        continue

                    msg_content = msg_item.first.locator("div.msg-s-event__content")
                    if msg_content.count() == 0:
                        content = None
                    else:
                        img_container = msg_content.first.locator("div.msg-s-event-listitem__image-container")
                        if img_container.count() > 0:
                            img_src = img_container.first.locator("img")
                            if img_src.count() > 0:
                                img_url = img_src.first.get_attribute("src")
                                content = img_url if img_url else None
                        else:
                            msg_body = msg_content.first.locator("p.msg-s-event-listitem__body")
                            if msg_body.count() == 0:
                                content_elem = msg_item.first.locator("div.msg-s-event__content")
                                if content_elem.count() == 0:
                                    content = None
                                else:
                                    content = content_elem.first.inner_text()
                            else:
                                content = msg_body.first.inner_text()

                    # Parse timestamp with better error handling
                    try:
                        dt_string = f"{date_text} {time}"
                        timestamp = datetime.strptime(dt_string, "%b %d, %Y %I:%M %p")
                    except ValueError as ve:
                        # Try uppercase format
                        try:
                            timestamp = datetime.strptime(dt_string.upper(), "%b %d, %Y %I:%M %p".upper())
                        except ValueError:
                            logger.warning(f"Could not parse timestamp '{dt_string}' for message {i}, skipping")
                            continue
                                        
                    all_messages.append({
                        # "sender": sender.strip() if sender else None,
                        "sender_link": href.strip() if href else None,
                        "timestamp": timestamp if timestamp else None,
                        "date": date_text.strip() if date_text else None,
                        "time": time.strip() if time else None,
                        "content": content.strip() if content else None
                    })  

                except Exception as e:
                    logger.warning(f"Error extracting a message item: {e}")
                    continue

            encoded_to_real: dict[str, Optional[str]] = {}
            all_urls = unique_non_none(all_urls)
            for url in all_urls:
                self.goto_profile(url)
                self.human_delay()
                real_url = self._normalize_profile_url(self.page.url)
                encoded_to_real[url] = real_url

            sender_role_map: dict[str, str] = {}
            fallback_counter = 0
            last_assigned_role: Optional[str] = None

            for message in all_messages:
                normalized_sender = (
                    encoded_to_real.get(message["sender_link"])
                    if message.get("sender_link")
                    else None
                )

                sender_key = normalized_sender or f"unknown_{fallback_counter}"
                if normalized_sender is None:
                    fallback_counter += 1

                if sender_key in sender_role_map:
                    role = sender_role_map[sender_key]
                else:
                    if not sender_role_map:
                        if normalized_sender == normalized_target_url:
                            role = "received"
                        else:
                            role = "sent"
                    elif len(sender_role_map) == 1:
                        existing_role = next(iter(sender_role_map.values()))
                        role = "received" if existing_role == "sent" else "sent"
                    else:
                        role = "received" if last_assigned_role == "sent" else "sent"
                    sender_role_map[sender_key] = role

                message["sender_link"] = normalized_sender
                message["type"] = role
                last_assigned_role = role

                # logger.info(
                #     "Parsed chat message: type=%s timestamp=%s content=%s",
                #     message["type"],
                #     message.get("timestamp"),
                #     (message.get("content") or "")[:120],
                # )
                if isinstance(message.get("timestamp"), datetime):
                    message["timestamp"] = message["timestamp"].isoformat()
                
                # Drop unnecessary fields
                # message.pop("sender", None)
                message.pop("sender_link", None)
                message.pop("date", None)
                message.pop("time", None)

            return all_messages

        except Exception as e:
            logger.error(f"Error fetching messages from chat for {profile_url}: {e}")
            return False
        
    def get_all_messages_from_all_chats(self):
        def normalize_date_string(value: str) -> str:
            value = value.strip().upper()
            today = datetime.today()
            weekdays = ["MONDAY", "TUESDAY", "WEDNESDAY", 
                        "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
            if value in weekdays:
                target_weekday = weekdays.index(value)
                today_weekday = today.weekday()
                days_diff = (today_weekday - target_weekday) % 7
                target_date = today - timedelta(days=days_diff)
                return target_date.strftime("%b %d, %Y").upper()
            return value

        def parse_short_date(date_str: str) -> datetime:
            date_str = date_str.strip()
            current_year = datetime.now().year
            full_date_str = f"{date_str} {current_year}"
            try:
                dt = datetime.strptime(full_date_str, "%b %d %Y")
                return dt
            except ValueError as e:
                raise ValueError(f"Could not parse date '{date_str}': {e}")

        try:
            logger.info("Fetching all messages from all chats...")
            self.page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")

            target_area = self.page.locator("div.scaffold-layout__list-detail-container")
            if target_area.count() == 0:
                logger.error("Target area not found...")
                return False

            conversations_box = target_area.locator("ul[aria-label^='Conversation List']")
            if conversations_box.count() == 0:
                logger.error("Conversations box not found...")
                return False

            conversations_prev_count = 0

            while True:
                conversations_box.evaluate("el => el.scrollBy(0, 2000)")
                self.page.wait_for_timeout(3000)

                conversations = conversations_box.locator("li.msg-conversation-listitem")
                conversations_count = conversations.count()
                if conversations_count == conversations_prev_count:
                    break
                conversations_prev_count = conversations_count

            logger.info(f"Total conversations found: {conversations_count}")

            data = []

            for i in range(conversations_count):
                conversation_item = conversations.nth(i)
                conversation_item.click()
                self.human_delay()
                messages_area = target_area.locator("div.msg__detail")
                if messages_area.count() == 0:
                    logger.error("Messages area not found...")
                    continue

                participant_name_elem = conversation_item.locator('h3.msg-conversation-listitem__participant-names')
                participant_name = participant_name_elem.first.inner_text() if participant_name_elem.count() > 0 else None

                header_bar = messages_area.first.locator('div.shared-title-bar__title')
                if header_bar.count() == 0:
                    logger.error("Header bar not found...")
                    continue

                participant_link_elem = header_bar.first.locator('a')
                participant_link = participant_link_elem.first.get_attribute('href') if participant_link_elem.count() > 0 else None

                sponsored_chat = messages_area.first.locator("div.msg-spinmail-thread-presenter__message")
                if sponsored_chat.count() > 0:
                    logger.info("Sponsored message detected, skipping...")
                    continue

                chat_box = messages_area.first.locator("div.msg-s-message-list")
                if chat_box.count() == 0:
                    logger.error("Chat box not found...")
                    continue

                prev_count = 0

                while True:
                    chat_box.evaluate("el => el.scrollBy(0, -5000)")
                    self.page.wait_for_timeout(1000)
                    messages = chat_box.locator("li.msg-s-message-list__event")
                    count = messages.count()
                    if count == prev_count:
                        break
                    prev_count = count

                logger.info(f"Total messages found: {count}")

                if count == 0:
                    logger.info("No messages found in the chat")
                    continue
                all_messages = []

                for i in range(count):
                    item = messages.nth(i)
                    try:
                        date_item = item.locator("time.msg-s-message-list__time-heading")
                        if date_item.count() == 0:
                            date_text = all_messages[i-1]["date"] if i > 0 else None
                        else:
                            date_text = date_item.first.inner_text()
                            if len(date_text.split(",")) == 1:
                                date_text = normalize_date_string(date_text)
                            else:
                                date_text = date_text + ", " + str(datetime.now().year)

                        msg_item = item.locator("div.msg-s-event-listitem").first
                        msg_metadata = msg_item.locator("div.msg-s-message-group__meta").first

                        sender = msg_metadata.locator("a")
                        if sender.count() == 0:
                            sender = all_messages[i-1]["sender"] if i > 0 else None
                        else:
                            sender = sender.first.inner_text()

                        time_element = msg_metadata.locator("time")
                        if time_element.count() == 0:
                            time = all_messages[i-1]["time"] if i > 0 else None
                        else:
                            time = time_element.inner_text()

                        msg_content = msg_item.locator("div.msg-s-event__content")
                        if msg_content.count() == 0:
                            content = None
                        else:
                            img_container = msg_content.first.locator("div.msg-s-event-listitem__image-container")
                            if img_container.count() > 0:
                                img_src = img_container.first.locator("img")
                                if img_src.count() > 0:
                                    img_url = img_src.first.get_attribute("src")
                                    content = img_url if img_url else None
                            else:
                                msg_body = msg_content.first.locator("p.msg-s-event-listitem__body")
                                if msg_body.count() == 0:
                                    content_elem = msg_item.locator("div.msg-s-event__content")
                                    if content_elem.count() == 0:
                                        content = None
                                    else:
                                        content = content_elem.first.inner_text()
                                else:
                                    content = msg_body.first.inner_text()

                        dt_string = f"{date_text} {time}"
                        timestamp = datetime.strptime(dt_string, "%b %d, %Y %I:%M %p")

                        all_messages.append({
                            "sender": sender.strip() if sender else None,
                            "timestamp": timestamp if timestamp else None,
                            "date": date_text.strip() if date_text else None,
                            "time": time.strip() if time else None,
                            "content": content.strip() if content else None
                        })
                    except Exception as e:
                        logger.warning(f"Error extracting a message item: {e}")
                        continue

                for message in all_messages:
                    message.pop("date", None)
                    message.pop("time", None)

                data.append({
                    "participant_name": participant_name.strip() if participant_name else None,
                    "participant_link": participant_link.strip() if participant_link else None,
                    "chat_history": all_messages
                })
            return data

        except Exception as e:
            logger.error(f"Error fetching messages from chat for participant_link: {e}")
            return False






    # def login(self, outreach_profile_id: int) -> bool:
    #     """Login to LinkedIn with persistent session."""
    #     self.page.goto("https://www.linkedin.com/login")
    #     if "feed" in self.page.url:
    #         logger.info(f"Already logged in as {self.email}")
    #         return True

    #     self.page.fill('input#username', self.email)
    #     self.page.fill('input#password', self.password)
    #     self.page.click('button[type="submit"]')

    #     self.page.wait_for_timeout(3000)
    #     if "feed" in self.page.url:
    #         logger.info(f"Login successful for {self.email}")
    #         return True

    #     logger.error(f"Login failed for {self.email}")
    #     return False

    # def is_alive(self) -> bool:
    #     """Check if browser session is still valid."""
    #     try:
    #         self.page.title()
    #         return True
    #     except Exception:
    #         return False

    # def fetch_profile_info(self, profile_url: str) -> dict:
    #     """Visit a target profile and scrape key information."""
    #     self.page.goto(profile_url)
    #     self.page.wait_for_selector('main')
    #     time.sleep(2)

    #     name = self._safe_inner_text('h1.text-heading-xlarge')
    #     title = self._safe_inner_text('div.text-body-medium.break-words')
    #     about = self._safe_inner_text('section.pv-about-section')
    #     location = self._safe_inner_text('span.text-body-small.inline.t-black--light.break-words')

    #     data = {
    #         "url": profile_url,
    #         "name": name,
    #         "title": title,
    #         "about": about,
    #         "location": location
    #     }
    #     logger.info(f"Fetched profile info: {data}")
    #     return data

    # def send_connection_request(self, profile_url: str, note: str | None = None):
    #     """Send a LinkedIn connection request."""
    #     self.page.goto(profile_url)
    #     time.sleep(2)
    #     connect_btn = self.page.query_selector('button:has-text("Connect")')
    #     if not connect_btn:
    #         logger.info("Already connected or Connect button missing.")
    #         return False

    #     connect_btn.click()
    #     time.sleep(1)
    #     if note:
    #         add_note_btn = self.page.query_selector('button:has-text("Add a note")')
    #         if add_note_btn:
    #             add_note_btn.click()
    #             self.page.fill('textarea[name="message"]', note)
    #             self.page.click('button:has-text("Send")')
    #         else:
    #             self.page.click('button:has-text("Send")')
    #     else:
    #         self.page.click('button:has-text("Send")')

    #     logger.info(f"Sent connection request to {profile_url}")
    #     return True

    # def check_connection_status(self, profile_url: str) -> str:
    #     """Check if user is connected."""
    #     self.page.goto(profile_url)
    #     time.sleep(2)
    #     connect_btn = self.page.query_selector('button:has-text("Connect")')
    #     if not connect_btn:
    #         logger.info("Connection established.")
    #         return "connected"
    #     logger.info("Connection still pending.")
    #     return "pending"

    # def fetch_messages(self, profile_url: str) -> list[dict]:
    #     """Fetch chat messages from conversation."""
    #     self.page.goto("https://www.linkedin.com/messaging/")
    #     self.page.wait_for_timeout(3000)
    #     messages = []

    #     message_items = self.page.query_selector_all("li.msg-s-message-list__event")
    #     for msg in message_items:
    #         sender = msg.query_selector("span.msg-s-message-group__name").inner_text() if msg.query_selector("span.msg-s-message-group__name") else None
    #         content = msg.query_selector("p.msg-s-event-listitem__body").inner_text() if msg.query_selector("p.msg-s-event-listitem__body") else None
    #         timestamp = msg.query_selector("time").inner_text() if msg.query_selector("time") else None
    #         if sender and content:
    #             messages.append({"sender": sender, "content": content, "timestamp": timestamp})
    #     logger.info(f"Fetched {len(messages)} messages.")
    #     return messages

    # def close(self):
    #     try:
    #         self.browser.close()
    #         self.playwright.stop()
    #     except Exception:
    #         pass

    # def _safe_inner_text(self, selector: str):
    #     el = self.page.query_selector(selector)
    #     return el.inner_text().strip() if el else ""
