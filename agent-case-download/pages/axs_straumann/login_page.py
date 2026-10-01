import re
import time
from pathlib import Path
from pages.common.base_page import BasePage
from loguru import logger
from utilities.allure_helper import step
import allure
from playwright.sync_api import (
    Error as PlaywrightError,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)   


class LoginPage(BasePage):

    

    def __init__(self, page: Page) -> None:
        self.page = page
        self.context = page.context

    COOKIE_BUTTON_NAME = re.compile(
        r"accept(?: all)?(?: cookies)?|allow all|agree|i accept", re.IGNORECASE
    )
    USERNAME = (
        "[name='loginID'], #signInName, [name='SignInName'], "
        "input[name='email'], input[type='email'], main input:not([type='checkbox'])"
    )
    PASSWORD = (
        "[name='password'], [name='Password'], #password, "
        "input[type='password']"
    )
    SUBMIT = "button[type='submit'], #next"
    
    def accept_cookies(self) -> bool:
        """Accept the optional consent banner, including iframe-hosted banners."""
        for frame in self.page.frames:
            cookie_button = frame.get_by_role(
                "button", name=self.COOKIE_BUTTON_NAME
            ).or_(frame.locator(
                "#onetrust-accept-btn-handler, [data-testid*='accept' i], "
                "button[id*='accept' i]"
            ))
            try:
                cookie_button.first.wait_for(state="visible", timeout=1500)
                cookie_button.first.click()
                return True
            except PlaywrightTimeoutError:
                continue
            except PlaywrightError as error:
                # Consent is optional and its document may be replaced by the
                # expected AXS/B2C redirect while this short probe is pending.
                # Do not suppress unrelated selector, click, or browser errors.
                if "frame was detached" in str(error).casefold() and frame.is_detached():
                    return False
                if (
                    error.__class__.__name__ == "TargetClosedError"
                    and "target page, context or browser has been closed"
                    in str(error).casefold()
                    and self._adopt_live_page()
                ):
                    return False
                raise
        return False

    def _adopt_live_page(self) -> bool:
        """Adopt an auth replacement page; return false if the context was closed."""
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                live_pages = [page for page in self.context.pages if not page.is_closed()]
            except PlaywrightError:
                return False
            if live_pages:
                self.page = live_pages[-1]
                self.page.bring_to_front()
                return True
            time.sleep(0.1)
        return False

    def _submit_login(self):
        submit = self.page.locator(self.SUBMIT).first
        if submit.count() and submit.is_visible():
            return submit
        return self.page.get_by_role(
            "button", name=re.compile(r"^login$", re.IGNORECASE)
        ).last

   

    @allure.step("Login with username: {username}")
    def login(self, username, password):
        self.accept_cookies()
        first_login = self.page.get_by_role(
            "button", name=re.compile(r"^log in$", re.IGNORECASE)
        ).first
        try:
            first_login.wait_for(state="visible", timeout=10000)
            first_login.click()
        except PlaywrightTimeoutError:
            pass

        self.accept_cookies()

        # Cookie consent or the identity redirect may replace the page. Resolve
        # credential locators only after the optional consent step completes.
        username_input = self.page.locator(self.USERNAME).first
        password_input = self.page.locator(self.PASSWORD).first
        try:
            username_input.wait_for(state="visible", timeout=90000)
        except PlaywrightTimeoutError as error:
            page_title = self.page.title()
            raise RuntimeError(
                "AXS username form did not load: "
                f"url={self.page.url!r}, title={page_title!r}"
            ) from error

        # The Straumann React form has previously discarded values entered with
        # fill(). Keyboard events update its controlled username state reliably.
        username_input.fill(username)
        if username_input.input_value() != username:
            username_input.click()
            username_input.press_sequentially(username, delay=25)

        # Azure B2C may render username and password together or as two steps.
        # Advance the username step only when the password is not already shown.
        if not password_input.is_visible():
            main_inputs = self.page.locator(
                "main input:not([type='checkbox'])"
            )
            if main_inputs.count() >= 2:
                password_input = main_inputs.last
            else:
                self._submit_login().click()
                password_input.wait_for(state="visible", timeout=90000)

        password_input.fill(password)
        if username_input.input_value() != username:
            raise AssertionError("AXS username field did not retain the entered value")
        if password_input.input_value() != password:
            raise AssertionError("AXS password field did not retain the entered value")

        context = self.context
        self._submit_login().click()
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            for candidate in reversed(context.pages):
                if candidate.is_closed():
                    continue
                company = candidate.get_by_text("Roe Dental Lab", exact=False).first
                if company.is_visible():
                    self.page = candidate
                    self.page.bring_to_front()
                    logger.info("Successfully login into the application")
                    return self.page

                error = candidate.get_by_text(
                    re.compile(r"invalid .*username|invalid .*password|login failed", re.IGNORECASE)
                ).first
                if error.is_visible():
                    raise RuntimeError(f"AXS login failed: {error.inner_text().strip()}")
            time.sleep(0.25)

        urls = [candidate.url for candidate in context.pages if not candidate.is_closed()]
        failure_path = (
            Path(__file__).resolve().parents[2]
            / "reports" / "axs_straumann" / "login_failure.png"
        )
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.page.is_closed():
            self.page.screenshot(path=str(failure_path), full_page=True)
        raise TimeoutError(f"AXS did not reach company selection after login: {urls}")

    def select_company(self, company: str) -> None:
        choice = self.page.get_by_text(company, exact=False).first
        choice.wait_for(state="visible", timeout=90000)
        choice.click()
        confirm = self.page.get_by_role(
            "button",
            name=re.compile(r"select|open|continue|confirm", re.IGNORECASE),
        )
        if confirm.count() and confirm.first.is_visible():
            confirm.first.click()
        self.page.get_by_text("Lab orders", exact=False).first.wait_for(
            state="visible", timeout=90000
        )
