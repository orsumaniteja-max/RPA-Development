from pages.common.base_page import BasePage
from utilities.allure_helper import step
import allure
import re
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

class DashboardPage(BasePage):

    CASE_RECORDS = "text=/^[A-Z]{3}-[0-9]+$/"
    STATUS_DROPDOWN="//div[text()='Status']/.././following-sibling::td/*[@class='gwt-ListBox']"
    ADVANCE_SEARCH_BUTTON="//button[text()='Advanced Search']"
    ACCESS_THE_SERVICE="#login"
    NEXT_PAGE = (
        "button.gwt-Button:has-text('Next'):visible:not([disabled]), "
        ".pagination a:has-text('Next'):visible:not([aria-disabled='true']):not(.disabled):not(.disabled a)"
    )

    @allure.step("Click on advance search link")
    def click_on_advance_link(self):
        self.click(self.ADVANCE_SEARCH_LINK)
        
    @allure.step("Click on access the service")
    def click_on_access_the_service(self):
        self.click(self.ACCESS_THE_SERVICE)

    @allure.step("Select status {text} from dropdown")
    def select_status(self,text):
        self.select_by_text(self.STATUS_DROPDOWN,text)

    @allure.step("Click on first record")
    def click_on_first_record(self):
        self.open_record(0)

    @allure.step("Click on first record")
    def open_first_record(self):
        self.open_record(0)

    @allure.step("Get number of Carestream case records")
    def get_record_count(self):
        return len(self.get_case_numbers())

    @allure.step("Get available Carestream case numbers")
    def get_case_numbers(self):
        selected_heading = self.page.locator("#caseId")
        selected_heading.wait_for(state="visible", timeout=180000)
        heading_box = selected_heading.bounding_box()
        sidebar_right = heading_box["x"] if heading_box else 400
        selected = self.get_selected_case_number()
        case_numbers = []
        for match in self.page.get_by_text(
            re.compile(r"^[A-Z]{3}-\d+$")
        ).all():
            box = match.bounding_box() if match.is_visible() else None
            text = match.inner_text().strip() if box else ""
            if (
                box
                and box["x"] < sidebar_right
                and text != selected
                and text not in case_numbers
            ):
                case_numbers.append(text)
        return case_numbers

    def get_selected_case_number(self):
        return self.page.locator("#caseId").inner_text().strip()

    @allure.step("Open Carestream case record {index}")
    def open_record(self, index):
        self.open_case(self.get_case_numbers()[index])

    @allure.step("Open Carestream case {case_number}")
    def open_case(self, case_number, _attempt=1):
        # The virtualized list briefly redraws after each selection. Let the
        # redraw settle, then resolve fresh locators for every retry.
        self.page.wait_for_timeout(750)
        selected_case = self.page.locator("#caseId")
        heading_box = selected_case.bounding_box()
        sidebar_right = heading_box["x"] if heading_box else 400
        matches = self.page.get_by_text(case_number, exact=True).all()
        record = next(
            (
                match for match in matches
                if match.get_attribute("id") != "caseId"
                and match.is_visible()
                and (match.bounding_box() or {}).get("x", sidebar_right)
                < sidebar_right
            ),
            None,
        )
        if record is None:
            raise AssertionError(
                f"No visible Carestream list row found for case {case_number}"
            )
        record.scroll_into_view_if_needed()

        # Different Carestream builds bind selection at different levels of
        # the nested result-row markup. Try the visible label and its small row
        # ancestors, while excluding broad containers such as the whole list.
        click_targets = [record]
        ancestor = record
        for _ in range(4):
            ancestor = ancestor.locator("xpath=..")
            box = ancestor.bounding_box()
            if (
                box is not None
                and box["width"] <= 500
                and box["height"] <= 180
            ):
                click_targets.append(ancestor)

        for target in click_targets:
            try:
                target.click(timeout=5000)
                # #caseId is already visible, so wait for its value to change.
                expect(selected_case).to_have_text(case_number, timeout=5000)
                return
            except (AssertionError, PlaywrightTimeoutError):
                continue
        if _attempt < 3:
            self.page.wait_for_timeout(1000)
            return self.open_case(case_number, _attempt=_attempt + 1)
        raise AssertionError(
            f"Clicking the Carestream row did not open case {case_number} "
            f"after {_attempt} attempts; "
            f"the selected case remained {selected_case.inner_text().strip()}"
        )

    def has_next_page(self):
        control = self.page.locator(self.NEXT_PAGE).first
        return bool(control.count() and control.is_visible() and control.is_enabled())

    def open_next_page(self):
        self.page.locator(self.NEXT_PAGE).first.click()
        self.page.wait_for_load_state("networkidle", timeout=90000)
        self.page.locator("#caseId").wait_for(state="visible", timeout=90000)

   

    
