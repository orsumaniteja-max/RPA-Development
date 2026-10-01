import json
import csv
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.labtrac_upload_service import (
    APPLICATIONS, LabtracUploadService, record_limit, select_applications,
)
from utilities.config_reader import ConfigReader


@pytest.fixture(autouse=True)
def offline_upload_dependencies(monkeypatch):
    from services.labtrac_account_lookup_service import LabtracAccountLookupService
    from services.rpa_sql_tracking_service import RpaSqlTrackingService
    monkeypatch.setattr(LabtracAccountLookupService, 'resolve', lambda self, name: 'matched-account')
    monkeypatch.setattr(RpaSqlTrackingService, 'record_submission', lambda *args: None)


class Client:
    def __init__(self, fail=False):
        self.payloads = []
        self.fail = fail

    def submit_payload(self, payload):
        self.payloads.append(payload)
        if self.fail:
            raise TimeoutError("Response lost after server accepted request")
        return {"submissionId": str(len(self.payloads))}


def write_case(root, application, case_id, doctor_id="matched-doctor"):
    folder = ConfigReader.get_config(application)["report_folder"]
    path = root / "reports" / folder / "results" / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"customerAccount": {"id": "matched-account",
                           "prescriber": {"id": doctor_id, "name": "Source Doctor"}},
                           "patientInfo": {"name": "Source Patient"}, "reference": case_id,
                           "description": "Source prescription"}))
    return path


def test_one_then_next_pending_across_restarts(tmp_path):
    for case_id in ("a", "b", "c"):
        write_case(tmp_path, "cares_connect", case_id)
    write_case(tmp_path, "ddx", "a")
    client = Client()
    first = LabtracUploadService(tmp_path, client).upload(("cares_connect",), 1)
    second = LabtracUploadService(tmp_path, client).upload(("cares_connect",), 1)
    assert [first[0]["case"], second[0]["case"]] == ["a", "b"]
    assert len(client.payloads) == 2
    assert client.payloads[0]["customerAccount"]["prescriber"]["id"] == "matched-account"
    assert client.payloads[0]["customerAccount"]["id"] == "matched-account"


def test_all_six_applications_and_duplicate_skip(tmp_path):
    for application in APPLICATIONS:
        write_case(tmp_path, application, "same-case-id")
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    assert len(service.upload(select_applications("all"))) == 6
    assert service.upload(APPLICATIONS) == []
    assert len(client.payloads) == 6
    with service.sheet.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6
    assert {row["Application"] for row in rows} == set(APPLICATIONS)


def test_verified_doctor_account_id_replaces_saved_fallback_before_submission(tmp_path):
    write_case(tmp_path, "cares_connect", "case", doctor_id="fallback-name")
    client = Client()
    lookup = type("Lookup", (), {"resolve": lambda self, name: "ACCOUNT-42"})()
    outcome = LabtracUploadService(tmp_path, client, lookup).upload(("cares_connect",))
    assert outcome[0]["status"] == "uploaded"
    payload = client.payloads[0]
    assert payload["customerAccount"]["id"] == "ACCOUNT-42"
    assert payload["customerAccount"]["prescriber"]["id"] == "ACCOUNT-42"


def test_missing_doctor_account_is_not_sent_to_labtrac(tmp_path):
    write_case(tmp_path, "cares_connect", "case")
    client = Client()
    lookup = type("Lookup", (), {"resolve": lambda self, name: (_ for _ in ()).throw(
        LookupError("Found no unique AccountId records"))})()
    outcome = LabtracUploadService(tmp_path, client, lookup).upload(("cares_connect",))
    assert outcome[0]["status"] == "needs_review"
    assert "Found no unique AccountId records" in outcome[0]["error"]
    assert client.payloads == []


def test_ambiguous_failure_never_automatically_recreates(tmp_path):
    write_case(tmp_path, "ddx", "a")
    client = Client(fail=True)
    service = LabtracUploadService(tmp_path, client)
    first = service.upload(("ddx",))[0]
    assert first["status"] == "needs_review"
    assert "TimeoutError" in first["error"]
    assert service.upload(("ddx",))[0]["status"] == "needs_review"
    assert len(client.payloads) == 1
    with service.sheet.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.DictReader(stream))[0]["Status"] == "needs_review"


def test_sheet_preserves_upload_metadata_after_source_changes(tmp_path):
    path = write_case(tmp_path, "ori_portal", "case-1")
    payload = json.loads(path.read_text())
    payload["patientInfo"]["name"] = "Jane Smith"
    payload["customerAccount"]["prescriber"]["name"] = "Doctor One"
    path.write_text(json.dumps(payload))
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    service.upload(("ori_portal",))
    assert json.loads(path.read_text())["patientInfo"]["name"] == "Jane Smith"
    payload["patientInfo"]["name"] = "Changed later"
    path.write_text(json.dumps(payload))
    restarted = LabtracUploadService(tmp_path, client)
    assert restarted.upload(("ori_portal",)) == []
    with restarted.sheet.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0]["Patient"] == "Jane Smith"
    assert rows[0]["SubmittedPatient"] == "Jane Smith (RPA)"
    assert rows[0]["Prescriber"] == "Doctor One"
    assert rows[0]["SubmissionId"]
    assert rows[0]["UploadedAtUTC"]


def test_locked_sheet_does_not_change_uploaded_status(tmp_path, monkeypatch):
    from services import upload_history_service as module
    write_case(tmp_path, "ddx", "case-1")
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    def locked(*args):
        raise PermissionError("Sheet open in Excel")
    monkeypatch.setattr(module.os, "replace", locked)
    assert service.upload(("ddx",))[0]["status"] == "needs_review"
    assert len(client.payloads) == 0


def test_missing_doctor_still_consumes_upload_count(tmp_path):
    write_case(tmp_path, "ddx", "a", doctor_id="")
    write_case(tmp_path, "ddx", "b")
    client = Client()
    outcomes = LabtracUploadService(tmp_path, client).upload(("ddx",), 1)
    assert [item["status"] for item in outcomes] == ["uploaded"]
    assert len(client.payloads) == 1


def test_legacy_receipt_is_adopted_and_not_uploaded(tmp_path):
    path = write_case(tmp_path, "cares_connect", "a")
    path.with_name("a_labtrac.json").write_text('{"submissionId": "existing"}')
    client = Client()
    assert LabtracUploadService(tmp_path, client).upload(("cares_connect",)) == []
    assert client.payloads == []


def test_concurrent_runners_claim_only_once(tmp_path):
    write_case(tmp_path, "ddx", "a")
    client = Client()
    services = [LabtracUploadService(tmp_path, client) for _ in range(2)]
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(lambda service: service.upload(("ddx",)), services))
    assert len(client.payloads) == 1


def test_interrupted_claim_is_not_retried(tmp_path):
    write_case(tmp_path, "ddx", "a")
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    service.save("ddx", "a", "in_progress", {})
    assert service.upload(("ddx",))[0]["status"] == "needs_review"
    assert client.payloads == []


def test_malformed_receipt_requires_review(tmp_path):
    path = write_case(tmp_path, "cares_connect", "a")
    path.with_name("a_labtrac.json").write_text("{")
    client = Client()
    assert LabtracUploadService(tmp_path, client).upload(("cares_connect",))[0]["status"] == "needs_review"
    assert client.payloads == []


def test_numeric_limit_is_total_across_applications(tmp_path):
    for application in APPLICATIONS:
        write_case(tmp_path, application, "a")
    client = Client()
    assert len(LabtracUploadService(tmp_path, client).upload(APPLICATIONS, 2)) == 2
    assert len(client.payloads) == 2


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "bad"])
def test_invalid_count(value):
    with pytest.raises(ValueError):
        record_limit(value)


def test_user_friendly_inputs():
    assert select_applications("CARES Connect") == ("cares_connect",)
    assert record_limit("one record") == 1
    assert record_limit("all") is None
    with pytest.raises(ValueError):
        select_applications("unknown")


def test_runner_uploads_pending_before_capture_with_input_file(tmp_path, monkeypatch):
    import run_rpa

    settings = tmp_path / "input.json"
    settings.write_text('{"application":"all","records":"all","mode":"capture_and_upload"}')
    calls = []
    monkeypatch.setattr(run_rpa, "capture", lambda apps, limit=None: calls.append(("capture", apps, limit)))

    class Queue:
        def upload(self, apps, limit):
            calls.append(("upload", apps, limit))
            return []

    monkeypatch.setattr(run_rpa, "LabtracUploadService", Queue)
    assert run_rpa.main(["--input", str(settings)]) == 0
    assert calls == [("upload", APPLICATIONS, None), ("capture", APPLICATIONS, None),
                     ("upload", APPLICATIONS, None)]


def test_runner_upload_only_skips_portal_capture(tmp_path, monkeypatch):
    import run_rpa

    settings = tmp_path / "input.json"
    settings.write_text('{"application":"all","records":"all"}')
    calls = []
    monkeypatch.setattr(run_rpa, "capture", lambda apps: pytest.fail("Capture must not run"))

    class Queue:
        def upload(self, apps, limit):
            calls.append((apps, limit))
            return []

    monkeypatch.setattr(run_rpa, "LabtracUploadService", Queue)
    assert run_rpa.main(["--input", str(settings), "--mode", "upload_only",
                         "--application", "cares connect", "--records", "1"]) == 0
    assert calls == [(("cares_connect",), 1)]


def test_all_capture_service_bindings_exist():
    import importlib
    from run_rpa import CAPTURE_SERVICES

    assert set(CAPTURE_SERVICES) == set(APPLICATIONS)
    for module, name in CAPTURE_SERVICES.values():
        service = getattr(importlib.import_module(f"services.{module}_case_capture_service"), name)
        assert callable(service.capture_all_cases)


def test_csv_history_migrates_old_database_once(tmp_path):
    import sqlite3
    database = tmp_path / "data" / "labtrac_uploads.db"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE uploads(application, case_id, status, response, updated_at)")
        connection.execute("INSERT INTO uploads VALUES (?, ?, ?, ?, ?)",
                           ("ddx", "a", "uploaded", '{"submissionId":"old"}', "2026-09-16"))
    connection.close()
    write_case(tmp_path, "ddx", "a")
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    assert service.upload(("ddx",)) == []
    database.unlink()
    assert LabtracUploadService(tmp_path, client).upload(("ddx",)) == []
    assert not database.exists()
    assert not client.payloads


def test_deleted_history_is_not_silently_reset(tmp_path):
    service = LabtracUploadService(tmp_path, Client())
    service.sheet.unlink()
    restarted = LabtracUploadService(tmp_path, Client())
    assert "history CSV is missing" in restarted.upload(("ddx",))[0]["error"]


def test_new_upload_tracking_does_not_create_database(tmp_path):
    write_case(tmp_path, "ddx", "a")
    service = LabtracUploadService(tmp_path, Client())
    assert service.upload(("ddx",))[0]["status"] == "uploaded"
    assert not (tmp_path / "data" / "labtrac_uploads.db").exists()


def test_old_csv_backfills_source_details_without_inventing_submission(tmp_path):
    from services.upload_history_service import UploadHistoryService
    path = write_case(tmp_path, "cares_connect", "case-1")
    payload = json.loads(path.read_text())
    payload["patientInfo"]["name"] = "Patient One"
    payload["rxItems"] = [{"name": "Crown", "qty": 1}]
    path.write_text(json.dumps(payload))
    sheet = tmp_path / "reports" / "labtrac" / "upload_history.csv"
    sheet.parent.mkdir()
    with sheet.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=UploadHistoryService.LEGACY_FIELDS)
        writer.writeheader()
        writer.writerow({"Application": "cares_connect", "CaseId": "case-1",
                         "Status": "needs_review", "UpdatedAtUTC": "2026-09-16", "Response": "{}"})
    service = LabtracUploadService(tmp_path, Client())
    with sheet.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["Patient"] == "Patient One"
    assert row["Reference"] == "case-1"
    assert json.loads(row["SourcePayload"])["rxItems"] == payload["rxItems"]
    assert row["Status"] == "needs_review"
    assert row["UpdatedAtUTC"] == "2026-09-16"
    assert row["SubmittedPatient"] == row["SubmissionId"] == row["UploadedAtUTC"] == ""
    assert "Recovered" in row["MetadataSource"]
    assert service.upload(("cares_connect",))[0]["status"] == "needs_review"


def test_failed_upload_keeps_case_details_and_error(tmp_path):
    path = write_case(tmp_path, "ddx", "case-1")
    service = LabtracUploadService(tmp_path, Client(fail=True))
    service.upload(("ddx",))
    with service.sheet.open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["SourceFile"] == str(path)
    assert json.loads(row["SourcePayload"])["customerAccount"]
    assert "TimeoutError" in row["Error"]
    assert row["Status"] == "needs_review"


@pytest.mark.parametrize('status,expected', [('submitted', 'uploaded'), ('pending', 'needs_review')])
def test_timestamp_csv_compatibility_preserves_saved_records(tmp_path, status, expected):
    from services.upload_history_service import UploadHistoryService
    write_case(tmp_path, 'ddx', 'a')
    sheet = tmp_path / 'reports/labtrac/upload_history.csv'
    sheet.parent.mkdir(parents=True)
    row = dict.fromkeys(UploadHistoryService.FIELDS, '')
    row.update(Application='ddx', CaseId='a', Status=status, SourcePayload='{}',
               SubmissionId='existing-id', Response='{}',
               DownloadedAtUTC='2026-09-20T12:00:00Z',
               UploadAttemptedAtUTC='2026-09-21T12:00:00Z',
               UploadedAtUTC='2026-09-21T12:00:01Z' if status == 'submitted' else '')
    with sheet.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=UploadHistoryService.FIELDS)
        writer.writeheader()
        writer.writerow(row)
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    assert service.history.status('ddx', 'a') == expected
    service.upload(('ddx',))
    assert client.payloads == []
    if status == 'submitted':
        service.save('ddx', 'a', 'needs_review', {'error': 'must not overwrite success'})
    with sheet.open(encoding='utf-8-sig', newline='') as stream:
        assert next(csv.DictReader(stream)) == row


def test_pre_timestamp_csv_still_loads(tmp_path):
    from services.upload_history_service import UploadHistoryService
    sheet = tmp_path / 'reports/labtrac/upload_history.csv'
    sheet.parent.mkdir(parents=True)
    with sheet.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=UploadHistoryService.PRE_TIMESTAMP_FIELDS)
        writer.writeheader()
        writer.writerow(dict(Application='ddx', CaseId='a', Status='uploaded', SourcePayload='{}'))
    assert UploadHistoryService(tmp_path).status('ddx', 'a') == 'uploaded'


@pytest.mark.parametrize('field', ['reference', 'patientInfo', 'customerAccount', 'description'])
def test_incomplete_case_skipped_next_complete_case_submitted(tmp_path, field):
    path = write_case(tmp_path, 'ddx', 'a')
    payload = json.loads(path.read_text())
    payload.pop(field)
    path.write_text(json.dumps(payload))
    write_case(tmp_path, 'ddx', 'b')
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    outcomes = service.upload(('ddx',), 1)
    assert [r['status'] for r in outcomes] == ['needs_review', 'uploaded']
    assert service.history.status('ddx', 'a') is None
    assert len(client.payloads) == 1


def test_lookup_exception_does_not_stop_next_case(tmp_path):
    from unittest.mock import Mock
    for case in ('a', 'b'):
        write_case(tmp_path, 'ddx', case)
    lookup = Mock()
    lookup.resolve.side_effect = [RuntimeError('database unavailable'), 'verified']
    client = Client()
    service = LabtracUploadService(tmp_path, client, lookup)
    assert [r['status'] for r in service.upload(('ddx',))] == ['needs_review', 'uploaded']
    assert len(client.payloads) == 1


def test_sql_failure_retries_tracking_without_resubmission(tmp_path):
    from unittest.mock import Mock
    write_case(tmp_path, 'ddx', 'a')
    client = Client()
    tracker = Mock()
    tracker.record_submission.side_effect = RuntimeError('SQL offline')
    service = LabtracUploadService(tmp_path, client, sql_tracker=tracker)
    result = service.upload(('ddx',))[0]
    assert result['status'] == 'uploaded'
    assert 'SQL offline' in result['sqlTrackingError']
    timestamp = tracker.record_submission.call_args.args[2]
    tracker.record_submission.side_effect = None
    restarted = LabtracUploadService(tmp_path, client, sql_tracker=tracker)
    assert restarted.upload(('ddx',)) == []
    tracker.record_submission.assert_called_with('ddx', 'a', timestamp)
    assert len(client.payloads) == 1
    assert restarted.history.submission_tracking('ddx', 'a')['sqlTrackingPending'] is False


def test_failure_to_save_failed_attempt_does_not_crash(tmp_path, monkeypatch):
    write_case(tmp_path, 'ddx', 'a')
    client = Client(fail=True)
    service = LabtracUploadService(tmp_path, client)
    monkeypatch.setattr(service, 'save', lambda *args: (_ for _ in ()).throw(PermissionError('locked')))
    result = service.upload(('ddx',))[0]
    assert result['status'] == 'needs_review'
    assert result['historyError'] == 'locked'
    assert service.history.status('ddx', 'a') == 'in_progress'
    service.upload(('ddx',))
    assert len(client.payloads) == 1


def test_sql_never_marked_submitted_after_api_failure(tmp_path):
    from unittest.mock import Mock
    write_case(tmp_path, 'ddx', 'a')
    tracker = Mock()
    service = LabtracUploadService(tmp_path, Client(fail=True), sql_tracker=tracker)
    service.upload(('ddx',))
    tracker.record_submission.assert_not_called()


@pytest.mark.parametrize('broken', ['{', 'null', '[]'])
def test_malformed_case_does_not_stop_next_case(tmp_path, broken):
    path = write_case(tmp_path, 'ddx', 'a')
    path.write_text(broken)
    write_case(tmp_path, 'ddx', 'b')
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    assert [r['status'] for r in service.upload(('ddx',))] == ['needs_review', 'uploaded']
    assert len(client.payloads) == 1


def test_successful_submission_history_save_failure_keeps_claim(tmp_path, monkeypatch):
    from unittest.mock import Mock
    write_case(tmp_path, 'ddx', 'a')
    client = Client()
    tracker = Mock()
    service = LabtracUploadService(tmp_path, client, sql_tracker=tracker)
    monkeypatch.setattr(service, 'save', lambda *args: (_ for _ in ()).throw(PermissionError('locked')))
    outcome = service.upload(('ddx',))[0]
    assert outcome['status'] == 'needs_review'
    assert outcome['submissionId']
    assert 'history save failed' in outcome['error']
    tracker.record_submission.assert_called_once()
    assert service.history.status('ddx', 'a') == 'in_progress'
    service.upload(('ddx',))
    assert len(client.payloads) == 1


def test_database_allowlist_does_not_pick_unlisted_case(tmp_path):
    for case in ('a', 'b'):
        write_case(tmp_path, 'ddx', case)
    client = Client()
    service = LabtracUploadService(tmp_path, client)
    outcomes = service.upload(('ddx',), eligible_cases={('ddx', 'b')})
    assert [r['case'] for r in outcomes] == ['b']
    assert service.history.status('ddx', 'a') is None
