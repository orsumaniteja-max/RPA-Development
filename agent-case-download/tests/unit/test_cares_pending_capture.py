import sys
from types import SimpleNamespace
from unittest.mock import Mock

import services.cares_case_capture_service as capture_module
from services.rpa_case_tracking_service import RpaCaseTrackingService


def test_all_pages_skip_existing_and_recapture_deleted_json(tmp_path, monkeypatch):
    results = tmp_path / "results"
    results.mkdir()
    existing = results / "existing.json"
    existing.write_text("{}")
    deleted = results / "deleted.json"
    deleted.write_text("{}")
    tracker = RpaCaseTrackingService("cares_connect", results, tmp_path / "tracking.db")
    deleted.unlink()

    dashboard = Mock()
    dashboard.get_record_count.side_effect = [2, 1]
    dashboard.has_next_page.side_effect = [True, False]
    details = Mock()
    details.get_case_id.side_effect = ["existing", "deleted", "new"]
    monkeypatch.setattr(capture_module, "DashboardPage", lambda page: dashboard)
    monkeypatch.setattr(capture_module, "CaseDetailsPage", lambda page: details)
    monkeypatch.setattr(capture_module, "LoginPage", lambda page: Mock())
    monkeypatch.setattr(capture_module, "DoctorCatalogService", lambda root: Mock())
    service = capture_module.CaresCaseCaptureService(reports_root=tmp_path, case_tracker=tracker)
    captured = []

    def capture(*args, case_id):
        captured.append(case_id)
        (results / f"{case_id}.json").write_text("{}")
        tracker.record_download(case_id, "")
        return SimpleNamespace(case_id=case_id)

    monkeypatch.setattr(service, "_capture_current_case", capture)
    output = service.capture_all_cases(Mock(), "username", "password", max_cases=sys.maxsize)
    assert captured == ["deleted", "new"]
    dashboard.select_status.assert_not_called()
    assert [result.case_id for result in output] == captured
    assert tracker.is_downloaded("deleted")
    assert tracker.is_downloaded("new")
    assert dashboard.return_to_search_results.call_count == 3
    dashboard.open_next_page.assert_called_once()
