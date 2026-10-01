"""Capture all currently listed IO Scanner cases and linked information."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page

from pages.io_scanner.case_details_page import CaseDetailsPage
from pages.io_scanner.dashboard_page import DashboardPage
from pages.io_scanner.login_page import LoginPage
from services.standard_case_payload_service import StandardCasePayloadService
from services.doctor_catalog_service import DoctorCatalogService
from services.rpa_case_tracking_service import RpaCaseTrackingService


@dataclass(frozen=True)
class IoScannerCaseCaptureResult:
    case_id: str
    json_file: Path
    text_file: Path
    screenshot_file: Path


class IoScannerCaseCaptureService:
    def __init__(self, reports_root: Path) -> None:
        self.results_root = Path(reports_root) / "results"
        self.case_tracker = RpaCaseTrackingService("io_scanner", self.results_root)

    def capture_all_cases(
        self, page: Page, username: str, password: str, max_cases: int | None = None,
        max_new_cases: int | None = None,
    ) -> list[IoScannerCaseCaptureResult]:
        login = LoginPage(page)
        dashboard = DashboardPage(page)
        details_page = CaseDetailsPage(page)
        doctor_catalog = DoctorCatalogService(self.results_root.parent)
        doctor_catalog.load_and_export()
        login.login(username, password)

        results = {}
        examined = 0
        while max_cases is None or examined < max_cases:
            case_numbers = dashboard.get_case_numbers()
            for index, listed_case_id in enumerate(case_numbers[:None if max_cases is None else max_cases - examined]):
                examined += 1
                if self.case_tracker.is_downloaded(listed_case_id):
                    continue
                dashboard.open_case(listed_case_id)
                information = details_page.get_case_information()
                case_id = information.get("Order Number", "").strip()
                if not case_id:
                    raise ValueError(
                        f"IO Scanner record {index + 1} has no order number"
                    )
                results[case_id] = self._export(
                    page, case_id, information, doctor_catalog
                )
                if max_new_cases is not None and len(results) >= max_new_cases:
                    return list(results.values())
                dashboard.return_to_case_list()
            if (max_cases is not None and examined >= max_cases) or not dashboard.has_next_page():
                break
            dashboard.open_next_page()
        return list(results.values())

    def _export(
        self, page: Page, case_id: str, information: dict,
        doctor_catalog: DoctorCatalogService,
    ) -> IoScannerCaseCaptureResult:
        self.results_root.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[<>:"/\\|?*]', "_", case_id).strip().rstrip(".")
        doctor_information = information.get("Doctor Information", {})
        organization_information = information.get("Organization Details", {})
        doctor_email = doctor_information.get("Email", "")
        source = {
            "Patient": information.get("Patient Name", ""),
            "Doctor": organization_information.get("Contact Person") or information.get("Doctor", ""),
            "Doctor Email": doctor_email,
            "Order Number": case_id,
            "Upload Time": information.get("Upload Time", ""),
            "Case Type": information.get("Case Type", ""),
            "Remark": information.get("Remark", ""),
        }
        payload = StandardCasePayloadService.build(source)
        payload.get("patientInfo", {}).pop("id", None)
        doctor_catalog.apply(
            payload, information.get("Organization Information", "")
        )
        # IO Scanner order numbers are <account ID>_<order ID>. The prefix
        # identifies the source account; the full reference identifies the case.
        account_match = re.fullmatch(r"(\d+)_\d+", case_id.strip())
        if account_match:
            source_account_id = account_match.group(1)
            payload["sourceAccountId"] = source_account_id
        payload["organizationInformation"] = organization_information
        payload["doctorInformation"] = doctor_information
        payload["labInformation"] = information.get("Lab Information", {})

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
        return IoScannerCaseCaptureResult(case_id, json_file, text_file, screenshot_file)
