from pages.common.base_page import BasePage
import allure
from loguru import logger
import re
from io import BytesIO

class CaseDetailsPage(BasePage):

    CASE_ID = "//*[contains(@class,'BDS')]"
    DETAILS = "//div[text()='{}']/following-sibling::div"
    OTHER_DETAILS = "//div[normalize-space()='{}']/following-sibling::div[1]//table/tbody"
    CASE_STATUSES = {
        "Accepted", "Submitted", "Received", "In Progress", "Completed",
        "Rejected", "Cancelled", "On Hold",
    }
       
    @allure.step("Get record details {label}")
    def get_detail(self, label):
        locator = self.DETAILS.format(label)
        values = self.page.locator(locator)
        if not values.count():
            return ""
        text = values.last.text_content()
        return text.strip() if text else ""

    @allure.step("Get case id")
    def get_case_id(self):
        return self.get_text(self.CASE_ID,"Case ID")

    @allure.step("Get case details {label}")
    def get_case_details_info(self,label):
        return self.get_table_text(self.OTHER_DETAILS,label)

    @allure.step("Capture all case information")
    def get_case_information(self):
        information = {
            "Patient": self.get_detail("Patient:"),
            "Doctor": self.get_detail("Doctor:"),
            "Caseid": self._clean_case_id(self.get_detail("Case ID:")),
            "Fullcaseid": self._clean_full_case_id(self.get_detail("Full Case ID:")),
            "Clinic": self.get_detail("Clinic:"),
            "Lab": self.get_detail("Lab:"),
            "Created": self.get_detail("Created:"),
            "Received": self.get_detail("Received:") or self.get_detail("Recieved:"),
            "Due": self.get_detail("Due:")
        }
        information["Status"] = self.get_status()
        information["License No"] = self.get_license_number()
        return information

    def get_license_number(self):
        """Read the license when exposed in the current case/prescription UI."""
        for label in ("License No.:", "License No:", "License Number:", "Licence No:"):
            value = self.get_detail(label)
            if value:
                return value
        licence = self._license_from_text(self.page.locator("body").inner_text())
        if licence:
            return licence
        # Only fetch a prescription/PDF link actually present on this case.
        links = self.page.locator("a[href]:visible").evaluate_all("""links => links
            .filter(a => /prescription|\\.pdf(?:$|[?#])/i.test(a.href + ' ' + a.innerText))
            .map(a => a.href)""")
        if not links:
            return ""
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError
        except ImportError:
            logger.warning(
                "ORI PDF license extraction unavailable: install pypdf in the Python "
                "environment running the RPA. Continuing capture with fallback identification."
            )
            return ""
        from playwright.sync_api import Error as PlaywrightError
        for url in links:
            try:
                response = self.page.context.request.get(url)
                try:
                    if not response.ok:
                        continue
                    content = response.body()
                finally:
                    response.dispose()
                if not content.startswith(b"%PDF-"):
                    continue
                text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
                license_number = self._license_from_text(text)
                if license_number:
                    return license_number
            except (PlaywrightError, PdfReadError, ValueError, OSError):
                logger.warning("ORI prescription license could not be read; retaining fallback identification")
        return ""

    @staticmethod
    def license_from_pdf(path):
        """Extract the labelled doctor licence from the saved prescription."""
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        return CaseDetailsPage._license_from_text(text)

    @staticmethod
    def _license_from_text(text):
        match = re.search(
            r"\bLicen[cs]e\s*(?:No\.?|Number)\s*:[ \t]*(?:\r?\n[ \t]*)?([^\r\n]*)",
            text, re.I,
        )
        value = match.group(1).strip() if match else ""
        # Validate the whole value line, not the first word of the next label.
        return value if re.fullmatch(r"[A-Za-z0-9-]+", value) else ""

    @allure.step("Get ORI case status")
    def get_status(self):
        statuses = self.page.locator(".status-label")
        if statuses.count():
            return statuses.last.inner_text().strip()
        return ""

    @staticmethod
    def _clean_case_id(value):
        return re.sub(
            r"(?:content_copy|Copied!).*$", "", value, flags=re.IGNORECASE
        ).strip()

    @staticmethod
    def _clean_full_case_id(value):
        value = value.replace("‐", "-").replace("‑", "-").replace("–", "-")
        match = re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            value,
            re.IGNORECASE,
        )
        return match.group(0) if match else value.strip()


    

    

   
