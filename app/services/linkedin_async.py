import asyncio
import random
import json
import os
from typing import Any, Optional
from datetime import datetime, timedelta    
from playwright.async_api import async_playwright, Page, BrowserContext, Playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
from fake_useragent import UserAgent
from app.services.proxy import Proxy
from app import crud_async
from app.database import AsyncSessionLocal
from app.redis import get_redis_async
from app.settings import FERNET, COOKIES_EXPIRATION_TIME, logger


class LinkedInService:
    def __init__(self, email: str, password: str, cookies=None, user_agent=None):
        self.proxies = []
        self.email = email
        self.password = password
        self.playwright: Optional[Playwright] = None
        self.browser_context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.browser = None
        self.cookies = cookies
        self.user_agent = user_agent

    @staticmethod
    async def human_delay(min_sec=1, max_sec=5):
        await asyncio.sleep(random.uniform(min_sec, max_sec))
        
    async def is_alive(self) -> bool:
        try:
            if not self.page or not self.browser:
                return False
            return not self.page.is_closed() and self.browser.is_connected()
        except Exception:
            return False
        
    async def close(self) -> bool:
        try:
            if await self.is_alive(): #and self.browser.is_connected():
                await self.browser.close()
                await self.playwright.stop()
                return True
            return False
        except Exception:
            return False

    async def start(
        self, 
        use_proxies: bool = False, 
        max_proxy_retries: int = 20
    ):
        """Start Playwright and launch browser, keep it persistent."""

        self.playwright = await async_playwright().start()

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
            self.browser = await self.playwright.chromium.launch(**launch_kwargs)
        except PlaywrightError as exc:
            if not requested_headless:
                logger.warning(
                    "Headed Chromium launch failed (%s); retrying in headless mode.",
                    exc,
                )
                launch_kwargs["headless"] = True
                self.browser = await self.playwright.chromium.launch(**launch_kwargs)
            else:
                await self.playwright.stop()
                raise
        self.browser_context = await self.browser.new_context(**browser_context_options)
        
        # restore cookies if available (after browser_context is created)
        if self.cookies:
            try:
                await self.browser_context.add_cookies(self.cookies)
            except Exception as e:
                logger.warning(f"Failed to restore cookies for {self.email}: {e}")

        await self.browser_context.add_init_script(bot_stealth_js_script)
        self.page = await self.browser_context.new_page()

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


    async def test_proxy(self, page, proxy, timeout=15000):
        """Test if a proxy is working by navigating to a test site."""
        logger.info(f"Testing proxy: {proxy['server']}")
        try:
            await page.goto("https://www.whatismyipaddress.com", wait_until="domcontentloaded", timeout=timeout)
            ip_content = await page.content()
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

    async def get_session_data(self) -> tuple[list, str]:
        """
        Return cookies and user agent for persistence.
        """
        return await self.browser_context.cookies(), await self.page.evaluate("navigator.userAgent")

    async def login(self, outreach_profile_id: int) -> bool:
        """Login to LinkedIn with optional proxy rotation."""
        # if not await self.is_alive():
        #     logger.info("Not alive")
        #     await self.start()  # make sure browser/page exists

        if self.cookies and self.user_agent:
            logger.info(f"Found stored session for {self.email}, trying to restore...")
            # Set user agent
            self.browser_context = await self.browser.new_context(user_agent=self.user_agent)
            # self.page = self.browser_context.new_page()

            # Set cookies
            await self.browser_context.add_cookies(self.cookies)

            # Try direct navigation to feed
            self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
            await self.human_delay()

            if self.page.url.startswith("https://www.linkedin.com/feed/"):
                logger.info("Restored session successfully via cookies.")
                return True
            else:
                logger.warning("Stored session invalid, falling back to normal login...")

        # --- Step 2: Do normal login with credentials ---
        # Navigate to LinkedIn login page first
        await self.page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=60000)
        await self.human_delay()

        # Handle welcome back screen
        login_as_button = self.page.locator('button[aria-label^="Login as"]')
        if await login_as_button.count() > 0:
            await login_as_button.first.click()
            await self.human_delay()
            logger.info("Clicked 'Login as' button")
        if await self.page.url.startswith("https://www.linkedin.com/feed/"):
            logger.info("User is already logged in.")
            return True
            # self.human_delay()
        else:
            logger.info("No 'Login as' button found, proceeding with standard login")
            await self.human_delay()
            # Fill credentials
            self.page.fill('input[name="session_key"]', self.email)
            await self.human_delay()
            await self.page.fill('input[name="session_password"]', self.password)
            await self.human_delay()
            await self.page.click('button[type="submit"]')
            await self.human_delay()
            await self.page.wait_for_load_state("domcontentloaded", timeout=60000)

        # --- Step 3: Detect login success/failure ---
        # logged_in = False
        if self.page.url.startswith("https://www.linkedin.com/error_pages/unsupported-browser"):
            logger.warning("Unsupported browser detected.")
            # logged_in = False
            return False
        if self.page.url.startswith("https://www.linkedin.com/feed/"):
            return True
        elif await self.page.is_visible('img[alt*="Photo of"]'):
            return True

        # --- Step 5: Handle 2FA / checkpoint ---
        elif await self.page.is_visible('input[name="pin"]') or "checkpoint" in self.page.url:
            logger.warning("2FA or checkpoint detected. Manual intervention may be required.")
            # Here the 2captcha logic will be added
            return False
            # logged_in = False
        else:
            logger.error("Login failed, something went wrong...")
            return False
            # logged_in = False
        
    
    #async def check_if_linkedin_url_is_valid(self):


    async def get_user_linkedin_url(self):
        # Locate the <img> element
        img = self.page.locator('img[alt*="Photo of"]').first  

        # Go to its parent <a>
        parent_a = img.locator("xpath=..")

        # Get the href attribute
        href = await parent_a.get_attribute("href")

        return f"https://www.linkedin.com{href}"


    async def click_if_visible(locator, timeout: int = 15000) -> bool:
        """
        Tries to click a locator if it exists and is visible.
        Returns True if clicked, False otherwise.
        """
        try:
            if await locator.count() == 0:
                return False  # element not found

            await locator.scroll_into_view_if_needed()
            await locator.wait_for(state="visible", timeout=timeout)
            await locator.click()
            return True

        except PlaywrightTimeoutError:
            # element exists but never became visible in time
            return False
        except Exception as e:
            # catch-all for weird cases (e.g. detached node)
            logger.warning(f"Could not click element: {e}")
            return False
        
    async def goto_profile(self, profile_url: str) -> Page | bool:
        """
        Go to target profile page - returns that page, or False if unsuccessful
        """
        # Visit profile URL
        await self.page.goto(profile_url, wait_until="domcontentloaded")

        # Handle LinkedIn Authwall redirect
        if "linkedin.com/authwall" in self.page.url:
            logger.warning("Hit authwall, trying to bypass...")

            # Try to click "Sign in" / "Continue"
            try:
                btn = self.page.locator("button:has-text('Sign in'), a:has-text('Sign in'), button:has-text('Continue')")
                await btn.first.scroll_into_view_if_needed()
                await btn.first.click()
                await self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                if self.page.url.startswith("https://www.linkedin.com/in/"):
                    logger.info("Bypassed authwall")
                    return self.page
                if "linkedin.com/authwall" in self.page.url:
                    logger.warning("Still on authwall...")
                    if self.page.locator("h1:has-text('Join Linkedin')").count() > 0:
                        logger.info("Detected Join Linkedin prompt.")
                        sign_in_btn = self.page.locator("button:has-text('Sign in'), a:has-text('Sign in')")
                        await sign_in_btn.first.scroll_into_view_if_needed()
                        await sign_in_btn.first.click()
                        await self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                        if await self.page.locator("h1:has-text('Sign in')").count() > 0:
                            logger.info("Detected Sign in prompt.")
                            await self.page.fill('input[name="session_key"]', self.email)
                            await self.human_delay()
                            await self.page.fill('input[name="session_password"]', self.password)
                            await self.human_delay()
                            await self.page.click('button[type="submit"]', has_text="Sign in")
                            await self.human_delay()
                            await self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                            if self.page.url.startswith("https://www.linkedin.com/in/"):
                                logger.info("Bypassed authwall")
                                return self.page
                    else:
                        logger.warning("Different authwall scenario...")
                        return False

                # Welcome screen - redirect to linkedin.com
                if "linkedin.com" in self.page.url:
                    welcome_text = self.page.locator("h1").first
                    if await welcome_text.count() == 0:
                        logger.error("Login redirect:Welcome text not found...")
                        return False
                    welcome_text_content = await welcome_text.text_content()
                    if "Welcome to your professional community" in welcome_text_content:
                        logger.info("Login redirect: Detected welcome screen, trying to click 'Sign in as'...")
                        sign_in_as_link = self.page.locator(("a[href='https://www.linkedin.com/login']")).first
                        if sign_in_as_link:
                            await sign_in_as_link.click()
                            await self.page.wait_for_load_state("domcontentloaded", timeout=60000)
                            if self.page.url.startswith("https://www.linkedin.com/in/"):
                                logger.info("Bypassed authwall")
                                return self.page
            except Exception as e:
                logger.error(f"Could not bypass authwall: {e}")

        return self.page
        

    async def fetch_profile_info(self, profile_url: str) -> dict[str, Any] | None:
        """
        Get target profile information - name, title, location, about
        """
        profile_data = {}

        await self.goto_profile(profile_url)
        await self.human_delay()

        # --- Top card: Name, Lastname, Title, Location ---
        try:
            top_card = self.page.locator("section.artdeco-card").first
            profile_data["name"] = await top_card.locator("h1").text_content()
            if profile_data["name"]:
                name_parts = profile_data["name"].strip().split()
                profile_data["name"] = name_parts[0]
                profile_data["lastname"] = " ".join(name_parts[1:])
            else:
                profile_data["name"] = None
                profile_data["lastname"] = None
            profile_data["title"] = await top_card.locator("div.text-body-medium").text_content()
            profile_data["location"] = await top_card.locator("span.text-body-small.inline.t-black--light.break-words").text_content()

            profile_data["title"] = profile_data["title"].strip() if profile_data["title"] else None
            profile_data["location"] = profile_data["location"].strip() if profile_data["location"] else None
            logger.info("Top card info added...")
        except Exception:
            logger.warning("Top card info not found...")

        # --- About Section ---
        try:
            about_area = await self.page.locator(
                "section.artdeco-card.pv-profile-card",
            ).filter(has=self.page.locator("h2.pvs-header__title >> span.visually-hidden", has_text="About")).first
            about_area_narrow = about_area.locator("span.visually-hidden")
            profile_data["about"] = await about_area_narrow.nth(1).inner_text()
            logger.info("About section added...")
        except Exception:
            logger.warning("About section not found...")

        # --- Connection / Message / Pending Buttons ---
        try:
            connect_btn = top_card.locator(
                "button[aria-label*='Invite to connect'], button:has-text('Connect')"
            ).first

            message_btn = top_card.locator(
                "button:has-text('Message'), button[aria-label*='Message']"
            ).first

            pending_btn = top_card.locator(
                "button:has-text('Pending'), button[aria-label*='Pending']"
            ).first

            more_dropdown = top_card.locator('[id*="ember"].artdeco-dropdown').first
            if await more_dropdown.count() > 0:
                list_items = more_dropdown.locator('[aria-hidden="true"] ul li')
                texts = await list_items.all_text_contents()
                texts = [text.strip() for text in texts]

            if texts:
                for text in texts:
                    if 'Remove Connection' in text:
                        profile_data["connected"] = True
                        profile_data["connection_pending"] = False
                        #profile_data["can_message"] = True
                        break
                    if 'Pending' in text:
                        profile_data["connection_pending"] = True
                        profile_data["connected"] = False
                        #profile_data["can_message"] = False
                        break
                    if 'Connect' in text:
                        profile_data["connected"] = False
                        #profile_data["can_message"] = False

            if await connect_btn.count() > 0:
                profile_data["connected"] = False
                #profile_data["can_message"] = False
            if await pending_btn.count() > 0:
                profile_data["connection_pending"] = True
                profile_data["connected"] = False
                #profile_data["can_message"] = False

            logger.info("Profile status data added...")
        except Exception:
            logger.error("Error during profile status data extraction...")

        return profile_data

    # ---------- SEND CONNECTION REQUEST ----------
    async def send_connection_request(self, profile_url: str, message=None) -> bool:
        """
        Send connection request, from outreach to target profile
        """
        try:
            logger.info(f"Visiting profile {profile_url}...")
            await self.goto_profile(profile_url)
            await self.human_delay()

            main_part = self.page.locator("main")
            if await main_part.count() == 0:
                return False

            top_card = main_part.first.locator("section.artdeco-card")
            if top_card.count() == 0:
                return False
            
            # Look for Connect button inside top_card first
            connect_btn = top_card.first.locator(
                "button[aria-label*='Invite to connect'], button:has-text('Connect')"
            )
            if await connect_btn.count() > 0:
                await connect_btn.first.click()
                logger.info("Clicked Connect button from the top card")
                await self.human_delay()
                if message:
                    send_with_note_response = await self.send_additional_note_on_conn_request(profile_url, message)
                    return send_with_note_response
                send_without_note_response = await self.handle_send_without_note_modal(profile_url)
                return send_without_note_response
            else:
                # More dropdown menu text
                more_dropdown = top_card.first.locator('[id*="ember"].artdeco-dropdown')
                # go inside aria-hidden="true" child, then into the ul > li
                if await more_dropdown.count() == 0:
                    logger.error("More dropdown not found")
                    return False
                list_items = more_dropdown.first.locator('[aria-hidden="true"] ul li')
                if await list_items.count() == 0:
                    logger.error("No list items in more dropdown")
                    return False
                # get all text contents
                texts = await list_items.all_text_contents()
                texts = [text.strip() for text in texts]
                if 'Connect' not in texts:
                    logger.error("Connect button not found in More actions dropdown")
                    return False
                logger.info("Found Connect button in More dropdown")
                # First, open the dropdown
                more_actions_btn = main_part.first.locator('button[aria-label*="More actions"]')
                if await more_actions_btn.count() == 0:
                    logger.warning("More actions button not found")
                    return False
                await more_actions_btn.first.click()
                await self.human_delay()
                # Now click "Connect"
                invite_to_connect = main_part.first.locator('div[role="button"][aria-label^="Invite"][aria-label$="to connect"]').first
                if await invite_to_connect.count() == 0:
                    logger.warning("Connect button not found in More actions dropdown")
                    return False
                await self.human_delay()
                await invite_to_connect.first.click()
                logger.info("Clicked Connect from More actions dropdown")
                if message:
                    send_with_note_response = await self.send_additional_note_on_conn_request(profile_url, message)
                    return send_with_note_response
                send_without_note_response = await self.handle_send_without_note_modal(profile_url)
                return send_without_note_response
        except Exception as e:
            logger.error(f"Error sending connection request to {profile_url}: {e}")
            return False


    async def handle_send_without_note_modal(self, profile_url: str) -> bool:
        """
        Send message, declining additional note
        """
        try:
            modal_window = self.page.locator('div[role="dialog"][aria-labelledby*="send-invite-modal"]')
            if await modal_window.count() == 0:
                logger.error("Connection request 'additional notes' modal not found")
                return False
            logger.info("Found connection request modal")
            send_without_note_btn = modal_window.first.locator('button[aria-label*="Send without a note"]')
            if await send_without_note_btn.count() == 0:
                logger.error("Send without note button not found in modal")
                return False
            await send_without_note_btn.first.click()
            logger.info(f"Sent connection request to {profile_url}")
            return True
        except Exception as e:
            logger.error(f"Error occurred while handling 'send without note' modal: {e}")
            return False
        
    async def send_additional_note_on_conn_request(self, profile_url, message: str) -> bool:
        """
        Send additional message, when sending connection request
        """
        try:
            # Validate message length first
            if len(message) > 300:
                logger.error("Message is too long, not sending. Needs to be 300 characters or less.")
                return False
            
            modal_outlet = self.page.locator('div[id*="modal-outlet"]')
            if await modal_outlet.count() == 0:
                logger.error("Connection request 'additional notes' modal outlet not found")
                return False
            logger.info("Found connection request modal outlet")
            
            modal_window = modal_outlet.first.locator('div[role="dialog"][aria-labelledby*="send-invite-modal"]')
            if await modal_window.count() == 0:
                logger.error("Connection request 'additional notes' modal not found")
                return False
            logger.info("Found connection request modal")
            
            add_note_btn = modal_window.first.locator('button[aria-label*="Add"][aria-label*="note"]')
            if await add_note_btn.count() == 0:
                logger.error("Add note button not found in modal")
                return False    
            logger.info("Add note button found in modal")
            await add_note_btn.first.click()
            await self.human_delay(2, 3)  # Wait for textarea to appear
            
            # Try multiple selector strategies for the textarea
            text_area = None
            
            # Strategy 1: Look for textarea with name="message"
            text_area = modal_window.locator('textarea[name="message"]')
            if await text_area.count() > 0:
                logger.info("Found textarea using name='message'")
            else:
                # Strategy 2: Look for textarea with id="custom-message"
                text_area = modal_window.locator('textarea[id="custom-message"]')
                if await text_area.count() > 0:
                    logger.info("Found textarea using id='custom-message'")
                else:
                    # Strategy 3: Look for any textarea inside the modal
                    text_area = modal_window.locator('textarea')
                    text_area_count = await text_area.count()
                    if text_area_count > 0:
                        logger.info(f"Found {text_area_count} textarea(s) in modal using generic selector")
                    else:
                        # Strategy 4: Look within the relative div
                        relative_area = modal_window.locator('div.relative')
                        if await relative_area.count() > 0:
                            logger.info("Found relative area, searching for textarea inside")
                            text_area = relative_area.first.locator('textarea')
                            if await text_area.count() == 0:
                                # Try with class containing 'ember'
                                text_area = relative_area.first.locator('textarea[class*="ember"]')
                        
                        if await text_area.count() == 0:
                            logger.error("Text area not found in modal after trying all strategies")
                            # Log the modal HTML for debugging
                            modal_html = await modal_window.first.inner_html()
                            logger.debug(f"Modal HTML snippet: {modal_html[:500]}")
                            return False
            
            logger.info(f"Text area found, attempting to fill with message (length: {len(message)})")
            
            # Wait for textarea to be visible and enabled
            await text_area.first.wait_for(state="visible", timeout=5000)
            
            # Click to focus
            await text_area.first.click()
            await self.human_delay(1, 2)
            
            # Clear any existing text
            await text_area.first.fill("")
            await self.human_delay()
            
            # Fill the message using type for more human-like behavior
            await text_area.first.press_sequentially(message, delay=50)
            await self.human_delay(1, 2)
            
            # Verify the text was entered
            entered_text = await text_area.first.input_value()
            if entered_text != message:
                logger.warning(f"Text verification failed. Expected: '{message}', Got: '{entered_text}'")
                # Try filling again
                await text_area.first.fill(message)
                await self.human_delay()
            
            send_btn = modal_window.first.locator('button[aria-label*="Send"]')
            if await send_btn.count() == 0:
                logger.error("Send button not found in modal")
                return False
            logger.info("Send button found in modal")
            await send_btn.first.click()
            await self.human_delay()
            logger.info(f"Sent additional note to {profile_url}")
            return True                    
        except Exception as e:
            logger.error(f"Error occurred while sending additional note: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
        
    async def open_messaging_interface(self, profile_url: str) -> bool:
        """
        Open the messaging interface for a profile.
        Only works for already connected profiles
        """
        try:
            # If not already on profile page, go there
            if profile_url not in self.page.url:
                logger.info(f"Visiting profile {profile_url}...")
                await self.goto_profile(profile_url)
                await self.human_delay()
            top_card = self.page.locator("section.artdeco-card").first
            if await top_card.count() == 0:
                logger.error("Top card not found...")
                return False
            # Look for Message button inside top_card
            message_btn = top_card.locator(
                "button:has-text('Message'), button[aria-label*='Message']"
            ).first
            if await message_btn.count() == 0:
                logger.warning("Message button not found in the top card")
                logger.info("Attempting to find message button in the 'More' dropdown...")
                # More dropdown menu text
                more_dropdown = top_card.locator('[id*="ember"].artdeco-dropdown').first
                # go inside aria-hidden="true" child, then into the ul > li
                if await more_dropdown.count() == 0:
                    logger.error("More dropdown not found")
                    return False
                list_items = more_dropdown.locator('[aria-hidden="true"] ul li')
                # get all text contents
                texts = await list_items.all_text_contents()
                texts = [text.strip() for text in texts]
                if 'Message' not in texts:
                    logger.error("Message button not found in More dropdown")
                    return False
                logger.info("Found Message button in More dropdown")
                # First, open the dropdown
                more_actions_btn = self.page.locator('button[aria-label*="More actions"]').first
                if await more_actions_btn.count() == 0:
                    logger.error("More actions button not found")
                    return False
                await more_actions_btn.click()
                await self.human_delay()
                # Now click "Message"
                message_btn = self.page.locator('div[role="button"][aria-label*="Message"]').first
                if await message_btn.count() == 0:
                    logger.error("Message button not found in More dropdown")
                    return False
                await message_btn.click()
                logger.info("Clicked Message from More actions dropdown")
                await self.human_delay()
                return True
            await message_btn.click()
            logger.info("Clicked Message button from the top card")
            await self.human_delay()
            return True
        except Exception as e:
            logger.error(f"Error opening messaging interface for {profile_url}: {e}")
            return False

    async def enter_message_and_send(self, profile_url: str, message: str, message_retries: int = 3) -> bool:
        """
        Enter message in the chatbox and hit Enter/Send
        """
        message_textbox = self.page.locator('div[role="textbox"][aria-label*="Write a message"]').first
        if await message_textbox.count() == 0:
            logger.error("Couldn't find message textbox")
            return False
        await message_textbox.click()
        await self.human_delay()
        # Clean message box
        await message_textbox.type("")
        await message_textbox.press_sequentially(message, delay=50)
        await self.human_delay(5, 10)
        for attempt in range(message_retries):
            # Click Send button explicitly
            msg_submit_btn = self.page.locator('button[type="submit"][class*="send-button"]').first
            if await msg_submit_btn.count() == 0:
                logger.warning("Couldn't find message submit button")
                # Press Enter to send
                await message_textbox.click()
                await message_textbox.press("Control+Enter")
                logger.info("Pressed Ctrl+Enter to send message")
            else:
                await msg_submit_btn.click()
                logger.info("Clicked Send button explicitly to send message")

            try:
                # wait for LinkedIn's "Message sent" toast/confirmation
                await self.page.wait_for_selector("text=Message sent", timeout=3000)
                logger.info(f"Message sent to {profile_url}")
                return True
            except:
                logger.warning(f"Attempt {attempt+1} failed, retrying...")
                await self.human_delay()
        logger.error(f"Failed to send message after {message_retries} retries.")
        return False
    
    async def send_message(self, profile_url: str, message: str) -> bool:
        """
        Send a message to a profile.
        Only works for already connected profiles
        """
        try:
            msg_interface_opened = await self.open_messaging_interface(profile_url)
            if not msg_interface_opened:
                logger.error(f"Could not send message: cannot open messaging interface for {profile_url}")
                return False
            msg_status = await self.enter_message_and_send(profile_url, message)
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

    async def get_all_messages_from_chat(self, profile_url: str) -> list[dict[str, Any]] | bool:
        """
        Get all messages from one chat
        """
        def unique_non_none(seq):
            seen = set()
            return [x for x in seq if x is not None and not (x in seen or seen.add(x))]
        try:
            logger.info(f"Fetching all messages from chat with {profile_url}...")
            msg_interface_opened = await self.open_messaging_interface(profile_url)
            if not msg_interface_opened:
                logger.error(f"Could not send message: cannot open messaging interface for {profile_url}")
                return False

            messages_container = self.page.locator('div.msg-s-message-list-container')
            if await messages_container.count() == 0:
                logger.error("Messages container not found...")
                return False

            chat_box = messages_container.first.locator("div.msg-s-message-list")
            prev_count = 0

            while True:
                await chat_box.evaluate("el => el.scrollBy(0, -5000)")
                await self.page.wait_for_timeout(1000)

                messages = chat_box.locator("li.msg-s-message-list__event")
                count = await messages.count()
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
                    if await date_item.count() == 0:
                        date_text = all_messages[i-1]["date"] if i > 0 and len(all_messages) > 0 else None
                    else:
                        date_text = await date_item.first.inner_text().strip()
                        # Normalize relative dates (TODAY, MONDAY, etc.)
                        date_text = self._normalize_date_string(date_text)
                        # Add year if missing
                        if len(date_text.split(",")) == 1:
                            date_text = date_text + ", " + str(datetime.now().year)

                    msg_item = item.locator("div.msg-s-event-listitem")
                    if await msg_item.count() == 0:
                        logger.warning(f"No event listitem found for message {i}, skipping")
                        continue

                    a_tag = msg_item.first.locator("a")
                    if await a_tag.count() == 0:
                        logger.warning(f"No a tag found for message {i}, skipping")
                        # continue
                    
                    href = await a_tag.first.get_attribute("href")
                    if href is None:
                        logger.warning(f"No href found for message {i}, skipping")
                        # continue

                    all_urls.append(href.strip())
                    msg_metadata = msg_item.first.locator("div.msg-s-message-group__meta")
                    if await msg_metadata.count() == 0:
                        logger.warning(f"No metadata found for message {i}, skipping")
                        continue

                    sender = msg_metadata.first.locator("a")
                    if await sender.count() == 0:
                        sender = all_messages[i-1]["sender"] if i > 0 and len(all_messages) > 0 else None
                    else:
                        sender = await sender.first.inner_text()

                    time_element = msg_metadata.first.locator("time")
                    if await time_element.count() == 0:
                        time = all_messages[i-1]["time"] if i > 0 and len(all_messages) > 0 else None
                    else:
                        time = await time_element.first.inner_text().strip()

                    # Skip if we don't have required fields
                    if not date_text or not time:
                        logger.warning(f"Missing date or time for message {i}, skipping")
                        continue

                    msg_content = msg_item.first.locator("div.msg-s-event__content")
                    if await msg_content.count() == 0:
                        content = None
                    else:
                        img_container = msg_content.first.locator("div.msg-s-event-listitem__image-container")
                        if await img_container.count() > 0:
                            img_src = img_container.first.locator("img")
                            if await img_src.count() > 0:
                                img_url = await img_src.first.get_attribute("src")
                                content = img_url if img_url else None
                        else:
                            msg_body = msg_content.first.locator("p.msg-s-event-listitem__body")
                            if await msg_body.count() == 0:
                                content_elem = msg_item.first.locator("div.msg-s-event__content")
                                if await content_elem.count() == 0:
                                    content = None
                                else:
                                    content = await content_elem.first.inner_text()
                            else:
                                content = await msg_body.first.inner_text()

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

            encoded_to_real = {}
            sent_received = {}
            all_urls = unique_non_none(all_urls)
            for url in all_urls:
                await self.goto_profile(url)
                await self.human_delay()
                real_url = self.page.url
                encoded_to_real[url] = real_url
                if real_url == profile_url:
                    sent_received[real_url] = "received"
                else:
                    sent_received[real_url] = "sent"

            for message in all_messages:
                message["sender_link"] = encoded_to_real[
                    message["sender_link"]] if message["sender_link"] else None
                message["type"] = sent_received[
                    message["sender_link"]] if message["sender_link"] else None
                
                # Drop unnecessary fields
                # message.pop("sender", None)
                message.pop("sender_link", None)
                message.pop("date", None)
                message.pop("time", None)

            return all_messages

        except Exception as e:
            logger.error(f"Error fetching messages from chat for {profile_url}: {e}")
            return False



    async def get_all_messages_from_chat(self, profile_url: str) -> list[dict[str, Any]] | bool:
        try:
            logger.info(f"Fetching all messages from chat with {profile_url}...")
            msg_interface_opened = await self.open_messaging_interface(profile_url)
            if not msg_interface_opened:
                logger.error(f"Could not send message: cannot open messaging interface for {profile_url}")
                return False
            
            messages_container = self.page.locator('div.msg-s-message-list-container')
            if await messages_container.count() == 0:
                logger.error("Messages container not found...")
                return False
            
            chat_box = messages_container.first.locator("div.msg-s-message-list")
            prev_count = 0

            while True:
                # Scroll up inside the chat box
                await chat_box.evaluate("el => el.scrollBy(0, -5000)")
                await self.page.wait_for_timeout(1000)  # give time for new messages to load

                # Count messages
                messages = chat_box.locator("li.msg-s-message-list__event")
                count = await messages.count()
                if count == prev_count:
                    break  # no new messages loaded, stop scrolling
                prev_count = count

            logger.info(f"Total messages found: {count}")

            if count == 0:
                logger.info("No messages found in the chat")
                return []
            all_messages = []

            for i in range(count):
                item = messages.nth(i)
                try:
                    # Date header (only appears sometimes)
                    date_item = item.locator("time.msg-s-message-list__time-heading")
                    if await date_item.count() == 0:
                        date_text = all_messages[i-1]["date"] if i > 0 else None
                    else:
                        date_text = await date_item.first.inner_text()
                        if len(date_text.split(",")) == 1:
                            date_text = date_text + ", " + str(datetime.now().year)
                        
                    # Message item    
                    msg_item = item.locator("div.msg-s-event-listitem").first
                    msg_metadata = msg_item.locator("div.msg-s-message-group__meta").first

                    # Sender
                    sender = msg_metadata.locator("a")
                    if await sender.count() == 0:
                        sender = all_messages[i-1]["sender"] if i > 0 else None
                    else:
                        sender = await sender.first.inner_text()

                    # Time
                    time_element = msg_metadata.locator("time")
                    if await time_element.count() == 0:
                        time = all_messages[i-1]["time"] if i > 0 else None
                    else:
                        time = await time_element.inner_text()


                    # Content
                    msg_content = msg_item.locator("div.msg-s-event__content")
                    # If no content
                    if await msg_content.count() == 0:
                        content = None
                    else:
                        # Check if message is image
                        img_container = msg_content.first.locator("div.msg-s-event-listitem__image-container")
                        if await img_container.count() > 0:
                            img_src = img_container.first.locator("img")
                            if await img_src.count() > 0:
                                img_url = await img_src.first.get_attribute("src")
                                content = img_url if img_url else None
                        else:
                            msg_body = msg_content.first.locator("p.msg-s-event-listitem__body")
                            if await msg_body.count() == 0:
                                content_elem = msg_item.locator("div.msg-s-event__content")
                                if await content_elem.count() == 0:
                                    content = None
                                else:
                                    content = await content_elem.first.inner_text()
                            else:
                                content = await msg_body.first.inner_text()


                    # # Content
                    # msg_body = msg_item.locator("p.msg-s-event-listitem__body")
                    # if await msg_body.count() == 0:
                    #     content = msg_item.locator("div.msg-s-event__content")
                    #     if await content.count() == 0:
                    #         content = None
                    #     else:
                    #         content = await content.first.inner_text()
                    # else:
                    #     content = await msg_body.first.inner_text()

                    # Combine date + time into a single string
                    dt_string = f"{date_text} {time}"
                    # Parse into a datetime object
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
                # Optionally, remove old keys
                message.pop("date", None)
                message.pop("time", None)
            return all_messages

        except Exception as e:
            logger.error(f"Error fetching messages from chat for {profile_url}: {e}")
            return False
        
    async def get_all_messages_from_all_chats(self):
        def normalize_date_string(value: str) -> str:
            """
            Convert LinkedIn-style date headers into full date strings.
            e.g. "TUESDAY" -> "SEP 11, 2025"
            """
            value = value.strip().upper()
            today = datetime.today()

            # Check if it's a weekday name
            weekdays = ["MONDAY", "TUESDAY", "WEDNESDAY", 
                        "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
            
            if value in weekdays:
                target_weekday = weekdays.index(value)
                today_weekday = today.weekday()  # Monday=0, Sunday=6

                # Go backwards in time until we find that weekday in current week
                days_diff = (today_weekday - target_weekday) % 7
                target_date = today - timedelta(days=days_diff)

                return target_date.strftime("%b %d, %Y").upper()  # e.g. "SEP 11, 2025"

            # Otherwise assume it's already a proper date string
            return value
        def parse_short_date(date_str: str) -> datetime:
            """
            Convert a short date string like 'Oct 3' into a datetime object.
            Automatically assumes the current year.
            """
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
            # Open messaging interface
            await self.page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
            #await self.human_delay()

            target_area = self.page.locator("div.scaffold-layout__list-detail-container")

            if await target_area.count() == 0:
                logger.error("Target area not found...")
                return False

            #conversations_box = target_area.first.locator('div.scaffold-layout__list')
            conversations_box = target_area.locator("ul[aria-label^='Conversation List']")
            if await conversations_box.count() == 0:
                logger.error("Conversations box not found...")
                return False
            
            conversations_prev_count = 0

            # Get all conversations by scrolling to the bottom
            while True:
                # Scroll up inside the chat box
                await conversations_box.evaluate("el => el.scrollBy(0, 2000)")
                await self.page.wait_for_timeout(3000)  # give time for new conversations to load

                # Count conversations
                conversations = conversations_box.locator("li.msg-conversation-listitem")
                conversations_count = await conversations.count()
                if conversations_count == conversations_prev_count:
                    break  # no new conversations loaded, stop scrolling
                conversations_prev_count = conversations_count

            logger.info(f"Total conversations found: {conversations_count}")
            
            data = []

            # Go through each conversation
            for i in range(conversations_count):
                conversation_item = conversations.nth(i)
                await conversation_item.click()
                await self.human_delay()
                messages_area = target_area.locator("div.msg__detail")
                #messages_area = conversation_item.locator("div.scaffold-layout__detail")
                if await messages_area.count() == 0:
                    logger.error("Messages area not found...")
                    continue
                
                participant_name_elem = conversation_item.locator('h3.msg-conversation-listitem__participant-names')
                participant_name = await participant_name_elem.first.inner_text() if await participant_name_elem.count() > 0 else None

                header_bar = messages_area.first.locator('div.shared-title-bar__title')
                if await header_bar.count() == 0:
                    logger.error("Header bar not found...")
                    continue
                
                participant_link_elem = header_bar.first.locator('a')
                participant_link = await participant_link_elem.first.get_attribute('href') if await participant_link_elem.count() > 0 else None

                # If message is sponsored, ignore
                sponsored_chat = messages_area.first.locator("div.msg-spinmail-thread-presenter__message")
                if await sponsored_chat.count() > 0:
                    logger.info("Sponsored message detected, skipping...")
                    continue
                
                # # If message is sponsored
                # sponsored_chat = messages_area.first.locator("div.msg-spinmail-thread-presenter__message")
                # sponsored_chat_header = messages_area.first.locator("div.msg-spinmail-thread-presenter__message-header")
                # top_banner = messages_area.first.locator("div.msg-spinmail-thread-presenter__top-banner")

                # if await sponsored_chat.count() > 0:
                #     content_elem = sponsored_chat.locator("p.msg-spinmail-thread-presenter__message-body")
                #     content_sponsored = await content_elem.first.inner_text() if await content_elem.count() > 0 else None
                # if await sponsored_chat_header.count() > 0:
                #     header_link_elem = sponsored_chat_header.first.locator("a")
                #     sponsored_header_link = await header_link_elem.first.get_attribute("href") if await header_link_elem.count() > 0 else None
                # else:
                #     sponsored_header_link = None
                # if await top_banner.count() > 0:
                #     time_elem = top_banner.first.locator("time")
                #     sponsored_timestamp = await time_elem.first.inner_text() if await time_elem.count() > 0 else None

                chat_box = messages_area.first.locator("div.msg-s-message-list")
                if await chat_box.count() == 0:
                    logger.error("Chat box not found...")
                    continue

                prev_count = 0

                # Get all messages by scrolling to the top
                while True:
                    # Scroll up inside the chat box
                    await chat_box.evaluate("el => el.scrollBy(0, -5000)")
                    await self.page.wait_for_timeout(1000)  # give time for new messages to load

                    # Count messages
                    messages = chat_box.locator("li.msg-s-message-list__event")
                    count = await messages.count()
                    if count == prev_count:
                        break  # no new messages loaded, stop scrolling
                    prev_count = count

                logger.info(f"Total messages found: {count}")

                if count == 0:
                    logger.info("No messages found in the chat")
                    continue
                all_messages = []

                # Go through each message
                for i in range(count):
                    item = messages.nth(i)
                    try:
                        # Date header (only appears sometimes)
                        date_item = item.locator("time.msg-s-message-list__time-heading")
                        if await date_item.count() == 0:
                            date_text = all_messages[i-1]["date"] if i > 0 else None
                        else:
                            date_text = await date_item.first.inner_text()
                            if len(date_text.split(",")) == 1:
                                    date_text = normalize_date_string(date_text)
                            else:
                                date_text = date_text + ", " + str(datetime.now().year)
                            
                        # Message item    
                        msg_item = item.locator("div.msg-s-event-listitem").first
                        msg_metadata = msg_item.locator("div.msg-s-message-group__meta").first

                        # Sender
                        sender = msg_metadata.locator("a")
                        if await sender.count() == 0:
                            sender = all_messages[i-1]["sender"] if i > 0 else None
                        else:
                            sender = await sender.first.inner_text()

                        # Time
                        time_element = msg_metadata.locator("time")
                        if await time_element.count() == 0:
                            time = all_messages[i-1]["time"] if i > 0 else None
                        else:
                            time = await time_element.inner_text()

                        # Content
                        msg_content = msg_item.locator("div.msg-s-event__content")
                        # If no content
                        if await msg_content.count() == 0:
                            content = None
                        else:
                            # Check if message is image
                            img_container = msg_content.first.locator("div.msg-s-event-listitem__image-container")
                            if await img_container.count() > 0:
                                img_src = img_container.first.locator("img")
                                if await img_src.count() > 0:
                                    img_url = await img_src.first.get_attribute("src")
                                    content = img_url if img_url else None
                            else:
                                msg_body = msg_content.first.locator("p.msg-s-event-listitem__body")
                                if await msg_body.count() == 0:
                                    content_elem = msg_item.locator("div.msg-s-event__content")
                                    if await content_elem.count() == 0:
                                        content = None
                                    else:
                                        content = await content_elem.first.inner_text()
                                else:
                                    content = await msg_body.first.inner_text()

                        # Combine date + time into a single string
                        dt_string = f"{date_text} {time}"
                        # Parse into a datetime object
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
                    # Optionally, remove old keys
                    message.pop("date", None)
                    message.pop("time", None)
                # await self.page.goto(participant_link.strip(), wait_until="domcontentloaded")
                # real_participant_link = self.page.url
                # await self.page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
                data.append({
                    "participant_name": participant_name.strip() if participant_name else None,
                    "participant_link": participant_link.strip() if participant_link else None,
                    #"participant_link": real_participant_link.strip() if real_participant_link else None,
                    "chat_history": all_messages
                })
            return data

        except Exception as e:
            logger.error(f"Error fetching messages from chat for participant_link: {e}")
            return False