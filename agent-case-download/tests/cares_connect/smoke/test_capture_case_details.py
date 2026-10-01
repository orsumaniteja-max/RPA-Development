"""Smoke test for the reusable CARES case-capture workflow."""

import allure
import pytest
from playwright.sync_api import Page

from services.cares_case_capture_service import CaresCaseCaptureService


@allure.epic("CARES Connect RPA")
@allure.feature("Case export")
@allure.story("Capture case details from advanced search")
@pytest.mark.smoke
def test_capture_case_details(
    page: Page, portal_credentials, application_report_root
) -> None:
    """Capture all new or missing cases across statuses and result pages."""
    results = CaresCaseCaptureService(reports_root=application_report_root).capture_all_cases(
        page,
        portal_credentials["username"],
        portal_credentials["password"],
    )

    for result in results:
        assert result.json_file.is_file()
        assert result.text_file.is_file()
        assert result.cares_text_file.is_file()
        assert result.screenshot_file.is_file()
        assert result.json_file.parent == application_report_root / "results"
        assert result.json_file.name == f"{result.case_id}.json"
