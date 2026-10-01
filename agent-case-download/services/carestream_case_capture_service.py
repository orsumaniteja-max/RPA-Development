"""Capture every Carestream case currently available in the case list."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Page

from pages.carestream.case_details_page import CaseDetailsPage
from pages.carestream.dashboard_page import DashboardPage
from pages.carestream.login_page import LoginPage
from services.standard_case_payload_service import StandardCasePayloadService
from services.doctor_catalog_service import DoctorCatalogService
from services.rpa_case_tracking_service import RpaCaseTrackingService


@dataclass(frozen=True)
class CarestreamCaseCaptureResult:
    case_id: str
    json_file: Path
    text_file: Path
    screenshot_file: Path


class CarestreamCaseCaptureService:
    def __init__(self, reports_root: Path) -> None:
        self.results_root = Path(reports_root) / "results"
        self.case_tracker = RpaCaseTrackingService("carestream", self.results_root)

    def capture_all_cases(
        self, page: Page, username: str, password: str, max_cases: int | None = None,
        max_new_cases: int | None = None,
    ) -> list[CarestreamCaseCaptureResult]:
        dashboard = DashboardPage(page)
        login = LoginPage(page)
        details_page = CaseDetailsPage(page)
        doctor_catalog = DoctorCatalogService(self.results_root.parent)
        doctor_catalog.load_and_export()
        dashboard.click_on_access_the_service()
        login.login(username, password)

        results = {}
        processed_ids: set[str] = set()
        while max_cases is None or len(processed_ids) < max_cases:
            selected_case_id = dashboard.get_selected_case_number()
            if selected_case_id not in processed_ids:
                processed_ids.add(selected_case_id)
                if self.case_tracker.is_downloaded(selected_case_id):
                    pass
                else:
                    case_id = details_page.get_case_id()
                    if not case_id:
                        raise ValueError("Carestream returned an empty selected case ID")
                    information = details_page.get_case_information()
                    information["Case ID"] = case_id
                    results[case_id] = self._export(
                        page, case_id, information, doctor_catalog
                    )
                    if max_new_cases is not None and len(results) >= max_new_cases:
                        return list(results.values())

            if max_cases is not None and len(processed_ids) >= max_cases:
                break

            # Carestream virtualizes and refreshes its sidebar while cases are
            # selected. Re-read it after every export instead of iterating a
            # stale snapshot whose later rows may have left the DOM.
            next_case_id = next(
                (
                    case_number
                    for case_number in dashboard.get_case_numbers()
                    if case_number not in processed_ids
                ),
                None,
            )
            if next_case_id is not None:
                dashboard.open_case(next_case_id)
                continue

            if (max_cases is not None and len(processed_ids) >= max_cases) or not dashboard.has_next_page():
                break
            dashboard.open_next_page()
        return list(results.values())

    def _export(
        self, page: Page, case_id: str, information: dict,
        doctor_catalog: DoctorCatalogService,
    ) -> CarestreamCaseCaptureResult:
        self.results_root.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[<>:"/\\|?*]', "_", case_id).strip().rstrip(".")
        payload = StandardCasePayloadService.build(information)
        payload.get("patientInfo", {}).pop("id", None)
        payload["doctorInformation"] = {
            "address": information.get("Doctor Address", "")
        }
        payload["summary"] = information.get(
            "Summary", {"Comment": "", "Due Date": ""}
        )
        doctor_catalog.apply(
            payload,
            match_name=self._doctor_name_hint(payload["summary"].get("Comment", "")),
        )
        json_file = self.results_root / f"{stem}.json"
        json_file.write_text(
            json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8"
        )
        text_file = self.results_root / f"{stem}.txt"
        summary = information.get("Summary", {})
        text_file.write_text(
            information["Details"]
            + f"\n\nSummary\nComment: {summary.get('Comment', '')}"
            + f"\nDue Date: {summary.get('Due Date', '')}\n",
            encoding="utf-8",
        )
        screenshot_file = self.results_root / f"{stem}.png"
        page.screenshot(path=str(screenshot_file), full_page=True)
        self.case_tracker.record_download(case_id, self.case_tracker.doctor_name(payload))
        return CarestreamCaseCaptureResult(case_id, json_file, text_file, screenshot_file)

    @staticmethod
    def _doctor_name_hint(comment: str) -> str:
        """Extract a more complete trailing doctor name from a case comment."""
        match = re.search(
            r"\bDr\.?\s+([A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){1,4})\s*$",
            comment or "",
            re.IGNORECASE,
        )
        return f"Dr. {match.group(1).strip()}" if match else ""
