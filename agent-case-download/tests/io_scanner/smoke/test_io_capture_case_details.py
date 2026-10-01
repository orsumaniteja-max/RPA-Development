from pages.io_scanner.case_details_page import CaseDetailsPage
import allure
import pytest
from playwright.sync_api import Page

from services.io_scanner_case_capture_service import IoScannerCaseCaptureService
from services.background_result_validation_service import validate_application_results

@allure.epic("IO Scanner RPA")
@allure.feature("Case export")
@allure.story("Capture all available case details")
@pytest.mark.smoke
def test_io_capture_case_details(
    page: Page, portal_credentials, application_report_root
) -> None:
    results = IoScannerCaseCaptureService(
        reports_root=application_report_root
    ).capture_all_cases(
        page,
        portal_credentials["username"],
        portal_credentials["password"],
    )

    # No new results is valid when SQL says every listed prescription is complete.
    for result in results:
        assert result.json_file.stem == result.case_id
        assert result.json_file.is_file()
        assert result.text_file.is_file()
        assert result.screenshot_file.is_file()
    validate_application_results(application_report_root)
