"""Capture every case available in the ORI Portal case viewer."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from playwright.sync_api import Page

from pages.ori_portal.case_details_page import CaseDetailsPage
from pages.ori_portal.dashboard_page import DashboardPage
from pages.ori_portal.login_page import LoginPage
from services.standard_case_payload_service import StandardCasePayloadService
from services.doctor_catalog_service import DoctorCatalogService
from services.rpa_case_tracking_service import RpaCaseTrackingService


@dataclass(frozen=True)
class OriCaseCaptureResult:
    case_id: str
    json_file: Path
    text_file: Path
    screenshot_file: Path
    prescription_file: Path | None = None


class OriCaseCaptureService:
    def __init__(self, reports_root: Path) -> None:
        self.results_root = Path(reports_root) / "results"
        self.case_tracker = RpaCaseTrackingService("ori_portal", self.results_root)

    def capture_all_cases(
        self, page: Page, username: str, password: str, max_cases: int | None = None,
        max_new_cases: int | None = None,
    ) -> list[OriCaseCaptureResult]:
        login = LoginPage(page)
        dashboard = DashboardPage(page)
        details_page = CaseDetailsPage(page)
        doctor_catalog = DoctorCatalogService(self.results_root.parent)
        doctor_catalog.load_and_export()

        login.login(username, password)
        results = {}
        examined = 0
        while max_cases is None or examined < max_cases:
            dashboard.open_first_record()
            dashboard.select_details_section()
            while True:
                examined += 1
                case_id = details_page._clean_case_id(details_page.get_detail("Case ID:"))
                if not case_id:
                    raise ValueError("ORI Portal returned a case without a Case ID")
                if not self.case_tracker.is_downloaded(case_id):
                    information = details_page.get_case_information()
                    results[case_id] = self._export(
                        page, case_id, information, doctor_catalog
                    )
                    if max_new_cases is not None and len(results) >= max_new_cases:
                        return list(results.values())
                if (max_cases is not None and examined >= max_cases) or not dashboard.has_next_case():
                    break
                dashboard.open_next_case(case_id)

            dashboard.close_case()
            if (max_cases is not None and examined >= max_cases) or not dashboard.has_next_page():
                break
            dashboard.open_next_page()
        return list(results.values())

    def _export(
        self, page: Page, case_id: str, information: dict,
        doctor_catalog: DoctorCatalogService,
    ) -> OriCaseCaptureResult:
        self.results_root.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[<>:"/\\|?*]', "_", case_id).strip().rstrip(".")
        prescription_file = self.results_root / f"{stem}_prescription.pdf"
        # Download and parse before catalog enrichment so fallback identification
        # can use the licence belonging to this case's prescriber.
        DashboardPage(page).download_prescription(prescription_file)
        licence_number = CaseDetailsPage.license_from_pdf(prescription_file)
        print("License number extracted from prescription PDF:", licence_number)
        if licence_number:
            information["License No"] = licence_number
        else:
            logger.warning("ORI prescription has no readable licence number for case {}", case_id)
        source = {
            "Patient": information.get("Patient", ""),
            "Doctor": information.get("Doctor", ""),
            "Case ID": case_id,
            "Created": information.get("Created", ""),
        }
        payload = StandardCasePayloadService.build(source)
        payload.get("patientInfo", {}).pop("id", None)
        payload["customerAccount"]["prescriber"]["licenceNo"] = information.get("License No", "")
        doctor_catalog.apply(payload, information.get("Clinic", ""))
        payload["caseNumber"] = case_id
        payload["fullCaseId"] = information.get("Fullcaseid", "")
        payload["status"] = information.get("Status", "")
        payload["clinicInformation"] = {
            "name": information.get("Clinic", "")
        }
        payload["labInformation"] = {"name": information.get("Lab", "")}
        payload["dates"] = {
            "created": information.get("Created", ""),
            "received": information.get("Received", ""),
            "due": information.get("Due", ""),
        }

        json_file = self.results_root / f"{stem}.json"
        json_file.write_text(
            json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        text_file = self.results_root / f"{stem}.txt"
        text_file.write_text(
            json.dumps(information, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        screenshot_file = self.results_root / f"{stem}.png"
        page.screenshot(path=str(screenshot_file), full_page=True)
        self.case_tracker.record_download(case_id, self.case_tracker.doctor_name(payload))
        return OriCaseCaptureResult(
            case_id, json_file, text_file, screenshot_file, prescription_file
        )
