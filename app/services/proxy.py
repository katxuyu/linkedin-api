import httpx
import pandas as pd
import re
from playwright.async_api import async_playwright
from datetime import datetime, timedelta

class Proxy:
    def __init__(self):
        pass

    async def extract_free_proxy_table(self, url="https://free-proxy-list.net/"):
        """Extract proxy table, filter elite proxies checked within the last hour, and return as list of dictionaries."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=60000)

            # Wait for the proxy table
            table = page.get_by_role("table").filter(has_text="IP Address")
            await table.wait_for(state="visible")

            # Locate columns
            columns = table.locator("thead tr th")
            column_count = await columns.count()
            column_names = []
            for i in range(column_count):
                column_names.append(await columns.nth(i).text_content())

            # Locate rows
            rows = table.locator("tbody tr")
            row_count = await rows.count()
            data = []
            for i in range(row_count):
                cols = rows.nth(i).locator("td")
                values = [await cols.nth(j).inner_text() for j in range(column_count)]

                data.append(dict(zip(column_names, values)))

            await browser.close()

        # Put into DataFrame
        df = pd.DataFrame(data)

        # --- Filter ---
        df = df[df["Anonymity"].str.lower() == "elite proxy"].copy()

        # Parse "Last Checked"
        def parse_last_checked(x: str):
            """
            Convert strings like '1 sec ago', '3 mins ago', '1 hour 41 mins ago'
            into a datetime.
            """
            total_seconds = 0
            parts = re.findall(r"(\d+)\s+(\w+)", x)

            for value, unit in parts:
                value = int(value)
                if "sec" in unit:
                    total_seconds += value
                elif "min" in unit:
                    total_seconds += value * 60
                elif "hour" in unit:
                    total_seconds += value * 3600

            return datetime.now() - timedelta(seconds=total_seconds)

        df["LastCheckedTime"] = df["Last Checked"].apply(parse_last_checked)

        # Keep only last hour
        one_hour_ago = datetime.now() - timedelta(hours=1)
        df = df[df["LastCheckedTime"] >= one_hour_ago]

        # Format output
        proxies = []
        for _, row in df.iterrows():
            protocol = "https" if row["Https"].lower() == "yes" else "http"
            proxies.append({"server": f"{protocol}://{row['IP Address']}:{row['Port']}"})

        return proxies

    async def extract_geonode_proxy_table(
        self, 
        api_url="https://proxylist.geonode.com/api/proxy-list?limit=500&sort_by=lastChecked&sort_type=desc"
    ):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            data = response.json()["data"]

        # Filter and format
        proxies = []
        for item in data:
            if item.get("upTime", 100) >= 95:  # filter out < 95
                ip = item["ip"]
                port = item["port"]
                protocols = item.get("protocols", ["http"])
                protocol = protocols[0]  # pick first available protocol
                proxies.append({"server": f"{protocol}://{ip}:{port}"})

        return proxies
        
    async def load_all_proxies(self):
        geonode_proxies = await self.extract_geonode_proxy_table()
        free_proxies = await self.extract_free_proxy_table()
        return geonode_proxies + free_proxies