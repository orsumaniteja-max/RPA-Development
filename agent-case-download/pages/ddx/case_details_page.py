from pages.common.base_page import BasePage
import allure
from loguru import logger
import re
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

class CaseDetailsPage(BasePage):

    BODY = "body"
    CASE_ID = "//*[self::h1 or self::h2][contains(normalize-space(), 'Case #')]"
    ACCOUNT_CONTACT_ACTION = "#practice_contact_action"
    ACCOUNT_CONTACT_CONTAINER = "#practice_contact_container"
    # DETAILS = "//*[normalize-space(text())='{}']/ancestor::td/following-sibling::td[1]"
    # OTHER_DETAILS="//div[normalize-space()='{}']/following-sibling::div[1]//table/tbody"

       
    # @allure.step("Get record details {label}")
    # def get_detail(self, label):
    #     locator = self.DETAILS.format(label)
    #     return self.get_text(locator,label)

    @allure.step("Get cases")
    def get_cases(self):
        return self.get_case_id()

    @allure.step("Get case ID")
    def get_case_id(self):
        heading = self.page.locator(self.CASE_ID).first
        heading.wait_for(state="visible")
        match = re.search(r"Case\s*#\s*([^\s]+)", heading.inner_text(), re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @allure.step("Get record detail {label}")
    def get_detail(self, label):
        return self._details_from_text().get(label.rstrip(":"), "")

    # @allure.step("Get case details {label}")
    # def get_case_details_info(self,label):
    #     return self.get_table_text(self.OTHER_DETAILS,label)

    @allure.step("Capture all case information")
    def get_case_information(self):

        details = self._details_from_text()
        details["Case ID"] = self.get_case_id()
        return details

    @allure.step("Capture every visible DDX case detail")
    def get_all_displayed_details(self):
        try:
            self.expand_account_details()
        except PlaywrightTimeoutError:
            # DDX renders practice contacts in the DOM even while collapsed.
            # A failed toggle must not discard those case-specific fields.
            logger.warning("DDX account toggle failed; reading the account panel directly")
        container = self.page.locator(self.ACCOUNT_CONTACT_CONTAINER)
        panel_text = container.text_content(timeout=10000) or ""
        contacts = self._account_contact_from_text(
            "Account:\nPractice\n" + panel_text + "\nProvider:"
        )
        if not any(contacts.values()):
            raise RuntimeError(
                "DDX account contact details could not be read; case was not exported. "
                "Retry capture after checking the account panel."
            )
        body_text = self.page.locator(self.BODY).inner_text().strip()
        information = self.get_case_information()
        information.update(contacts)
        return {
            "Case Information": information,
            "Account Contact Text": panel_text.strip(),
            "Displayed Tables": self._visible_tables(),
            "Displayed Text": body_text,
        }

    def expand_account_details(self):
        """Expand the control beside Account without navigating the account link."""
        container = self.page.locator(self.ACCOUNT_CONTACT_CONTAINER)
        self.page.wait_for_load_state("load", timeout=30000)
        for attempt in range(3):
            if container.is_visible():
                return
            try:
                self.page.locator(self.ACCOUNT_CONTACT_ACTION).click(timeout=10000)
                container.wait_for(state="visible", timeout=10000)
                return
            except PlaywrightTimeoutError:
                if attempt == 2:
                    raise
                logger.warning("DDX account expansion timed out; retrying")

    @staticmethod
    def _account_contact_from_text(text):
        """Limit contact extraction to Account, excluding Provider/patient data."""
        match = re.search(r"\bAccount\s*:(.*?)(?=\bProvider\s*:|$)", text, re.S | re.I)
        if not match:
            return {}
        block = match.group(1)
        if not re.search(r"\b(?:Phone|Email)\s*:", block, re.I):
            return {}
        email = re.search(r"\bEmail\s*:\s*([^\s@]+@[^\s@]+)", block, re.I)
        phone = re.search(r"\bPhone\s*:\s*([+\d][\d ().+\-]*(?:\s*(?:ext\.?|x)\s*\d+)?)", block, re.I)
        # The account name is the first line; address occupies the lines before
        # the contact labels. inner_text preserves the address column's lines.
        address_block = re.split(r"\b(?:Phone|Email)\s*:", block, maxsplit=1, flags=re.I)[0]
        lines = [line.strip() for line in address_block.splitlines() if line.strip()]
        return {
            "Doctor Address": "\n".join(lines[1:]),
            "Doctor Phone": phone.group(1).strip() if phone else "",
            "Doctor Email": email.group(1).strip() if email else "",
        }

    def _details_from_text(self):
        lines = [line.strip() for line in self.page.locator(self.BODY).inner_text().splitlines()]
        lines = [line for line in lines if line]
        labels = {
            "Account", "Provider", "Creation Date", "Send to Lab Date", "Patient",
            "Patient Appointment", "Status", "Shipper", "Delivery Date",
        }
        details = {}
        for index, line in enumerate(lines):
            label = line.rstrip(":")
            if label not in labels:
                continue
            inline_value = line[len(label):].lstrip(":").strip()
            details[label] = inline_value or (lines[index + 1] if index + 1 < len(lines) else "")
        return details

    def _visible_tables(self):
        return self.page.locator("table:visible").evaluate_all("""
            tables => tables.map((table, tableIndex) => {
                const rows = Array.from(table.querySelectorAll('tr')).map(row =>
                    Array.from(row.querySelectorAll('th,td'))
                        .map(cell => cell.innerText.trim())
                        .filter(Boolean)
                ).filter(row => row.length);
                const caption = table.querySelector('caption')?.innerText.trim() || '';
                return {tableNumber: tableIndex + 1, caption, rows};
            }).filter(table => table.rows.length)
        """)


    

    

   
