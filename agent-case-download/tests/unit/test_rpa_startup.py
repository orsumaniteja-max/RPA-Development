import sys
from types import SimpleNamespace

import run_rpa
import json
from unittest.mock import Mock
from services.doctor_catalog_service import DoctorCatalogService


def test_saved_pending_case_uploads_without_capture(tmp_path, monkeypatch):
    from services.labtrac_upload_service import LabtracUploadService
    results = tmp_path / "reports/carestream/results"
    results.mkdir(parents=True)
    for name in ("already", "pending1", "pending2"):
        (results / f"{name}.json").write_text(json.dumps({
            "reference": name, "patientInfo": {"name": "Source Patient"}, "description": "Source prescription",
            "customerAccount": {"prescriber": {"id": "account-1", "name": "Source Doctor"}},
        }))
    client = Mock()
    client.submit_payload.return_value = {"submissionId": "new-submission"}
    uploader = LabtracUploadService(tmp_path, client, Mock(resolve=Mock(return_value="account-1")), sql_tracker=Mock())
    uploader.save("carestream", "already", "uploaded", {"submissionId": "old"})
    monkeypatch.setattr(run_rpa, "LabtracUploadService", lambda: uploader)
    capture = Mock(side_effect=AssertionError("Browser must not start"))
    monkeypatch.setattr(run_rpa, "capture", capture)
    settings = tmp_path / "input.json"
    settings.write_text('{"application":"carestream","records":1,"mode":"capture_and_upload"}')
    assert run_rpa.main(["--input", str(settings)]) == 0
    client.submit_payload.assert_called_once()
    assert client.submit_payload.call_args.args[0]["reference"] == "pending1"
    capture.assert_not_called()


def test_capture_only_fills_upload_shortfall(tmp_path, monkeypatch):
    uploader = Mock()
    uploader.upload.side_effect = [
        [{"status": "uploaded"}], [{"status": "uploaded"}],
    ]
    monkeypatch.setattr(run_rpa, "LabtracUploadService", lambda: uploader)
    capture = Mock()
    monkeypatch.setattr(run_rpa, "capture", capture)
    settings = tmp_path / "input.json"
    settings.write_text('{"application":"carestream","records":2,"mode":"capture_and_upload"}')
    assert run_rpa.main(["--input", str(settings)]) == 0
    capture.assert_called_once_with(("carestream",), limit=1)
    assert [call.args[1] for call in uploader.upload.call_args_list] == [2, 1]


def test_uncertain_upload_does_not_trigger_capture(tmp_path, monkeypatch):
    uploader = Mock()
    uploader.upload.return_value = [{"status": "needs_review"}]
    monkeypatch.setattr(run_rpa, "LabtracUploadService", lambda: uploader)
    capture = Mock()
    monkeypatch.setattr(run_rpa, "capture", capture)
    settings = tmp_path / "input.json"
    settings.write_text('{"application":"carestream","records":1,"mode":"capture_and_upload"}')
    assert run_rpa.main(["--input", str(settings)]) == 1
    capture.assert_not_called()


def test_carestream_new_case_limit_skips_existing(tmp_path, monkeypatch):
    from services import carestream_case_capture_service as module
    service = module.CarestreamCaseCaptureService.__new__(module.CarestreamCaseCaptureService)
    service.results_root = tmp_path / "results"
    service.case_tracker = Mock()
    service.case_tracker.is_downloaded.side_effect = [True, False]
    service._export = Mock(return_value="new-result")
    dashboard = Mock()
    dashboard.get_selected_case_number.side_effect = ["old", "new"]
    dashboard.get_case_numbers.return_value = ["old", "new", "extra"]
    details = Mock()
    details.get_case_id.return_value = "new"
    details.get_case_information.return_value = {}
    monkeypatch.setattr(module, "DashboardPage", Mock(return_value=dashboard))
    monkeypatch.setattr(module, "LoginPage", Mock())
    monkeypatch.setattr(module, "CaseDetailsPage", Mock(return_value=details))
    monkeypatch.setattr(module, "DoctorCatalogService", Mock())
    assert service.capture_all_cases(Mock(), "user", "password", max_new_cases=1) == ["new-result"]
    service._export.assert_called_once()
    dashboard.open_case.assert_called_once_with("new")


def test_shared_catalog_preserves_database_exception(tmp_path, monkeypatch):
    class DatabaseError(Exception):
        pass

    def connect(**kwargs):
        raise DatabaseError(18456, "Login failed")

    monkeypatch.setitem(sys.modules, "pymssql", SimpleNamespace(Error=DatabaseError, connect=connect))
    for key in ("SERVER", "DATABASE", "USERNAME", "PASSWORD"):
        monkeypatch.setenv(f"AZURE_SQL_{key}", "test-value")
    import pytest
    # The shared catalog retains its original exception contract for portal tests.
    with pytest.raises(DatabaseError):
        DoctorCatalogService(tmp_path).load_and_export()


def test_sql_login_guidance_is_only_added_by_runner(monkeypatch, caplog):
    def fail():
        raise RuntimeError(18456, "Login failed")

    monkeypatch.setattr(run_rpa, "main", fail)
    assert run_rpa.cli() == 1
    assert "Azure SQL rejected" in caplog.text
    assert "AZURE_SQL_PASSWORD" in caplog.text


def test_cli_reports_failure_without_traceback(monkeypatch, caplog):
    def fail():
        raise RuntimeError("Configuration needs correction")

    monkeypatch.setattr(run_rpa, "main", fail)
    assert run_rpa.cli() == 1
    assert "RPA stopped: Configuration needs correction" in caplog.text


def test_relative_input_resolves_from_project_root(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "input.json").write_text('{"application":"ddx","mode":"capture_only"}')
    monkeypatch.setattr(run_rpa.ConfigReader, "PROJECT_ROOT", tmp_path)
    monkeypatch.chdir(config)
    calls = []
    monkeypatch.setattr(run_rpa, "capture", lambda apps: calls.append(apps))
    assert run_rpa.main(["--input", "config/input.json"]) == 0
    assert calls == [("ddx",)]


def test_labtrac_check_does_not_capture_or_upload(monkeypatch, capsys):
    calls = []
    class Client:
        def check_authentication(self):
            calls.append("authentication")
    monkeypatch.setattr(run_rpa, "LabtracApiClient", Client)
    monkeypatch.setattr(run_rpa, "capture", lambda apps: (_ for _ in ()).throw(AssertionError()))
    assert run_rpa.main(["--check-labtrac", "--input", "does-not-exist.json"]) == 0
    assert calls == ["authentication"]
    assert "No cases were uploaded" in capsys.readouterr().out


def test_end_to_end_captures_before_database_upload_and_continues_after_failure(tmp_path, monkeypatch):
    from utilities import upload_database_cases
    calls = []
    def do_capture(apps):
        calls.append(('capture', apps))
        if apps == ('cares_connect',):
            raise RuntimeError('portal unavailable')
    monkeypatch.setattr(run_rpa, 'capture', do_capture)
    monkeypatch.setattr(upload_database_cases, 'main', lambda args: calls.append(('upload', args)) or 0)
    settings = tmp_path / 'input.json'
    settings.write_text('{"application":"all","records":"all","mode":"end_to_end"}')
    assert run_rpa.main(['--input', str(settings)]) == 1
    assert len([c for c in calls if c[0] == 'capture']) == 6
    assert calls[-1] == ('upload', ['--apply', '--application', 'all'])


def test_end_to_end_single_application(tmp_path, monkeypatch):
    from utilities import upload_database_cases
    capture = Mock()
    upload = Mock(return_value=0)
    monkeypatch.setattr(run_rpa, 'capture', capture)
    monkeypatch.setattr(upload_database_cases, 'main', upload)
    settings = tmp_path / 'input.json'
    settings.write_text('{"application":"ddx","records":"all","mode":"end_to_end"}')
    assert run_rpa.main(['--input', str(settings)]) == 0
    capture.assert_called_once_with(('ddx',))
    upload.assert_called_once_with(['--apply', '--application', 'ddx'])
