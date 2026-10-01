from pages.common.base_page import BasePage
from utilities.allure_helper import step
import allure
import re
from playwright.sync_api import expect

class DashboardPage(BasePage):

    ADVANCE_SEARCH_LINK="//a[text()='Advanced Search']"
    STATUS_DROPDOWN="//div[text()='Status']/.././following-sibling::td/*[@class='gwt-ListBox']"
    ADVANCE_SEARCH_BUTTON="//button[text()='Advanced Search']"
    FIRST_RECORD = "[class='ant-table-body'] a"
    CASE_ROWS = ".ant-table-body tbody tr:not(.ant-table-measure-row):visible"
    NEXT_PAGE = ".ant-pagination-next:not(.ant-pagination-disabled) button:visible"
    

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

    @allure.step("Get number of IO Scanner case records")
    def get_record_count(self):
        return len(self.get_case_numbers())

    @allure.step("Get unique IO Scanner case numbers")
    def get_case_numbers(self):
        links = self.page.locator(self.FIRST_RECORD)
        links.first.wait_for(state="visible", timeout=90000)
        texts = links.all_inner_texts()
        return list(dict.fromkeys(
            text.strip() for text in texts
            if re.fullmatch(r"\d+_\d+", text.strip())
        ))

    @allure.step("Open IO Scanner case record {index}")
    def open_record(self, index):
        self.open_case(self.get_case_numbers()[index])

    @allure.step("Open IO Scanner case {case_number}")
    def open_case(self, case_number):
        self.page.locator(self.FIRST_RECORD).get_by_text(
            case_number, exact=True
        ).first.click()
        self.page.locator(
            "text=/^(Order Details|order\\.detail\\.enum1)$/"
        ).first.wait_for(state="visible", timeout=90000)
        current_order = self.page.locator(
            "//span[normalize-space()='Order Number:' "
            "or normalize-space()='order.detail.enum2']/following-sibling::span"
        ).first
        expect(current_order).to_have_text(case_number, timeout=90000)

    @allure.step("Return to IO Scanner case list")
    def return_to_case_list(self):
        self.go_back()
        self.page.locator(self.CASE_ROWS).first.wait_for(
            state="visible", timeout=90000
        )

    def has_next_page(self):
        control = self.page.locator(self.NEXT_PAGE).first
        return bool(control.count() and control.is_visible() and control.is_enabled())

    def open_next_page(self):
        current_cases = self.get_case_numbers()
        self.page.locator(self.NEXT_PAGE).first.click()
        if current_cases:
            expect(self.page.locator(self.FIRST_RECORD).first).not_to_have_text(
                current_cases[0], timeout=90000
            )

   

    
