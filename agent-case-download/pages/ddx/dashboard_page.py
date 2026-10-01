from pages.common.base_page import BasePage
from utilities.allure_helper import step
import allure
from playwright.sync_api import expect

class DashboardPage(BasePage):

    DASHBOARD = "//a[text()='Dashboard ']"
    CASES_CARET = "//a[text()='Cases ']"
    CASE_RECORDS = "//tr/td[4]//a"
    CASE_HEADING = "//*[self::h1 or self::h2][contains(normalize-space(), 'Case #')]"
    # VIEW_DETAILS = "(//button[contains(text(),'View Details')])[1]"
    # DDX renders duplicate desktop/mobile navigation links. Restrict this to
    # the currently visible link so BasePage.click(...).first does not select
    # the hidden copy.
    TO_ARRIVE = "a[href*='filter=arrive']:visible"
    NEXT_PAGE = (
        ".pagination li.next:not(.disabled) a:visible, "
        ".pagination a[rel='next']:visible:not([aria-disabled='true']):not(.disabled):not(.disabled a)"
    )

    # @allure.step("Click on Dashboard")
    # def click_on_Dashboard(self):
    #     self.click(self.DASHBOARD)

    # @allure.step("Select Partner Labs from dropdown")
    # def select_Partner_Labs(self):
    #     self.click(self.PATNER_LABS_DROPDOWN)

    @allure.step("Click on Cases caret button")
    def click_on_Cases_caret(self):
        self.click(self.CASES_CARET)

    @allure.step("Click on To Arrive")
    def click_on_To_Arrive(self):
        self.click(self.TO_ARRIVE)

    # @allure.step("Click on Case")
    # def click_on_Case(self):
    #     self.click(self.CASE) 

    @allure.step("Click on first record")
    def open_first_record(self):
        self.open_record(0)

    @allure.step("Get number of DDX case records")
    def get_record_count(self):
        records = self.page.locator(self.CASE_RECORDS)
        records.first.wait_for(state="visible")
        return records.count()

    @allure.step("Open DDX case record {index}")
    def open_record(self, index):
        record = self.page.locator(self.CASE_RECORDS).nth(index)
        record.scroll_into_view_if_needed()
        with self.page.expect_navigation(
            wait_until="domcontentloaded", timeout=90000
        ):
            record.click()
        self.page.locator(self.CASE_HEADING).first.wait_for(
            state="visible", timeout=90000
        )

    @allure.step("Return to DDX case results")
    def return_to_case_results(self):
        self.page.go_back(wait_until="domcontentloaded", timeout=90000)
        self.page.locator(self.CASE_RECORDS).first.wait_for(
            state="visible", timeout=90000
        )

    def has_next_page(self):
        control = self.page.locator(self.NEXT_PAGE).first
        return bool(control.count() and control.is_visible() and control.is_enabled())

    def open_next_page(self):
        first_case = self.page.locator(self.CASE_RECORDS).first
        current_href = first_case.get_attribute("href")
        self.page.locator(self.NEXT_PAGE).first.click()
        first_case.wait_for(state="visible", timeout=90000)
        if current_href:
            expect(first_case).not_to_have_attribute("href", current_href, timeout=90000)

    # @allure.step("Click on View Details")
    # def open_View_Details(self):
    #     self.click(self.VIEW_DETAILS)
        

   

    
