from pages.common.base_page import BasePage
from utilities.allure_helper import step
import allure
from playwright.sync_api import expect

class DashboardPage(BasePage):

    ADVANCE_SEARCH_LINK="//a[text()='Advanced Search']"
    DETAILS_SECTION="//*[text()='Details']"
    ACTIONS_SECTION="//*[normalize-space(text())='Actions']"
    PRESCRIPTION_BUTTON="//*[text()='Prescription']/../preceding-sibling::span"
    FIRST_RECORD = "[class='table'] [class='data status-cell']"
    NEXT_CASE = "button:has-text('Next')"
    CLOSE_CASE = "i.material-icons:text-is('close')"
    NEXT_PAGE = ".pagination-container button:has-text('keyboard_arrow_right')"
    

    @allure.step("Click on advance search link")
    def click_on_advance_link(self):
        self.click(self.ADVANCE_SEARCH_LINK)

    @allure.step("Select details section")
    def select_details_section(self):
        self.click(self.DETAILS_SECTION)

    @allure.step("Select actions section")
    def select_actions_section(self):
        self.click(self.ACTIONS_SECTION)

    @allure.step("Click on download prescription button")
    def click_on_prescription_download_button(self):
        self.click(self.PRESCRIPTION_BUTTON)

    @allure.step("Save ORI prescription PDF")
    def download_prescription(self, destination):
        self.select_actions_section()
        with self.page.expect_download(timeout=60000) as download_info:
            self.click_on_prescription_download_button()
        download = download_info.value
        destination.parent.mkdir(parents=True, exist_ok=True)
        download.save_as(str(destination))
        self.select_details_section()
        return destination

    @allure.step("Click on first record")
    def open_first_record(self):
        self.click(self.FIRST_RECORD)

    @allure.step("Check whether another ORI case is available")
    def has_next_case(self):
        next_button = self.page.locator(self.NEXT_CASE).first
        return (
            next_button.count()
            and next_button.is_visible()
            and next_button.is_enabled()
        )

    @allure.step("Open next ORI case")
    def open_next_case(self, current_case_id):
        self.page.locator(self.NEXT_CASE).first.click()
        case_id = self.page.locator(
            "//div[text()='Case ID:']/following-sibling::div"
        ).first
        expect(case_id).not_to_contain_text(current_case_id, timeout=90000)

    @allure.step("Close ORI case details")
    def close_case(self):
        close = self.page.locator(self.CLOSE_CASE).first
        if close.count() and close.is_visible():
            close.click()
        else:
            self.page.keyboard.press("Escape")
        self.page.locator(self.FIRST_RECORD).first.wait_for(state="visible")

    @allure.step("Check whether another ORI result page is available")
    def has_next_page(self):
        next_page = self.page.locator(self.NEXT_PAGE).first
        return next_page.count() and next_page.is_visible() and next_page.is_enabled()

    @allure.step("Open next ORI result page")
    def open_next_page(self):
        page_indicator = self.page.locator(".pagination-container .text").first
        current_page = page_indicator.inner_text()
        self.page.locator(self.NEXT_PAGE).first.click()
        expect(page_indicator).not_to_have_text(current_page, timeout=90000)
        self.page.locator(self.FIRST_RECORD).first.wait_for(state="visible")

   

    
