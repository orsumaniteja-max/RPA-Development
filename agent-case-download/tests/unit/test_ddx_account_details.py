import json
from unittest.mock import Mock
import pytest

from pages.ddx.case_details_page import CaseDetailsPage
from services.ddx_case_capture_service import DdxCaseCaptureService
from services.doctor_catalog_service import DoctorCatalogService
from services.doctor_validation_service import DoctorRecord
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


TEXT = """Case #1434313
Account:
Dr. Brian Lentz
850 Cherry Street
Waterford PA US 16441
Phone: 8147962649
Email:
lentz@example.test
Provider:
Another Doctor
Phone: 9999999999
Email: other@example.test
"""


def test_account_contacts_exclude_provider_details():
    assert CaseDetailsPage._account_contact_from_text(TEXT) == {
        "Doctor Address": "850 Cherry Street\nWaterford PA US 16441",
        "Doctor Phone": "8147962649",
        "Doctor Email": "lentz@example.test",
    }


def test_collapsed_account_has_no_contact_details():
    assert CaseDetailsPage._account_contact_from_text("Account:\nDoctor\nProvider:\nOther\nPhone: 123") == {}


def test_account_expansion_clicks_and_waits():
    page = Mock()
    page.locator.return_value.is_visible.return_value = False
    details = CaseDetailsPage(page)
    details.expand_account_details()
    page.locator.return_value.click.assert_called_once_with(timeout=10000)
    page.locator.return_value.wait_for.assert_called_once_with(state="visible", timeout=10000)
    assert page.locator.call_args_list[-1].args == ("#practice_contact_action",)


def test_expanded_account_is_not_collapsed():
    page = Mock()
    page.locator.return_value.is_visible.return_value = True
    CaseDetailsPage(page).expand_account_details()
    page.locator.return_value.click.assert_not_called()


def test_account_expansion_retries_after_timeout():
    page = Mock()
    container, action = Mock(), Mock()
    page.locator.side_effect = lambda selector: (
        container if selector == CaseDetailsPage.ACCOUNT_CONTACT_CONTAINER else action
    )
    container.is_visible.return_value = False
    container.wait_for.side_effect = [PlaywrightTimeoutError("not open yet"), None]
    CaseDetailsPage(page).expand_account_details()
    assert action.click.call_count == 2


def test_retry_does_not_close_a_panel_that_opened_late():
    page = Mock()
    container, action = Mock(), Mock()
    page.locator.side_effect = lambda selector: (
        container if selector == CaseDetailsPage.ACCOUNT_CONTACT_CONTAINER else action
    )
    container.is_visible.side_effect = [False, True]
    container.wait_for.side_effect = PlaywrightTimeoutError("late animation")
    CaseDetailsPage(page).expand_account_details()
    action.click.assert_called_once()


def test_failed_toggle_reads_hidden_account_panel():
    page = Mock()
    container, body = Mock(), Mock()
    page.locator.side_effect = lambda selector: (
        container if selector == CaseDetailsPage.ACCOUNT_CONTACT_CONTAINER else body
    )
    container.text_content.return_value = "850 Cherry Street\nWaterford PA US 16441\nPhone: 8147962649\nEmail: lentz@example.test"
    body.inner_text.return_value = "Account:\nDr. Brian Lentz\nProvider:\nBRIAN LENTZ"
    details = CaseDetailsPage(page)
    details.expand_account_details = Mock(side_effect=PlaywrightTimeoutError("toggle failed"))
    details.get_case_information = Mock(return_value={"Provider": "BRIAN LENTZ"})
    details._visible_tables = Mock(return_value=[])
    info = details.get_all_displayed_details()["Case Information"]
    assert info["Doctor Email"] == "lentz@example.test"
    assert info["Doctor Phone"] == "8147962649"
    assert info["Doctor Address"] == "850 Cherry Street\nWaterford PA US 16441"


def test_unreadable_account_stops_capture():
    page = Mock()
    page.locator.return_value.text_content.return_value = ""
    details = CaseDetailsPage(page)
    details.expand_account_details = Mock()
    details.get_case_information = Mock()
    with pytest.raises(RuntimeError, match="case was not exported"):
        details.get_all_displayed_details()
    details.get_case_information.assert_not_called()


@pytest.mark.parametrize("contact,address,expected", [
    ({"email": "", "phone": ""}, "", True),
    ({"email": "lentz@example.test"}, "", False),
    ({"phone": "1234567890"}, "", False),
    ({}, "850 Cherry Street", False),
])
def test_legacy_incomplete_results_are_recaptured(tmp_path, contact, address, expected):
    service = DdxCaseCaptureService.__new__(DdxCaseCaptureService)
    service.results_root = tmp_path
    (tmp_path / "123.json").write_text(json.dumps({
        "customerAccount": {"prescriber": {"contact": contact}},
        "doctorInformation": {"address": address},
    }))
    assert service._needs_contact_retry("123") is expected
    assert service._needs_contact_retry("not-local") is False


def test_account_failure_does_not_export_or_mark_complete(tmp_path, monkeypatch):
    from services import ddx_case_capture_service as module
    service = DdxCaseCaptureService.__new__(DdxCaseCaptureService)
    service.results_root = tmp_path
    service.case_tracker = Mock()
    service.case_tracker.is_downloaded.return_value = False
    service._export = Mock()
    details, dashboard = Mock(), Mock()
    details.get_case_id.return_value = "1366818"
    details.get_all_displayed_details.side_effect = RuntimeError("account unreadable")
    dashboard.get_record_count.return_value = 1
    monkeypatch.setattr(module, "LoginPage", Mock())
    monkeypatch.setattr(module, "DashboardPage", Mock(return_value=dashboard))
    monkeypatch.setattr(module, "CaseDetailsPage", Mock(return_value=details))
    monkeypatch.setattr(module, "DoctorCatalogService", Mock())
    with pytest.raises(RuntimeError, match="account unreadable"):
        service.capture_all_cases(Mock(), "user", "password", max_cases=1)
    service._export.assert_not_called()
    service.case_tracker.record_download.assert_not_called()


def test_export_passes_contacts_to_matching_and_json(tmp_path):
    service = DdxCaseCaptureService.__new__(DdxCaseCaptureService)
    service.results_root = tmp_path
    service.case_tracker = Mock()
    catalog = Mock()
    info = {"Provider": "Brian Lentz", "Account": "Dr. Brian Lentz"}
    info.update(CaseDetailsPage._account_contact_from_text(TEXT))
    result = service._export(Mock(), "1434313", {
        "Case Information": info, "Displayed Text": TEXT,
    }, catalog)
    payload = json.loads(result.json_file.read_text())
    assert payload["customerAccount"]["prescriber"]["contact"]["email"] == "lentz@example.test"
    assert payload["customerAccount"]["prescriber"]["contact"]["phone"] == "8147962649"
    assert payload["customerAccount"]["prescriber"]["contact"]["first_name"] == "Brian"
    assert payload["customerAccount"]["prescriber"]["contact"]["last_name"] == "Lentz"
    assert payload["doctorInformation"]["address"] == "850 Cherry Street\nWaterford PA US 16441"
    catalog.apply.assert_called_once_with(payload, "Dr. Brian Lentz")


def test_contact_fallback_is_deterministic_and_preserves_matched_id():
    from copy import deepcopy
    from services.account_identifier_service import ensure_account_identifier

    source = {"reference": "1434313", "customerAccount": {"prescriber": {"contact": {
        "first_name": "Brian", "last_name": "Lentz",
        "phone": "814-796-2649", "email": "lentz@example.test",
    }}}}
    payload = deepcopy(source)
    identifier = ensure_account_identifier(payload, "ddx")
    assert identifier == "Brian_Lentz_lentz@example.test"
    assert ensure_account_identifier(deepcopy(source), "ddx") == identifier
    assert ensure_account_identifier(payload, "ddx") == identifier
    changed = deepcopy(source)
    changed["customerAccount"]["prescriber"]["contact"]["email"] = "another@example.test"
    assert ensure_account_identifier(changed, "ddx") != identifier
    changed = deepcopy(source)
    changed["reference"] = "another-case"
    assert ensure_account_identifier(changed, "ddx") == identifier
    payload["customerAccount"]["id"] = "ACTUAL-ACCOUNT"
    assert ensure_account_identifier(payload, "ddx") == "ACTUAL-ACCOUNT"


@pytest.mark.parametrize("matched", [False, True])
def test_expanded_account_identifies_doctor_across_cases(tmp_path, matched):
    service = DdxCaseCaptureService.__new__(DdxCaseCaptureService)
    service.results_root = tmp_path / "ddx" / "results"
    service.case_tracker = Mock()
    catalog = DoctorCatalogService(tmp_path / "ddx")
    if matched:
        catalog.records = [DoctorRecord(
            account_id="LENTZ", name="Brian Lentz", practice="Dr. Brian Lentz",
            email="lentz@example.test", doctor_id="doctor-uuid",
        )]
    info = {"Provider": "Brian Lentz", "Account": "Dr. Brian Lentz"}
    info.update(CaseDetailsPage._account_contact_from_text(TEXT))
    for case_id in ("1434313", "1434314"):
        result = service._export(Mock(), case_id, {
            "Case Information": info, "Displayed Text": TEXT,
        }, catalog)
        account = json.loads(result.json_file.read_text())["customerAccount"]
        assert account["prescriber"]["id"] == (
            "LENTZ" if matched else "Brian_Lentz_lentz@example.test"
        )
        assert "id" not in account
