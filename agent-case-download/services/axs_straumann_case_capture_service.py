"""Capture AXS Straumann Lab Orders in the standard portal format."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from playwright.sync_api import Page

from pages.axs_straumann.lab_orders_page import LabOrdersPage
from pages.axs_straumann.login_page import LoginPage
from pages.axs_straumann.order_details_page import OrderDetailsPage
from services.doctor_catalog_service import DoctorCatalogService
from services.rpa_case_tracking_service import RpaCaseTrackingService
from services.standard_case_payload_service import StandardCasePayloadService


@dataclass(frozen=True)
class AxsCaptureResult:
    case_id: str
    json_file: Path
    text_file: Path
    screenshot_file: Path


class AxsStraumannCaseCaptureService:
    def __init__(self, reports_root: Path) -> None:
        self.results_root = Path(reports_root) / "results"
        self.tracker = RpaCaseTrackingService("axs_straumann", self.results_root)

    def capture_all_cases(
        self, page: Page, username: str, password: str, max_cases: int | None = None,
        max_new_cases: int | None = None,
    ) -> list[AxsCaptureResult]:
        login = LoginPage(page)

        # The page fixture has already launched the configured AXS URL. Finish
        # cookie consent and authentication before doing any capture setup.
        page = login.login(username, password)
        doctors = DoctorCatalogService(self.results_root.parent)
        doctors.load_and_export()
        orders, details = LabOrdersPage(page), OrderDetailsPage(page)
        login.select_company("Roe Dental Lab")
        orders.open()
        results, examined = [], 0
        while max_cases is None or examined < max_cases:
            remaining = orders.record_count()
            if max_cases is not None:
                remaining = min(remaining, max_cases - examined)
            for index in range(remaining):
                examined += 1
                case_id = orders.record_id(index)
                if self.tracker.is_downloaded(case_id):
                    continue
                case_id = orders.open_record(index, case_id)
                raw = details.capture()
                case_id = case_id or details.case_number(raw)
                if not case_id:
                    raise ValueError("AXS Lab Order did not expose an order identifier")
                results.append(self._export(page, case_id, raw, doctors))
                if max_new_cases is not None and len(results) >= max_new_cases:
                    return results
                orders.return_to_orders()
            if (max_cases is not None and examined >= max_cases) or not orders.has_next_page():
                break
            orders.next_page()
        return results

    def _export(self, page, case_id, raw, doctors):
        owner = self._person_name(self._value(raw, "case owner", "doctor"))
        patient = self._meaningful(raw.get("Patient", ""))
        displayed_order_type = str(raw.get("Type of order", "") or "").strip()
        displayed_sites = str(raw.get("Sites to restore", "") or "").strip()
        order_type = self._meaningful(displayed_order_type)
        sites = self._meaningful(displayed_sites)
        comment = self._meaningful(raw.get("Comment", ""))
        payload = StandardCasePayloadService.build({
            "Patient": patient,
            "Doctor": owner,
            "Date": raw.get("Due date", ""),
            "description": comment,
            "Material": order_type,
            "Tooth": sites,
        })
        self._remove_patient_ids(payload)
        if owner:
            payload["customerAccount"]["prescriber"]["name"] = owner
            payload["customerAccount"]["prescriber"]["contact"][
                "displayName"
            ] = StandardCasePayloadService._display_name(owner)
        clinic_name = raw.get("Clinic Name", "") or self._value(
            raw, "practice", "clinic", "account"
        )
        clinic = {
            "name": clinic_name,
            "phone": raw.get("Clinic Phone", ""),
            "email": raw.get("Clinic Mail", ""),
        }
        prescriber = payload["customerAccount"]["prescriber"]
        prescriber["contact"]["email"] = clinic["email"]
        prescriber["contact"]["phone"] = clinic["phone"]
        prescriber["clinic"] = clinic.copy()
        payload["orderInformation"] = {
            "submittedOn": raw.get("Submitted on", ""),
            "createdOn": raw.get("Created on", ""),
            "dueDate": raw.get("Due date", ""),
            "status": raw.get("Status", ""),
            "doctor": owner,
            "patient": patient,
            "summary": self._meaningful(raw.get("Summary", "")),
            "lab": self._meaningful(raw.get("Lab", "")),
            "typeOfOrder": displayed_order_type,
            "sitesToRestore": displayed_sites,
            "comment": comment,
            "labSlip": raw.get("Lab slip", ""),
        }
        payload["clinicInformation"] = clinic
        selected_doctor = doctors.apply(payload, clinic_name, match_name=owner)
        match = getattr(doctors, "last_match", None)
        match_error = getattr(doctors, "last_match_error", None)
        if selected_doctor is not None:
            matched_id = selected_doctor.doctor_id or selected_doctor.account_id
            payload["doctorMatch"] = {
                "status": "matched",
                "method": match.method if match else "catalog",
                "confidence": match.confidence if match else None,
                "matchedIdType": (
                    "doctorId" if selected_doctor.doctor_id else "accountId"
                ),
                "matchedId": matched_id,
            }
        else:
            payload["doctorMatch"] = {
                "status": "humanReviewRequired",
                "reason": match_error or "No doctor database match was selected",
            }
        self.results_root.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[<>:"/\\|?*]', "_", case_id).strip().rstrip(".")
        json_file = self.results_root / f"{stem}.json"
        text_file = self.results_root / f"{stem}.txt"
        screenshot_file = self.results_root / f"{stem}.png"
        json_file.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")
        text_file.write_text(raw.get("Displayed Text", "") + "\n", encoding="utf-8")
        page.screenshot(path=str(screenshot_file), full_page=True)
        self.tracker.record_download(case_id, self.tracker.doctor_name(payload))
        return AxsCaptureResult(case_id, json_file, text_file, screenshot_file)

    @staticmethod
    def _value(source, *names):
        for key, value in source.items():
            if any(name in key.lower() for name in names) and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _person_name(value):
        """Return the case owner's displayed name, excluding avatar initials/practice."""
        lines = [line.strip() for line in str(value).splitlines() if line.strip()]
        return next((line for line in lines if len(line) > 3), lines[0] if lines else "")

    @staticmethod
    def _meaningful(value):
        value = str(value or "").strip()
        return "" if value == "-" else value

    @classmethod
    def _remove_patient_ids(cls, value, parent_key=""):
        """Remove patient identifiers at any depth without removing the case number."""
        if isinstance(value, dict):
            for key in list(value):
                normalized = re.sub(r"[^a-z]", "", str(key).casefold())
                if normalized in {"patientid", "patientidentifier"} or (
                    normalized == "id" and parent_key == "patientinfo"
                ):
                    value.pop(key, None)
                else:
                    cls._remove_patient_ids(value[key], normalized)
        elif isinstance(value, list):
            for item in value:
                cls._remove_patient_ids(item, parent_key)
