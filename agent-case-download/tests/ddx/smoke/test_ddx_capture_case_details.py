"""Smoke test for exporting every displayed DDX To Arrive case."""

from services.ddx_case_capture_service import DdxCaseCaptureService
from services.background_result_validation_service import validate_application_results
import pytest


@pytest.mark.smoke
def test_ddx_capture_case_details(page, portal_credentials, application_report_root):
    results = DdxCaseCaptureService(application_report_root).capture_all_cases(
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
