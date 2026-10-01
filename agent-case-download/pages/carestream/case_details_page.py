from pages.common.base_page import BasePage
import allure
import re

class CaseDetailsPage(BasePage):

    CASE_ID = "#caseId"
    DETAILS = "#detailsTitlesData"
    PARTNER_MORE = "#detailsTitlesData :text-is('More')"
       
    @allure.step("Get record details {label}")
    def get_detail(self, label):
        locator = self.DETAILS.format(label)
        return self.get_text(locator,label)

    @allure.step("Get case id")
    def get_case_id(self):
        return self.get_text(self.CASE_ID,"Case ID")

    @allure.step("Capture all case information")
    def get_case_information(self):

        more = self.page.locator(self.PARTNER_MORE)
        if more.count() and more.first.is_visible():
            more.first.click()

        details_text = self.get_detail("Details")
        fields = self._parse_details(details_text)
        fields["Details"] = details_text
        fields["Summary"] = self.get_summary_information()
        return fields

    @allure.step("Capture case summary")
    def get_summary_information(self):
        body_text = self.page.locator("body").inner_text()
        comment_match = re.search(
            r"^\s*Comment\s*:\s*([^\r\n]*)", body_text, re.IGNORECASE | re.MULTILINE
        )
        due_date_match = re.search(
            r"^\s*Due Date\s*:\s*([^\r\n]*)", body_text, re.IGNORECASE | re.MULTILINE
        )
        return {
            "Comment": comment_match.group(1).strip() if comment_match else "",
            "Due Date": due_date_match.group(1).strip() if due_date_match else "",
        }

    @staticmethod
    def _parse_details(details_text):
        """Convert Carestream's label/value panel into exportable fields."""
        address_match = re.search(r"(?:�)?Close\s*(.+)$", details_text, re.DOTALL)
        doctor_address = address_match.group(1).strip() if address_match else ""
        if address_match:
            details_text = details_text[:address_match.start()]
        lines = [line.strip() for line in details_text.splitlines() if line.strip()]
        labels = {
            "Status", "Partner", "Submission date", "Type", "Modality",
            "Acquisition date", "Gender", "Date of birth",
        }
        parsed = {}
        for index, line in enumerate(lines):
            if line not in labels:
                continue
            values = []
            for value in lines[index + 1:]:
                if value in labels:
                    break
                if value.lower() != "more":
                    values.append(value)
            parsed[line] = "\n".join(values).strip()

        partner = parsed.pop("Partner", "")
        email_match = re.search(r"\(([^()\s]+@[^()\s]+)\)", partner)
        doctor_email = email_match.group(1).strip() if email_match else ""
        partner_without_email = re.sub(
            r"\s*\([^()]*@[^()]*\)\s*", "\n", partner, count=1
        )
        partner_lines = [
            line.strip() for line in partner_without_email.splitlines() if line.strip()
        ]
        parsed["Doctor"] = partner_lines[0] if partner_lines else ""
        parsed["Doctor Email"] = doctor_email
        parsed["Doctor Address"] = doctor_address or "\n".join(partner_lines[1:])
        return parsed
