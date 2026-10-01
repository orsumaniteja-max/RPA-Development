from unittest.mock import Mock

import pytest

from services import ddx_case_capture_service as module


@pytest.mark.parametrize("limit, expected, next_clicks", [(None, 53, 2), (51, 51, 1)])
def test_capture_crosses_pages_and_respects_explicit_limit(monkeypatch, limit, expected, next_clicks):
    service = module.DdxCaseCaptureService.__new__(module.DdxCaseCaptureService)
    service.results_root = Mock()
    service.case_tracker = Mock()
    # A full first page of previously downloaded cases must not stop pagination.
    service.case_tracker.is_downloaded.side_effect = [True] * 50 + [False] * 3
    service._export = Mock(side_effect=lambda page, case_id, details, catalog: case_id)
    dashboard = Mock()
    dashboard.get_record_count.side_effect = [50, 2, 1]
    dashboard.has_next_page.side_effect = [True, True, False]
    details = Mock()
    details.get_case_id.side_effect = [f"RX-{i}" for i in range(53)]
    monkeypatch.setattr(module, "DashboardPage", Mock(return_value=dashboard))
    monkeypatch.setattr(module, "CaseDetailsPage", Mock(return_value=details))
    monkeypatch.setattr(module, "LoginPage", Mock())
    monkeypatch.setattr(module, "DoctorCatalogService", Mock())

    kwargs = {} if limit is None else {"max_cases": limit}
    results = service.capture_all_cases(Mock(), "user", "password", **kwargs)

    assert results == [f"RX-{i}" for i in range(50, expected)]
    assert dashboard.open_record.call_count == expected
    assert dashboard.return_to_case_results.call_count == expected
    assert dashboard.open_next_page.call_count == next_clicks
