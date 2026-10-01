"""Match the deployed Doctor schema and use AccountId in every portal."""

import csv
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from services.account_identifier_service import ensure_account_identifier
from services.doctor_catalog_service import DoctorCatalogService
from services.doctor_match_service import DoctorMatchService


@pytest.fixture
def doctor_database(monkeypatch):
    row = {
        "ID": "00071B43-09F4-47B6-B287-6443454665C8",
        "AccountId": "LANDY",
        "AccountName": "Dr Jewel Landy",
        "PracticeName": "",
        "Email": "",
    }
    connection = Mock()
    connection.cursor.return_value.fetchall.return_value = [row]
    monkeypatch.setitem(sys.modules, "pymssql", SimpleNamespace(
        connect=Mock(return_value=connection)
    ))
    for key in ("SERVER", "DATABASE", "USERNAME", "PASSWORD"):
        monkeypatch.setenv(f"AZURE_SQL_{key}", "test-value")
    monkeypatch.delenv("DOCTOR_MATCH_ALERTS_ENABLED", raising=False)
    return row


@pytest.mark.parametrize("portal", [
    "ddx", "carestream", "caresconnect", "ioscanner", "oriportal", "axs_straumann",
])
def test_database_account_id_replaces_generated_id(tmp_path, doctor_database, portal):
    catalog = DoctorCatalogService(tmp_path / portal)
    catalog.load_and_export()
    payload = {"reference": "case-123", "customerAccount": {
        "id": "iZWQiJZCGF2IQe2nX8zICPqymA33cCzmsod4eYEJh2c=",
        "prescriber": {"name": "Dr. Jewel Landy", "id": "old-doctor-id"},
    }}

    assert catalog.apply(payload) is not None
    assert payload["customerAccount"]["prescriber"]["id"] == "LANDY"
    assert ensure_account_identifier(payload, portal) == "LANDY"
    assert "id" not in payload["customerAccount"]
    with (catalog.results_root / "doctors.csv").open(encoding="utf-8-sig", newline="") as stream:
        exported = next(csv.DictReader(stream))
    assert exported["DoctorName"] == "Dr Jewel Landy"
    assert exported["AccountId"] == "LANDY"


@pytest.mark.parametrize("column", ["DoctorName", "Name"])
def test_legacy_name_columns_remain_supported(tmp_path, doctor_database, column):
    doctor_database["AccountName"] = ""
    doctor_database[column] = "Dr Jewel Landy"
    catalog = DoctorCatalogService(tmp_path)
    assert catalog.load_and_export()[0].name == "Dr Jewel Landy"


def test_matcher_accepts_account_name_from_database_row(doctor_database):
    match = DoctorMatchService().identify(
        {"name": "Dr. Jewel Landy"}, [doctor_database]
    )
    assert match.doctor.account_id == "LANDY"


def test_unmatched_doctor_keeps_fallback(tmp_path, doctor_database):
    catalog = DoctorCatalogService(tmp_path / "oriportal")
    catalog.load_and_export()
    payload = {"reference": "case-123", "customerAccount": {
        "prescriber": {"name": "Dr. Alice Smith", "licenceNo": "12345"},
    }}
    assert catalog.apply(payload) is None
    assert payload["customerAccount"]["prescriber"]["id"] == "Alice_Smith_12345"
