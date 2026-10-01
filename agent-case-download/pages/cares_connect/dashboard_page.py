from pages.common.base_page import BasePage
from utilities.allure_helper import step
import allure
from loguru import logger
import re
from playwright.sync_api import expect

class DashboardPage(BasePage):

    ADVANCE_SEARCH_LINK="//a[text()='Advanced Search']"
    STATUS_DROPDOWN="//div[text()='Status']/.././following-sibling::td/*[@class='gwt-ListBox']"
    ADVANCE_SEARCH_BUTTON="//button[text()='Advanced Search']"
    FIRST_RECORD = "//img[contains(@src,'order')]"
    BODY="body"
    PAGE_RANGE = re.compile(r"Displaying\s+([\d,]+)\s*-\s*([\d,]+)\s+out of\s+([\d,]+)")
    NEXT_PAGE = (
        "button.gwt-Button:has-text('Next'):visible:not([disabled]), "
        ".pagination a:has-text('Next'):visible:not([aria-disabled='true']):not(.disabled):not(.disabled a)"
    )


    @allure.step("Click on advance search link")
    def click_on_advance_link(self):
        self.click(self.ADVANCE_SEARCH_LINK)

    @allure.step("Select status {text} from dropdown")
    def select_status(self,text):
        self.select_by_text(self.STATUS_DROPDOWN,text)

    @allure.step("Click on advance search button")
    def click_on_advance_button(self):
        self.click(self.ADVANCE_SEARCH_BUTTON)

    @allure.step("Click on first record")
    def open_first_record(self):
        self.open_record(0)

    @allure.step("Get number of case records")
    def get_record_count(self):
        self.page.locator(self.FIRST_RECORD).first.wait_for(state="visible")
        return self.get_locator_count(self.FIRST_RECORD)

    @allure.step("Open case record {index}")
    def open_record(self, index):
        self.click(self.FIRST_RECORD, action_name=f"case record {index + 1}", index=index)

    @allure.step("Return to advanced-search results")
    def return_to_search_results(self):
        self.go_back()
        self.page.locator(self.FIRST_RECORD).first.wait_for(state="visible")

    def has_next_page(self):
        indicator = self.page.get_by_text(self.PAGE_RANGE).first
        if indicator.count():
            start, end, total = self._page_range(indicator.inner_text())
            if end >= total:
                return False
            control = indicator.locator("xpath=ancestor::tr[1]").locator("button").last
            if not (control.count() and control.is_visible() and control.is_enabled()):
                raise RuntimeError(f"CARES pagination stopped at {end} of {total}: Next is unavailable")
            return True
        control = self.page.locator(self.NEXT_PAGE).first
        return bool(control.count() and control.is_visible() and control.is_enabled())

    def open_next_page(self):
        indicator = self.page.get_by_text(self.PAGE_RANGE).first
        if indicator.count():
            previous_text = indicator.inner_text()
            _, previous_end, _ = self._page_range(previous_text)
            indicator.locator("xpath=ancestor::tr[1]").locator("button").last.click()
            expect(indicator).not_to_have_text(previous_text, timeout=90000)
            start, end, total = self._page_range(indicator.inner_text())
            if start != previous_end + 1:
                raise RuntimeError(f"CARES pagination skipped or repeated records: {previous_text} -> {start}-{end} of {total}")
            self.page.locator(self.FIRST_RECORD).first.wait_for(state="visible", timeout=90000)
            logger.info("CARES results page: {}-{} of {}", start, end, total)
            return
        self.page.locator(self.NEXT_PAGE).first.click()
        self.page.wait_for_load_state("networkidle", timeout=90000)
        self.page.locator(self.FIRST_RECORD).first.wait_for(
            state="visible", timeout=90000
        )

    @classmethod
    def _page_range(cls, text):
        match = cls.PAGE_RANGE.search(text)
        if not match:
            raise ValueError(f"Unrecognized CARES results range: {text!r}")
        return tuple(int(value.replace(",", "")) for value in match.groups())

    @allure.step("Get data from app")
    def get_data_app(self):
        text=self.get_body_text(self.BODY)
        return text

    # api actions
    @allure.step("fecth application data")
    def get_application_data1(self):
        captured_responses = []

        def handle_response(response):
            try:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    captured_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "body": response.json()
                    })
            except Exception:
                pass  # some responses can't be parsed (redirects, etc.)

            self.on("response", handle_response)
        logger.info("captured_responses: ",captured_responses)
        self.click(self.FIRST_RECORD)

    def get_json_body():
        case_detail = None

        if "case" in ["url"].lower() or "order" in resp["url"].lower():
            case_detail = resp["body"]

        print(json.dumps(case_detail, indent=2))




