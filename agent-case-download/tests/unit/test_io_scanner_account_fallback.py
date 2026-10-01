import json
from unittest.mock import Mock

import pytest

from services.doctor_catalog_service import DoctorCatalogService
from services.doctor_validation_service import DoctorRecord
from services.io_scanner_case_capture_service import IoScannerCaseCaptureService


@pytest.mark.parametrize("records,expected", [
    ([], "Erin_Pender_5441"),
    ([DoctorRecord("DB-ACCOUNT", "Erin Pender", "", "", doctor_id="doctor")], "DB-ACCOUNT"),
    ([DoctorRecord("", "Erin Pender", "", "", doctor_id="doctor")], "Erin_Pender_5441"),
    ([DoctorRecord("A", "Erin Pender", "", "", doctor_id="a"),
      DoctorRecord("B", "Erin Pender", "", "", doctor_id="b")], "Erin_Pender_5441"),
])
def test_source_account_fallback_preserves_matched_account(tmp_path, records, expected):
    service = IoScannerCaseCaptureService.__new__(IoScannerCaseCaptureService)
    service.results_root = tmp_path / "results"
    service.case_tracker = Mock()
    catalog = DoctorCatalogService(tmp_path / "ioscanner")
    catalog.records = records
    result = service._export(Mock(), "5441_1776886980455", {"Doctor": "Erin Pender"}, catalog)
    payload = json.loads(result.json_file.read_text())
    assert payload["customerAccount"]["prescriber"]["id"] == expected
    assert payload["sourceAccountId"] == "5441"
    assert payload["reference"] == "5441_1776886980455"
    if len(records) == 1:
        assert payload["customerAccount"]["prescriber"]["id"] == expected


def test_invalid_order_retains_generated_fallback(tmp_path):
    service = IoScannerCaseCaptureService.__new__(IoScannerCaseCaptureService)
    service.results_root = tmp_path / "results"
    service.case_tracker = Mock()
    result = service._export(Mock(), "invalid", {}, DoctorCatalogService(tmp_path))
    payload = json.loads(result.json_file.read_text())
    assert payload["customerAccount"]["prescriber"]["id"]
    assert "sourceAccountId" not in payload
