import re

from playwright.sync_api import Page


class OrderDetailsPage:
    """Read the rendered AXS Overview dashboard for one lab order."""

    CASE_KEYS = ("case number", "case #", "case no", "order number", "order #")
    CASE_OWNER = '[data-cy="caseOwner"] div p'
    SUBMITTED_ON = 'xpath=(//*[normalize-space(text())="Submitted on"]/following-sibling::div)[2]'
    DUE_DATE = 'xpath=(//*[normalize-space(text())="Due date"]/following-sibling::div)[2]'
    PATIENT = 'xpath=(//*[normalize-space(text())="Patient"]/following-sibling::div)[2]'
    COMMENT = 'xpath=//*[normalize-space(text())="Comment"]/following-sibling::div/div'
    CLINIC_NAME = 'xpath=//*[normalize-space(text())="Name"]/following-sibling::div//p'
    CLINIC_PHONE = 'xpath=//*[normalize-space(text())="Phone"]/following-sibling::div'
    CLINIC_MAIL = 'xpath=//*[normalize-space(text())="Mail"]/following-sibling::div'

    def __init__(self, page: Page) -> None:
        self.page = page

    def capture(self) -> dict:
        displayed_text = self.page.locator("body").inner_text()
        captured = self.parse_displayed_text(displayed_text)
        captured["Displayed Text"] = displayed_text.strip()
        clinic_mail = self._valid_email(self._locator_text(self.CLINIC_MAIL))
        confirmed = {
            "Case owner": self._locator_text(self.CASE_OWNER),
            "Submitted on": self._locator_text(self.SUBMITTED_ON),
            "Due date": self._locator_text(self.DUE_DATE),
            "Patient": self._locator_text(self.PATIENT),
            "Comment": self._locator_text(self.COMMENT),
            "Clinic Name": self._locator_text(self.CLINIC_NAME, skip_initials=True),
            "Clinic Phone": self._locator_text(self.CLINIC_PHONE),
            "Clinic Mail": clinic_mail,
        }
        captured.update({key: value for key, value in confirmed.items() if value})
        return captured

    @staticmethod
    def _valid_email(value: str) -> str:
        match = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", value, re.IGNORECASE)
        return match.group(0) if match else ""

    def _locator_text(self, selector: str, skip_initials: bool = False) -> str:
        values = []
        for text in self.page.locator(selector).all_inner_texts():
            values.extend(line.strip() for line in text.splitlines() if line.strip())
        if skip_initials:
            values = [value for value in values if not re.fullmatch(r"[A-Z]{1,3}", value)]
        return "\n".join(dict.fromkeys(values)).strip()

    @classmethod
    def parse_displayed_text(cls, text: str) -> dict:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        result = {}

        def section(start, end=None):
            first = next((i for i, line in enumerate(lines) if line.casefold() == start.casefold()), None)
            if first is None:
                return []
            last = next((i for i in range(first + 1, len(lines)) if end and lines[i].casefold() == end.casefold()), len(lines))
            return lines[first + 1:last]

        def after(label, source, skip_initials=False):
            indexes = [i for i, line in enumerate(source) if line.casefold() == label.casefold()]
            if not indexes:
                return ""
            values = source[indexes[-1] + 1:]
            return next((value for value in values if not (skip_initials and re.fullmatch(r"[A-Z]{1,3}", value))), "")

        order = section("Order information", "Lab slip") or lines
        clinic = section("Clinic information")
        for label in ("Submitted on", "Due date", "Patient", "Type of order", "Sites to restore"):
            value = after(label, order)
            if value:
                result[label] = value
        owner = after("Case owner", order, skip_initials=True)
        if owner:
            result["Case owner"] = owner
        summary = after("Summary", lines)
        if summary:
            result["Summary"] = summary
        lab = after("Lab", lines, skip_initials=True)
        if lab:
            result["Lab"] = lab
        comment_index = next((i for i, line in enumerate(order) if line.casefold() == "comment"), None)
        if comment_index is not None:
            result["Comment"] = "\n".join(order[comment_index + 1:]).strip()
        result["Lab slip"] = "\n".join(section("Lab slip", "Clinic information")).strip()
        for label, key, skip_initials in (("Name", "Clinic Name", True), ("Phone", "Clinic Phone", False), ("Mail", "Clinic Mail", False)):
            value = after(label, clinic, skip_initials)
            if key == "Clinic Mail":
                value = cls._valid_email(value)
            if value:
                result[key] = value
        created = next((line[11:].strip() for line in lines if line.casefold().startswith("created on ")), "")
        if created:
            result["Created on"] = created
        status = next((line for line in lines if line.casefold() in {"in validation", "accepted", "rejected", "submitted", "completed"}), "")
        if status:
            result["Status"] = status
        return result

    @classmethod
    def case_number(cls, details: dict) -> str:
        for key, value in details.items():
            normalized = re.sub(r"\s+", " ", key.lower()).strip()
            if any(candidate in normalized for candidate in cls.CASE_KEYS):
                return str(value).strip()
        match = re.search(r"(?:case|order)\s*(?:number|no\.?|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]+)", details.get("Displayed Text", ""), re.IGNORECASE)
        return match.group(1).strip() if match else ""
