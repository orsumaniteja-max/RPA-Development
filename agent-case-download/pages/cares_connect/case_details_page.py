from pages.common.base_page import BasePage
import allure
from loguru import logger
import re
from datetime import datetime

class CaseDetailsPage(BasePage):

    # CARES is a SPA and initially renders empty BDS placeholder elements.
    # Requiring text prevents us from reading a placeholder as the case ID.
    CASE_ID = "//*[contains(@class,'BDS') and normalize-space()]"
    DETAILS = "//*[normalize-space(text())='{}']/ancestor::td/following-sibling::td[1]"
    OTHER_DETAILS="//div[normalize-space()='{}']/following-sibling::div/div/table/tbody"
    manufacturingInfo="//div[normalize-space()='{}']/following-sibling::div/table/tbody"

       
    @allure.step("Get record details {label}")
    def get_detail(self, label):
        locator = self.DETAILS.format(label)
        return self.get_text(locator,label)

    @allure.step("Get case id")
    def get_case_id(self):
        case_id = self.page.locator(self.CASE_ID).first
        case_id.wait_for(state="visible")
        value = case_id.inner_text().strip()
        # CARES adds suffixes such as "(1)" when a search result is repeated.
        # They are display disambiguators, not part of the actual case name.
        source_id = re.sub(r"\s*\(\d+\)\s*$", "", value)
        return self.dated_case_id(source_id, self.get_detail("Date:"))

    @staticmethod
    def dated_case_id(source_id, case_date):
        """Use the portal timestamp to distinguish reused CARES case names."""
        value = " ".join(str(case_date or "").split())
        for date_format in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                timestamp = datetime.strptime(value, date_format)
            except ValueError:
                continue
            if not source_id.strip():
                raise ValueError("CARES case ID is empty")
            return f"{source_id.strip()}_{timestamp:%Y%m%d-%H%M%S}"
        raise ValueError(
            f"CARES case {source_id!r} has a missing or unsupported Date; "
            "cannot safely identify the record"
        )

    @allure.step("Get case details {label}")
    def get_case_details_info(self,label):
        locator = self.OTHER_DETAILS.format(label)
        return self.get_text(locator,label)

    @allure.step("Get manufaturing details {label}")
    def get_manufacturing_details_info(self,label):
        locator = self.manufacturingInfo.format(label)
        return self.get_text(locator,label)

    @allure.step("Capture all case information")
    def get_case_information(self):

        return {
            "Date": self.get_detail("Date:"),
            "Due Date": self.get_detail("Due date:"),
            "Laboratory": self.get_detail("Laboratory:"),
            "Dentist": self.get_detail("Dentist:"),
            "Patient": self.get_detail("Patient:"),
            "Note": self.get_detail("Note")
        }


    

    

   
