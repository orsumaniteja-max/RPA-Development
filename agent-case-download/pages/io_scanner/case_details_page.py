from pages.common.base_page import BasePage
import allure
from loguru import logger
import re

class CaseDetailsPage(BasePage):

    CASE_ID = "//*[contains(@class,'BDS')]"
    DETAILS = "//span[text()='{}']/following-sibling::span"
    PATIENT_DETAILS = "(//*[@class='ant-space-item']/span)[{}]"
    OTHER_DETAILS="//*[normalize-space()='{}']/following-sibling::a"
    DIALOG = "[role='dialog']:visible, .ant-modal-content:visible"
    LABEL_ALIASES = {
        "Doctor:": "order.svg.enum6",
        "Order Number:": "order.detail.enum2",
        "Organization Information:": "order.svg.enum7",
    }

       
    @allure.step("Get record details {label}")
    def get_detail(self, label):
        return self._get_labeled_text(self.DETAILS, label)

    @allure.step("Get patient {index}")
    def get_patient_details(self,index):
        locator = self.PATIENT_DETAILS.format(index + 1)
        return self.get_text(locator, index)

    @allure.step("Get case details {label}")
    def get_case_details_info(self,label):
        return self._get_labeled_text(self.OTHER_DETAILS, label)

    def _get_labeled_text(self, template, label):
        labels = (label, self.LABEL_ALIASES.get(label))
        for candidate in filter(None, labels):
            locator = self.page.locator(template.format(candidate))
            if locator.count() and locator.first.is_visible():
                return self.get_text(template.format(candidate), label)
        return ""

    @allure.step("Capture all case information")
    def get_case_information(self):
        information = {
            "Doctor": self.get_case_details_info("Doctor:"),
            "Order Number": self.get_detail("Order Number:"),
            "Organization Information": self.get_case_details_info("Organization Information:"),
            "Update Time": self.get_detail("Update Time:"),
            "Patient Name": self.get_patient_details(0),
            "Lab": self.get_patient_details(1),
            "Upload Time": self.get_patient_details(2),
            "Case Type": self.get_patient_details(3),
            "Remark": self.get_detail("Remark:"),
        }
        information["Organization Details"] = self.get_linked_information(
            "Organization Information:"
        )
        information["Doctor Information"] = self.get_linked_information("Doctor:")
        information["Lab Information"] = self.get_lab_information()
        return information

    @allure.step("Open and capture {label}")
    def get_linked_information(self, label):
        link = None
        for candidate in (label, self.LABEL_ALIASES.get(label)):
            if not candidate:
                continue
            candidate_link = self.page.locator(self.OTHER_DETAILS.format(candidate)).first
            if candidate_link.count() and candidate_link.is_visible():
                link = candidate_link
                break
        if link is None:
            return {}
        link.click()
        dialog = self.page.locator(self.DIALOG).last
        dialog.wait_for(state="visible")
        text = dialog.inner_text().strip()
        information = self._parse_information(text)
        input_values = [
            value.strip()
            for value in dialog.locator("input").evaluate_all(
                "elements => elements.map(element => element.value)"
            )
            if value.strip()
        ]
        if input_values:
            information["Input Values"] = input_values
            email = next((value for value in input_values if "@" in value), "")
            if email:
                information["Email"] = email
        close = dialog.locator("button[aria-label='Close'], .ant-modal-close")
        if close.count():
            close.first.click()
        else:
            self.page.keyboard.press("Escape")
        return information

    @allure.step("Capture lab information")
    def get_lab_information(self):
        labels = ("Lab Information:", "Lab:")
        for label in labels:
            value = self.page.locator(
                f"//*[normalize-space()='{label}']/following-sibling::*[1]"
            )
            if value.count() and value.first.is_visible():
                return self._parse_information(value.first.inner_text())

        body_text = self.page.locator("body").inner_text()
        match = re.search(
            r"Lab Information\s*:?\s*([^\r\n]+)", body_text, re.IGNORECASE
        )
        if match:
            return {"Name": match.group(1).strip()}
        lab_name = self.page.get_by_text(re.compile(r"\bDental Laboratory\b"))
        if lab_name.count():
            return {"Name": lab_name.first.inner_text().strip()}
        return {}

    @staticmethod
    def _parse_information(text):
        """Parse label/value content while retaining all displayed information."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        information = {"Displayed Text": text}
        fallback_labels = {
            "order.svg.enum15": "Contact Person",
            "order.svg.enum16": "Country",
            "order.svg.enum17": "Address",
            "order.svg.enum14": "Contact Information",
        }
        for index, line in enumerate(lines):
            if line in fallback_labels and index + 1 < len(lines):
                information[fallback_labels[line]] = lines[index + 1]
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                if key.strip():
                    information[key.strip()] = value.strip()
            elif line.lower() in {
                "country", "address", "contact person", "contact information",
                "name", "email", "phone", "telephone",
            } and index + 1 < len(lines):
                information[line] = lines[index + 1]

        email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        if email_match:
            information["Email"] = email_match.group(0)
        return information


    

    

   
