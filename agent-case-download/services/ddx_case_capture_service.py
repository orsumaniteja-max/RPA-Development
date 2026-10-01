"""Capture all currently listed DDX cases and their displayed details."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page

from pages.ddx.case_details_page import CaseDetailsPage
from pages.ddx.dashboard_page import DashboardPage
from pages.ddx.login_page import LoginPage
from services.doctor_catalog_service import DoctorCatalogService
from services.standard_case_payload_service import StandardCasePayloadService
from services.rpa_case_tracking_service import RpaCaseTrackingService


@dataclass(frozen=True)
class DdxCaseCaptureResult:
    case_id: str
    json_file: Path
    text_file: Path
    screenshot_file: Path


class DdxCaseCaptureService:
    def __init__(self, reports_root: Path) -> None:
        self.results_root = Path(reports_root) / "results"
        self.case_tracker = RpaCaseTrackingService("ddx", self.results_root)

    def capture_all_cases(
        self, page: Page, username: str, password: str, max_cases: int | None = None,
        max_new_cases: int | None = None,
    ) -> list[DdxCaseCaptureResult]:
        login = LoginPage(page)
        dashboard = DashboardPage(page)
        details_page = CaseDetailsPage(page)
        doctor_catalog = DoctorCatalogService(self.results_root.parent)
        doctor_catalog.load_and_export()

        login.login(username, password)
        dashboard.click_on_Cases_caret()
        dashboard.click_on_To_Arrive()

        results: dict[str, DdxCaseCaptureResult] = {}
        examined = 0
        while max_cases is None or examined < max_cases:
            record_count = dashboard.get_record_count()
            page_limit = record_count if max_cases is None else min(record_count, max_cases - examined)
            for index in range(page_limit):
                examined += 1
                dashboard.open_record(index)
                case_id = details_page.get_case_id()
                if not case_id:
                    raise ValueError("DDX returned an empty case ID")
                if self.case_tracker.is_downloaded(case_id):
                    dashboard.return_to_case_results()
                    continue
                details = details_page.get_all_displayed_details()
                results[case_id] = self._export(page, case_id, details, doctor_catalog)
                if max_new_cases is not None and len(results) >= max_new_cases:
                    return list(results.values())
                dashboard.return_to_case_results()
            if (max_cases is not None and examined >= max_cases) or not dashboard.has_next_page():
                break
            dashboard.open_next_page()
        return list(results.values())

    def _needs_contact_retry(self, case_id: str) -> bool:
        """Recapture legacy exports that completed with the account collapsed."""
        stem = re.sub(r'[<>:"/\\|?*]', "_", case_id).strip().rstrip(".")
        path = self.results_root / f"{stem}.json"
        if not path.is_file():
            return False
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        contact = payload.get("customerAccount", {}).get("prescriber", {}).get("contact") or {}
        doctor = payload.get("doctorInformation") or {}
        return not any(str(value or "").strip() for value in (
            contact.get("email"), contact.get("phone"), doctor.get("address"),
        ))

    def _export(
        self, page: Page, case_id: str, details: dict,
        doctor_catalog: DoctorCatalogService,
    ) -> DdxCaseCaptureResult:
        self.results_root.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[<>:"/\\|?*]', "_", case_id).strip().rstrip(".")
        case_information = details.get("Case Information", {})
        material = ""
        for table in details.get("Displayed Tables", []):
            rows = table.get("rows", [])
            if len(rows) > 1 and len(rows[1]) > 1:
                material = rows[1][1]
                break
        payload = StandardCasePayloadService.build({
            "Patient": case_information.get("Patient", ""),
            "Doctor": case_information.get("Provider", ""),
            "Case ID": case_id,
            "Created": case_information.get("Creation Date", ""),
            "Case Type": material,
            "Doctor Email": case_information.get("Doctor Email", ""),
        })
        payload.get("patientInfo", {}).pop("id", None)
        contact = payload["customerAccount"]["prescriber"]["contact"]
        contact["phone"] = case_information.get("Doctor Phone", "")
        name = case_information.get("Provider", "") or case_information.get("Account", "")
        name = re.sub(r"^(?:dr|doctor)\.?\s+", "", name.strip(), flags=re.I)
        name = re.sub(r"(?:[\s,]+(?:dds|dmd|md)\.?)+$", "", name, flags=re.I)
        if "," in name:
            last, first = name.split(",", 1)
            parts = first.split()
            contact["first_name"] = parts[0] if parts else ""
            contact["last_name"] = last.strip()
        else:
            parts = name.split()
            contact["first_name"] = parts[0] if parts else ""
            contact["last_name"] = parts[-1] if len(parts) > 1 else ""
        payload["doctorInformation"] = {
            "address": case_information.get("Doctor Address", ""),
            "phone": case_information.get("Doctor Phone", ""),
        }
        doctor_catalog.apply(payload, case_information.get("Account", ""))
        json_file = self.results_root / f"{stem}.json"
        json_file.write_text(
            json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        text_file = self.results_root / f"{stem}.txt"
        account_text = details.get("Account Contact Text", "")
        text_file.write_text(
            f"{details['Displayed Text']}\n\nAccount contact details:\n{account_text}\n",
            encoding="utf-8",
        )
        screenshot_file = self.results_root / f"{stem}.png"
        page.screenshot(path=str(screenshot_file), full_page=True)
        self.case_tracker.record_download(case_id, self.case_tracker.doctor_name(payload))
        return DdxCaseCaptureResult(case_id, json_file, text_file, screenshot_file)
