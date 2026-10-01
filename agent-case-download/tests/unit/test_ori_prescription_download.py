"""ORI prescription download and doctor identity regression coverage."""

import json
from unittest.mock import Mock, call, patch

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from pages.ori_portal.case_details_page import CaseDetailsPage
from pages.ori_portal.dashboard_page import DashboardPage
from services.doctor_catalog_service import DoctorCatalogService
from services.ori_case_capture_service import OriCaseCaptureService


def write_prescription(path, text="License No.: 0039328"):
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=500)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
    })
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 30 400 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    writer.write(path)


def test_download_saves_event_file_to_case_path(tmp_path):
    page = Mock()
    event = Mock()
    page.expect_download.return_value.__enter__ = Mock(return_value=event)
    page.expect_download.return_value.__exit__ = Mock(return_value=False)
    dashboard = DashboardPage(page)
    dashboard.click = Mock()
    operations = Mock()
    operations.attach_mock(dashboard.click, "click")
    operations.attach_mock(page.expect_download.return_value.__enter__, "listen")
    operations.attach_mock(event.value.save_as, "save")
    destination = tmp_path / "results" / "123_prescription.pdf"

    assert dashboard.download_prescription(destination) == destination
    assert operations.mock_calls == [
        call.click(dashboard.ACTIONS_SECTION),
        call.listen(),
        call.click(dashboard.PRESCRIPTION_BUTTON),
        call.save(str(destination)),
        call.click(dashboard.DETAILS_SECTION),
    ]


def test_export_uses_downloaded_licence_for_doctor_identity(tmp_path):
    with patch("services.ori_case_capture_service.RpaCaseTrackingService"):
        service = OriCaseCaptureService(tmp_path / "oriportal")
    page = Mock()
    information = {"Doctor": "Dr. Erin Pender", "License No": "old"}

    def download(destination):
        write_prescription(destination)
        return destination

    with patch.object(DashboardPage, "download_prescription", side_effect=download):
        result = service._export(
            page, "123", information, DoctorCatalogService(tmp_path / "oriportal")
        )

    payload = json.loads(result.json_file.read_text(encoding="utf-8"))
    assert result.prescription_file.is_file()
    assert payload["customerAccount"]["prescriber"]["licenceNo"] == "0039328"
    assert payload["customerAccount"]["prescriber"]["id"] == "Erin_Pender_0039328"
    assert json.loads(result.text_file.read_text())["License No"] == "0039328"
    service.case_tracker.record_download.assert_called_once()


def test_download_failure_does_not_mark_case_complete(tmp_path):
    with patch("services.ori_case_capture_service.RpaCaseTrackingService"):
        service = OriCaseCaptureService(tmp_path)
    with patch.object(DashboardPage, "download_prescription", side_effect=RuntimeError("failed")):
        with pytest.raises(RuntimeError, match="failed"):
            service._export(Mock(), "123", {}, Mock())
    service.case_tracker.record_download.assert_not_called()
    assert not (service.results_root / "123.json").exists()


def test_pdf_without_licence_does_not_use_case_number(tmp_path):
    path = tmp_path / "prescription.pdf"
    write_prescription(path, "Case ID: 123456")
    assert CaseDetailsPage.license_from_pdf(path) == ""


@pytest.mark.parametrize("text,expected", [
    ("License No.: BN9950040\nSignature Image:", "BN9950040"),
    ("License No.:\n0039328\nSignature Image:", "0039328"),
    ("License No.:\nSignature Image:", ""),
    ("License No.:\n\nSignature Image:", ""),
])
def test_licence_does_not_capture_next_pdf_label(text, expected):
    assert CaseDetailsPage._license_from_text(text) == expected


@pytest.mark.parametrize("name,licence,expected", [
    ("Dr. Norwood", "BN9950040", "_Norwood_BN9950040"),
    ("Norwood", "22768", "_Norwood_22768"),
    ("John Norwood", "00123", "John_Norwood_00123"),
    ("", "00123", "__00123"),
])
def test_ori_unmatched_identifier_uses_available_name_and_licence(tmp_path, name, licence, expected):
    catalog = DoctorCatalogService(tmp_path / "oriportal")
    for reference in ("case-one", "case-two"):
        payload = {"reference": reference, "customerAccount": {
            "prescriber": {"name": name, "licenceNo": licence}}}
        catalog.apply(payload)
        assert payload["customerAccount"]["prescriber"]["id"] == expected
        assert "id" not in payload["customerAccount"]


@pytest.mark.parametrize("name,expected", [
    ("", "__"),
    ("Dr. Norwood", "_Norwood_"),
    ("John Norwood", "John_Norwood_"),
])
def test_ori_missing_fields_preserve_three_positions(tmp_path, name, expected):
    from services.account_identifier_service import ensure_account_identifier

    catalog = DoctorCatalogService(tmp_path / "oriportal")
    for case_id in ("7dc9c9bc", "8d728132"):
        payload = {"reference": case_id, "customerAccount": {
            "prescriber": {"name": name, "licenceNo": ""}}}
        catalog.apply(payload)
        assert payload["customerAccount"]["prescriber"]["id"] == expected
        assert ensure_account_identifier(payload, "oriportal") == expected
        assert "id" not in payload["customerAccount"]
