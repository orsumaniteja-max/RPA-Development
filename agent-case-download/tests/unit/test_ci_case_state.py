import json
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

from services.rpa_case_tracking_service import RpaCaseTrackingService
from utilities.ci_case_state import ARTIFACT, CAPTURE_TAG, MANIFEST, pack, restore, select_build


def test_retain_uses_lease_api_with_numeric_run_and_definition():
    from utilities.ci_case_state import AzureBuilds, RETENTION_DAYS
    api = AzureBuilds.__new__(AzureBuilds)
    api.request = Mock()
    api.retain("122", "9", "requester-id")
    api.request.assert_called_once_with("retention/leases", method="POST", body=[{
        "daysValid": RETENTION_DAYS, "definitionId": 9, "runId": 122,
        "ownerId": "User:requester-id", "protectPipeline": False,
    }])


def test_api_error_reports_operation_and_server_message_without_token(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError
    from utilities import ci_case_state as module
    api = module.AzureBuilds.__new__(module.AzureBuilds)
    api.base = "https://example.test/_apis/build/"
    api.token = "test-secret-token"
    api.deadline = module.time.monotonic() + 120
    error = HTTPError(api.base, 400, "Bad Request", {}, BytesIO(
        b'{"message":"Invalid retention request test-secret-token"}'))
    monkeypatch.setattr(module, "urlopen", Mock(side_effect=error))
    with pytest.raises(RuntimeError, match="POST retention/leases.*HTTP 400") as caught:
        api.request("retention/leases", method="POST", body=[])
    assert "Invalid retention request" in str(caught.value)
    assert api.token not in str(caught.value)


def test_history_stops_after_first_batch_with_saved_state():
    api = Mock()
    api.builds.return_value = [{"id": i, "status": "completed"} for i in range(1, 30)]
    api.artifacts.side_effect = lambda build_id: [{"name": ARTIFACT}] if build_id == 28 else []
    assert select_build(api, 30) == 28
    assert {call.args[0] for call in api.artifacts.call_args_list} == set(range(22, 30))


def test_concurrent_lookup_keeps_newest_state_even_if_older_finishes_first():
    from threading import Event
    api = Mock()
    api.builds.return_value = [{"id": 19, "status": "completed"},
                               {"id": 18, "status": "completed"}]
    older_finished = Event()
    def artifacts(build_id):
        if build_id == 18:
            older_finished.set()
        else:
            assert older_finished.wait(2)
        return [{"name": ARTIFACT}]
    api.artifacts.side_effect = artifacts
    assert select_build(api, 20) == 19


def test_history_rejects_repeated_pagination_token(monkeypatch):
    from utilities.ci_case_state import AzureBuilds
    monkeypatch.setenv("SYSTEM_DEFINITIONID", "1")
    api = AzureBuilds.__new__(AzureBuilds)
    api.request = Mock(return_value=({"value": []}, "same-token"))
    with pytest.raises(RuntimeError, match="continuation token"):
        api.builds()
    assert api.request.call_count == 2


def test_history_deadline_does_not_make_another_network_request(monkeypatch):
    from utilities import ci_case_state as module
    api = module.AzureBuilds.__new__(module.AzureBuilds)
    api.deadline = 10
    monkeypatch.setattr(module.time, "monotonic", lambda: 11)
    network = Mock()
    monkeypatch.setattr(module, "urlopen", network)
    with pytest.raises(RuntimeError, match="120 seconds"):
        api.request("builds")
    network.assert_not_called()


def test_round_trip_skips_local_case_in_fresh_ci_checkout(tmp_path):
    local, ci = tmp_path / "local", tmp_path / "ci"
    results = local / "reports" / "oriportal" / "results"
    results.mkdir(parents=True)
    payload = {"customerAccount": {"prescriber": {"name": "Doctor"}}}
    (results / "RX1.json").write_text(json.dumps(payload))
    (results / "RX1_prescription.pdf").write_bytes(b"PDF evidence")
    tracker = RpaCaseTrackingService("ori_portal", results, local / "data" / "rpa_case_tracking.db")
    tracker.record_download("RX1", "Doctor")
    (local / ".env").write_text("secret")
    archive = tmp_path / "state.zip"
    pack(local, archive)
    restore(archive, ci)
    restored = RpaCaseTrackingService("ori_portal", ci / "reports" / "oriportal" / "results",
                                      ci / "data" / "rpa_case_tracking.db")
    assert restored.is_downloaded("RX1")
    assert not restored.is_downloaded("RX2")
    assert (restored.results_root / "RX1_prescription.pdf").read_bytes() == b"PDF evidence"
    assert not (ci / ".env").exists()
    # Future snapshots remain cumulative, including when a later capture fails.
    (restored.results_root / "RX2.json").write_text("{}")
    pack(ci, archive)
    restore(archive, tmp_path / "next")
    assert (tmp_path / "next/reports/oriportal/results/RX1.json").exists()
    assert (tmp_path / "next/reports/oriportal/results/RX2.json").exists()


def test_metadata_seed_preserves_skip_information_without_large_evidence(tmp_path):
    results = tmp_path / "local/reports/ddx/results"
    results.mkdir(parents=True)
    (results / "123.json").write_text("{}")
    (results / "123.png").write_bytes(b"screenshot")
    archive = tmp_path / "seed.zip"
    pack(tmp_path / "local", archive, metadata_only=True)
    restore(archive, tmp_path / "ci")
    tracker = RpaCaseTrackingService("ddx", tmp_path / "ci/reports/ddx/results", tmp_path / "ci/data/history.db")
    assert tracker.is_downloaded("123")
    assert not (tracker.results_root / "123.png").exists()


def test_pack_names_an_unreadable_case_state_file(monkeypatch, tmp_path):
    from utilities import ci_case_state as module
    results = tmp_path / "reports/labtrac"
    results.mkdir(parents=True)
    (results / "upload_history.csv").write_text("history")
    original_write = module.ZipFile.write

    def deny_history(self, filename, arcname=None, *args, **kwargs):
        if str(filename).endswith("upload_history.csv"):
            raise PermissionError("denied")
        return original_write(self, filename, arcname, *args, **kwargs)

    monkeypatch.setattr(module.ZipFile, "write", deny_history)
    with pytest.raises(RuntimeError, match="Cannot read case-state file reports/labtrac/upload_history.csv"):
        pack(tmp_path, tmp_path / "state.zip")


@pytest.mark.parametrize("bad_name", ["../escape", "/absolute", "reports/ddx/results/../../escape", "data/other.db", "reports\\escape"])
def test_restore_rejects_unexpected_paths_before_writing(tmp_path, bad_name):
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as output:
        output.writestr(MANIFEST, '{"version": 1}')
        output.writestr("reports/ddx/results/valid.json", "{}")
        output.writestr(bad_name, "bad")
    with pytest.raises(ValueError, match="Unexpected path"):
        restore(archive, tmp_path / "ci")
    assert not (tmp_path / "ci").exists()


def test_select_includes_failed_runs_and_ignores_current_run():
    api = Mock()
    api.builds.return_value = [
        {"id": 20, "status": "inProgress"},
        {"id": 19, "status": "completed", "result": "failed"},
        {"id": 18, "status": "completed", "result": "succeeded"},
    ]
    api.artifacts.return_value = [{"name": ARTIFACT}]
    assert select_build(api, 20) == 19


def test_select_skips_failure_before_capture_but_not_lost_capture_state():
    api = Mock()
    api.builds.return_value = [{"id": 19, "status": "completed"}, {"id": 18, "status": "completed"}]
    api.artifacts.side_effect = lambda build_id: [] if build_id == 19 else [{"name": ARTIFACT}]
    assert select_build(api, 20) == 18
    api.builds.return_value[0]["tags"] = [CAPTURE_TAG]
    with pytest.raises(RuntimeError, match="saved no state"):
        select_build(api, 20)
    assert select_build(api, 20, allow_missing_capture_state=True) is None


def test_fresh_state_override_does_not_allow_an_overlapping_run():
    api = Mock()
    api.builds.return_value = [{"id": 19, "status": "inProgress", "tags": [CAPTURE_TAG]}]
    with pytest.raises(RuntimeError, match="earlier run"):
        select_build(api, 20, allow_missing_capture_state=True)
    api.artifacts.assert_not_called()


def test_overlapping_run_cannot_start_capture():
    api = Mock()
    api.builds.return_value = [{"id": 19, "status": "inProgress"}]
    with pytest.raises(RuntimeError, match="earlier run"):
        select_build(api, 20)
    api.artifacts.assert_not_called()


def test_no_history_is_explicit():
    api = Mock()
    api.builds.return_value = []
    assert select_build(api, 20) is None


def test_retry_requires_new_run_to_avoid_stale_state_and_artifact_collision():
    api = Mock()
    with pytest.raises(RuntimeError, match="Queue a new pipeline run"):
        select_build(api, 20, job_attempt=2)
    api.builds.assert_not_called()


def test_ori_skips_before_reading_details_or_downloading(monkeypatch, tmp_path):
    from services import ori_case_capture_service as module
    service = module.OriCaseCaptureService.__new__(module.OriCaseCaptureService)
    service.results_root = tmp_path / "results"
    service.case_tracker = Mock()
    service.case_tracker.is_downloaded.return_value = True
    service._export = Mock()
    details = Mock()
    details.get_detail.return_value = "RX1"
    details._clean_case_id.side_effect = lambda value: value
    monkeypatch.setattr(module, "CaseDetailsPage", Mock(return_value=details))
    monkeypatch.setattr(module, "DashboardPage", Mock())
    monkeypatch.setattr(module, "LoginPage", Mock())
    monkeypatch.setattr(module, "DoctorCatalogService", Mock())
    assert service.capture_all_cases(Mock(), "user", "password", max_cases=1) == []
    details.get_case_information.assert_not_called()
    service._export.assert_not_called()


def test_ddx_never_recaptures_known_case_for_missing_contact(monkeypatch, tmp_path):
    from services import ddx_case_capture_service as module
    service = module.DdxCaseCaptureService.__new__(module.DdxCaseCaptureService)
    service.results_root = tmp_path / "results"
    service.case_tracker = Mock()
    service.case_tracker.is_downloaded.return_value = True
    service._needs_contact_retry = Mock(return_value=True)
    service._export = Mock()
    details, dashboard = Mock(), Mock()
    details.get_case_id.return_value = "RX1"
    dashboard.get_record_count.return_value = 1
    monkeypatch.setattr(module, "CaseDetailsPage", Mock(return_value=details))
    monkeypatch.setattr(module, "DashboardPage", Mock(return_value=dashboard))
    monkeypatch.setattr(module, "LoginPage", Mock())
    monkeypatch.setattr(module, "DoctorCatalogService", Mock())
    assert service.capture_all_cases(Mock(), "user", "password", max_cases=1) == []
    details.get_all_displayed_details.assert_not_called()
    service._export.assert_not_called()
