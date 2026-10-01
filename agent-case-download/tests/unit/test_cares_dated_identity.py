from unittest.mock import Mock

import pytest

from pages.cares_connect.case_details_page import CaseDetailsPage
from services.cares_case_capture_service import CaresCaseCaptureService
from services.rpa_case_tracking_service import RpaCaseTrackingService


@pytest.mark.parametrize("value,expected", [
    ("30/05/2024 19:07", "20240530-190700"),
    ("16/05/2024 19:46", "20240516-194600"),
    ("30/05/2024 19:08:12", "20240530-190812"),
    ("30/05/2024", "20240530-000000"),
])
def test_case_id_includes_stable_portal_timestamp(value, expected):
    details = CaseDetailsPage.__new__(CaseDetailsPage)
    details.page = Mock()
    details.page.locator.return_value.first.inner_text.return_value = "IO-240516-1 (2)"
    details.get_detail = Mock(return_value=value)
    assert details.get_case_id() == f"IO-240516-1_{expected}"
    details.get_detail.assert_called_once_with("Date:")


@pytest.mark.parametrize("value", ["", None, "not a date"])
def test_missing_date_cannot_silently_merge_cases(value):
    with pytest.raises(ValueError, match="cannot safely identify"):
        CaseDetailsPage.dated_case_id("IO-240516-1", value)


def test_reused_case_names_have_separate_exports_and_tracking(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    legacy = results / "IO-240516-1.json"
    legacy.write_text('{"reference":"IO-240516-1"}')
    tracker = RpaCaseTrackingService("cares_connect", results, tmp_path / "history.db")
    service = CaresCaseCaptureService.__new__(CaresCaseCaptureService)
    service.reports_root = tmp_path
    service.case_tracker = tracker
    details = Mock()
    ids = [CaseDetailsPage.dated_case_id("IO-240516-1", date) for date in ("30/05/2024 19:07", "16/05/2024 19:46")]
    for case_id in ids:
        assert not tracker.is_downloaded(case_id)
        payload = {"reference": case_id}
        result = service._export_by_case_id(details, case_id, payload, "case details")
        assert result.json_file.name == f"{case_id}.json"
        assert tracker.is_downloaded(case_id)
    assert legacy.read_text() == '{"reference":"IO-240516-1"}'
    assert len(list(results.glob("*.json"))) == 3
