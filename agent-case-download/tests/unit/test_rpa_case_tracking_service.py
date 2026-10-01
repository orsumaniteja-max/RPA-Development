import csv
import sqlite3
from unittest.mock import Mock

import pytest

from services.rpa_case_tracking_service import RpaCaseTrackingService


def test_sql_backfill_and_duplicate_retry(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "RX_100.json").write_text('{"reference": "RX/100"}')
    (results / "invalid.json").write_text('broken')
    sql = Mock()
    tracker = RpaCaseTrackingService("ddx", results, tmp_path / "tracking.db", sql)
    sql.sync.assert_called_once_with("ddx", ["RX/100"])
    sql.sync.reset_mock()
    assert tracker.record_download("RX-200", "Doctor")
    sql.sync.assert_called_once_with("ddx", ["RX-200"])
    sql.sync.side_effect = RuntimeError("SQL unavailable")
    with pytest.raises(RuntimeError, match="SQL unavailable"):
        tracker.record_download("RX-300", "Doctor")
    sql.sync.side_effect = None
    assert tracker.record_download("RX-300", "Doctor") is False
    sql.sync.assert_called_with("ddx", ["RX-300"])


@pytest.mark.parametrize("existing", [True, False])
def test_sql_uses_master_key_and_transaction(monkeypatch, existing):
    import sys
    from types import SimpleNamespace
    from services.rpa_sql_tracking_service import RpaSqlTrackingService

    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchall.return_value = [("RX-existing",)]
    cursor.fetchone.side_effect = [("master-id",)] if existing else [None, ("master-id",)]
    monkeypatch.setitem(sys.modules, "pymssql", SimpleNamespace(connect=Mock(return_value=connection)))
    for key in ("SERVER", "DATABASE", "USERNAME", "PASSWORD"):
        monkeypatch.setenv("AZURE_SQL_" + key, "test")
    RpaSqlTrackingService().sync("ddx", ["RX-1", "RX-1", "RX-2", "RX-existing"])
    inserts = [call for call in cursor.execute.call_args_list if "INSERT INTO dbo.RpaDownloadedCase" in call.args[0]]
    assert [call.args[1] for call in inserts] == [
        ("master-id", "RX-1", "master-id", "RX-1"),
        ("master-id", "RX-2", "master-id", "RX-2"),
    ]
    updates = [call for call in cursor.execute.call_args_list if "UPDATE dbo.RpaDownloadedCase" in call.args[0]]
    assert updates == []  # History synchronization must preserve current case statuses.
    connection.commit.assert_called_once()
    connection.close.assert_called_once()

    cursor.execute.side_effect = RuntimeError("write failed")
    with pytest.raises(RuntimeError, match="write failed"):
        RpaSqlTrackingService().sync("ddx", ["RX-3"])
    connection.rollback.assert_called_once()


def test_records_case_and_prevents_duplicate(tmp_path):
    tracker = RpaCaseTrackingService(
        "cares_connect", tmp_path / "results", tmp_path / "tracking.db"
    )

    assert tracker.is_downloaded("RX-100") is False
    assert tracker.record_download("RX-100", "Dr. Jane Doe") is True
    assert tracker.record_download("RX-100", "Dr. Jane Doe") is False
    assert tracker.is_downloaded("RX-100") is False
    tracker.results_root.mkdir(parents=True)
    (tracker.results_root / "RX-100.json").write_text("{}", encoding="utf-8")
    assert tracker.is_downloaded("RX-100") is True

    with sqlite3.connect(tracker.database_path) as connection:
        row = connection.execute(
            """
            SELECT apps.ApplicationName, cases.PrescriptionId,
                   cases.DoctorName, cases.DownloadedAt
            FROM RpaDownloadedCases AS cases
            JOIN RpaApplications AS apps ON apps.Id = cases.ApplicationId
            """
        ).fetchone()

    assert row[:3] == ("cares_connect", "RX-100", "Dr. Jane Doe")
    assert row[3].endswith("Z")


def test_existing_result_is_adopted_without_rewrite(tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    result_file = results / "RX-200.json"
    result_file.write_text('{"original": true}', encoding="utf-8")
    original_timestamp = result_file.stat().st_mtime_ns
    tracker = RpaCaseTrackingService(
        "cares_connect", results, tmp_path / "tracking.db"
    )

    assert tracker.is_downloaded("RX-200") is True
    assert result_file.read_text(encoding="utf-8") == '{"original": true}'
    assert result_file.stat().st_mtime_ns == original_timestamp

    with sqlite3.connect(tracker.database_path) as connection:
        assert connection.execute(
            "SELECT PrescriptionId FROM RpaDownloadedCases"
        ).fetchone() == ("RX-200",)


def test_csv_contains_only_latest_case_for_each_doctor(tmp_path):
    tracker = RpaCaseTrackingService(
        "cares_connect", tmp_path / "results", tmp_path / "tracking.db"
    )

    tracker.record_download("RX-100", " Dr. Jane Doe ")
    tracker.record_download("RX-200", "dr. jane doe")
    tracker.record_download("RX-300", "Dr. John Smith")
    tracker.record_download("RX-400", "")

    with tracker.csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert rows == [
        {
            "ApplicationName": "cares_connect",
            "PrescriptionId": "RX-200",
            "DoctorName": "dr. jane doe",
            "DownloadedAt": rows[0]["DownloadedAt"],
        },
        {
            "ApplicationName": "cares_connect",
            "PrescriptionId": "RX-300",
            "DoctorName": "Dr. John Smith",
            "DownloadedAt": rows[1]["DownloadedAt"],
        },
    ]


@pytest.mark.parametrize('rowcount', [0, 1, 2])
def test_sql_submission_date_preserves_download_date(monkeypatch, rowcount):
    import sys
    from types import SimpleNamespace
    from datetime import datetime
    from services.rpa_sql_tracking_service import RpaSqlTrackingService
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.rowcount = rowcount
    monkeypatch.setitem(sys.modules, 'pymssql', SimpleNamespace(connect=Mock(return_value=connection)))
    for key in ('SERVER', 'DATABASE', 'USERNAME', 'PASSWORD'):
        monkeypatch.setenv('AZURE_SQL_' + key, 'test')
    if rowcount == 1:
        RpaSqlTrackingService().record_submission('ddx', 'source/reference', '2026-09-23T15:30:00+05:30')
        connection.commit.assert_called_once()
    else:
        with pytest.raises(RuntimeError, match='one downloaded-case row'):
            RpaSqlTrackingService().record_submission('ddx', 'source/reference', '2026-09-23T15:30:00+05:30')
        connection.rollback.assert_called_once()
    query, parameters = cursor.execute.call_args.args
    assert 'CreatedAt' not in query
    assert 'CaseSubmisisonAt' in query
    assert parameters == (datetime(2026, 9, 23, 10), datetime(2026, 9, 23, 10), 'ddx', 'source/reference')
    connection.close.assert_called_once()
