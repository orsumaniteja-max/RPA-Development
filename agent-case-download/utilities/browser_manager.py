import os

from playwright.sync_api import sync_playwright

_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-setuid-sandbox",
]

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Removes the navigator.webdriver flag that Vercel/bot-detection checks.
_WEBDRIVER_OVERRIDE = "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"


class BrowserManager:

    def launch_browser(self, browser_name="chromium", headless=False):
        playwright = sync_playwright().start()

        browser = getattr(playwright, browser_name).launch(
            headless=headless,
            args=_STEALTH_ARGS,
        )

        context = browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        context.add_init_script(_WEBDRIVER_OVERRIDE)
        page = context.new_page()

        return playwright, browser, page
