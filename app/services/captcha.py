import requests
import asyncio
from playwright.async_api import async_playwright
from app.settings import TWO_CAPTCHA_API_KEY

class CaptchaSolver:
    def __init__(self):
        self.api_key = TWO_CAPTCHA_API_KEY
        self.method_map = {
            "funcaptcha": "funcaptcha",
            "recaptcha": "userrecaptcha",
            "hcaptcha": "hcaptcha"
        }

    async def detect_captcha(self, page, page_url):
        """Detect the type of CAPTCHA on the page and return relevant metadata."""
        try:
            # Check for FunCAPTCHA (Arkose Labs)
            fun_captcha_iframe = await page.query_selector("iframe[src*='arkoselabs.com']")
            if fun_captcha_iframe:
                print("Detected FunCAPTCHA (Arkose Labs)")
                site_key = await page.evaluate(
                    """() => {
                        const iframe = document.querySelector('iframe[src*="arkoselabs.com"]');
                        if (iframe) {
                            const url = new URL(iframe.src);
                            return url.searchParams.get('pk') || 'default_site_key';
                        }
                        return null;
                    }"""
                )
                if site_key:
                    return {"type": "funcaptcha", "site_key": site_key, "page_url": page_url}
                print("FunCAPTCHA detected but no site key found.")
                return None

            # Check for reCAPTCHA (Google)
            recaptcha_iframe = await page.query_selector("iframe[src*='recaptcha/api2']")
            if not recaptcha_iframe:
                recaptcha_iframe = await page.query_selector("iframe[src*='gstatic.com/recaptcha']")
            if recaptcha_iframe:
                print("Detected reCAPTCHA (Google)")
                site_key = await page.evaluate(
                    """() => {
                        const script = document.querySelector('script[src*="recaptcha/api.js"]');
                        if (script) {
                            const url = new URL(script.src);
                            return url.searchParams.get('render') || document.querySelector('.g-recaptcha')?.getAttribute('data-sitekey') || 'default_site_key';
                        }
                        return null;
                    }"""
                )
                if site_key:
                    return {"type": "recaptcha", "site_key": site_key, "page_url": page_url}
                print("reCAPTCHA detected but no site key found.")
                return None

            # Check for hCaptcha
            hcaptcha_iframe = await page.query_selector("iframe[src*='hcaptcha.com']")
            if hcaptcha_iframe:
                print("Detected hCaptcha")
                site_key = await page.evaluate(
                    """() => {
                        const div = document.querySelector('div[data-hcaptcha-widget-id]');
                        return div ? div.getAttribute('data-sitekey') : null;
                    }"""
                )
                if site_key:
                    return {"type": "hcaptcha", "site_key": site_key, "page_url": page_url}
                print("hCaptcha detected but no site key found.")
                return None

            # Check for generic CAPTCHA elements
            generic_captcha = await page.query_selector("div[id*='captcha'], div[class*='captcha']")
            if generic_captcha:
                print("Detected potential custom CAPTCHA")
                return {"type": "unknown", "site_key": None, "page_url": page_url}

            print("No CAPTCHA detected.")
            return {"type": None, "site_key": None, "page_url": page_url}
        except Exception as e:
            print(f"Error detecting CAPTCHA: {e}")
            return None
        
    async def solve_captcha(self, page, captcha_info):
        """Solve CAPTCHA using 2Captcha service based on detected type."""
        if not captcha_info or captcha_info["type"] is None:
            print("No CAPTCHA to solve.")
            return True

        captcha_type = captcha_info["type"]
        site_key = captcha_info["site_key"]
        page_url = captcha_info["page_url"]
        print(f"Attempting to solve {captcha_type} CAPTCHA...")

        if captcha_type not in self.method_map:
            print(f"Unsupported CAPTCHA type: {captcha_type}")
            return False

        try:
            # Submit CAPTCHA to 2Captcha
            response = requests.post(
                "http://2captcha.com/in.php",
                data={
                    "key": self.api_key,
                    "method": self.method_map[captcha_type],
                    "publickey": site_key,
                    "pageurl": page_url,
                    "json": 1
                }
            )
            result = response.json()
            if result["status"] != 1:
                print(f"Failed to submit {captcha_type} CAPTCHA to 2Captcha: {result['error_text']}")
                return False

            captcha_id = result["request"]
            print(f"{captcha_type} CAPTCHA submitted, ID: {captcha_id}")

            # Poll for solution
            for _ in range(30):  # Try for up to 60 seconds
                await asyncio.sleep(2)
                response = requests.get(
                    f"http://2captcha.com/res.php?key={self.api_key}&action=get&id={captcha_id}&json=1"
                )
                result = response.json()
                if result["status"] == 1:
                    print(f"{captcha_type} CAPTCHA solved successfully!")
                    # Apply solution based on CAPTCHA type
                    if captcha_type == "funcaptcha":
                        await page.evaluate(
                            f"""(solution) => {{
                                window.arkoseCallback && window.arkoseCallback(solution);
                                const input = document.querySelector('input[name="fc-token"]');
                                if (input) input.value = solution;
                            }}""",
                            result["request"]
                        )
                    elif captcha_type in ["recaptcha", "hcaptcha"]:
                        await page.evaluate(
                            f"""(solution) => {{
                                const textarea = document.querySelector('textarea[id*="response"]');
                                if (textarea) textarea.value = solution;
                                const callback = window.grecaptcha?.callback || window.hcaptcha?.onloadCallback;
                                if (callback) callback(solution);
                            }}""",
                            result["request"]
                        )
                    return True
                elif result["status"] == 0 and "CAPCHA_NOT_READY" in result["request"]:
                    continue
                else:
                    print(f"{captcha_type} CAPTCHA solving failed: {result['error_text']}")
                    return False

            print(f"{captcha_type} CAPTCHA solving timed out.")
            return False
        except Exception as e:
            print(f"Error solving {captcha_type} CAPTCHA: {e}")
            return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        page_url = "https://test.cap.guru/demo/funcap#funcap4"
        await page.goto(page_url)  # Example page with FunCAPTCHA
        await page.wait_for_timeout(20000)  # Wait for 20 seconds
        captcha_solver = CaptchaSolver()
        captcha_info = await captcha_solver.detect_captcha(page, page_url)
        if captcha_info:
            await captcha_solver.solve_captcha(page, captcha_info)
        await page.close()
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())