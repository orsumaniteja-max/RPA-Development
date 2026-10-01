import json
from types import SimpleNamespace
from unittest.mock import Mock

import services.axs_straumann_case_capture_service as axs_capture_module
from pages.axs_straumann.order_details_page import OrderDetailsPage
from pages.axs_straumann.login_page import LoginPage
from services.axs_straumann_case_capture_service import AxsStraumannCaseCaptureService


def test_axs_case_number_supports_label_and_displayed_text():
    assert OrderDetailsPage.case_number({"Case Number": "AXS-100"}) == "AXS-100"
    assert OrderDetailsPage.case_number({"Displayed Text": "Order # 12345"}) == "12345"


def test_axs_removes_patient_ids_recursively_but_preserves_other_ids():
    payload = {
        "patientInfo": {"id": "secret", "name": "Patient"},
        "caseNumber": "AXS-100",
        "customerAccount": {"prescriber": {"id": "doctor-1"}},
        "metadata": {"Patient ID": "secret", "patient_identifier": "secret"},
    }

    AxsStraumannCaseCaptureService._remove_patient_ids(payload)

    assert payload["patientInfo"] == {"name": "Patient"}
    assert payload["customerAccount"]["prescriber"]["id"] == "doctor-1"
    assert payload["metadata"] == {}


def test_axs_case_owner_is_normalized_to_doctor_name():
    assert AxsStraumannCaseCaptureService._person_name(
        "GS\nGeoffrey Stefko\nBuckeye Dental and Braces"
    ) == "Geoffrey Stefko"


def test_axs_parses_order_and_clinic_dashboard_sections():
    displayed = """IO-260828-1
In validation
Patient
EXT-260828-104116
Summary
-
Lab
R
Roe Dental Lab
Order information
Submitted on
Aug 28, 2026, 20:45
Due date
Sep 18, 2026
Case owner
GS
Geoffrey Stefko
Buckeye Dental and Braces
Patient
EXT-260828-104116
Type of order
-
Sites to restore
-
Comment
Please make a surgical guide
Doctor will send over CBCT Scan
Lab slip
Clinic information
Name
B
Buckeye Dental and Braces
Phone
+1 440-934-3333
Mail
stefkogl@yahoo.com"""

    result = OrderDetailsPage.parse_displayed_text(displayed)

    assert result["Case owner"] == "Geoffrey Stefko"
    assert result["Submitted on"] == "Aug 28, 2026, 20:45"
    assert result["Due date"] == "Sep 18, 2026"
    assert result["Patient"] == "EXT-260828-104116"
    assert result["Type of order"] == "-"
    assert result["Sites to restore"] == "-"
    assert result["Lab"] == "Roe Dental Lab"
    assert result["Comment"] == (
        "Please make a surgical guide\nDoctor will send over CBCT Scan"
    )
    assert result["Clinic Name"] == "Buckeye Dental and Braces"
    assert result["Clinic Phone"] == "+1 440-934-3333"
    assert result["Clinic Mail"] == "stefkogl@yahoo.com"
    assert result["Lab slip"] == ""


def test_axs_writes_case_owner_and_clinic_as_prescriber_details(tmp_path, monkeypatch):
    monkeypatch.setattr(axs_capture_module, "RpaCaseTrackingService", Mock())
    class DoctorCatalogStub:
        last_match = SimpleNamespace(method="fuzzy", confidence=96.5)
        last_match_error = None

        def apply(self, payload, practice="", match_name=""):
            payload["customerAccount"]["prescriber"]["id"] = "doctor-1"
            return SimpleNamespace(doctor_id="doctor-1", account_id="account-1")

    raw = {
        "Submitted on": "Aug 28, 2026, 20:45",
        "Due date": "Sep 18, 2026",
        "Case owner": "GS\nGeoffrey Stefko\nBuckeye Dental and Braces",
        "Patient": "EXT-260828-104116",
        "Type of order": "-",
        "Sites to restore": "-",
        "Comment": "Shirely Dingess\nPlease make a surgical Guide for implant # 3, 12, 30, 19",
        "Clinic Name": "Buckeye Dental and Braces",
        "Clinic Phone": "+1 440-934-3333",
        "Clinic Mail": "stefkogl@yahoo.com",
        "Displayed Text": "AXS order dashboard",
    }
    service = AxsStraumannCaseCaptureService(tmp_path)
    result = service._export(Mock(), "IO-260828-1", raw, DoctorCatalogStub())
    payload = json.loads(result.json_file.read_text(encoding="utf-8"))

    prescriber = payload["customerAccount"]["prescriber"]
    assert prescriber["name"] == "Geoffrey Stefko"
    assert prescriber["contact"] == {
        "displayName": "Geoffrey",
        "email": "stefkogl@yahoo.com",
        "phone": "+1 440-934-3333",
    }
    assert prescriber["clinic"] == {
        "name": "Buckeye Dental and Braces",
        "phone": "+1 440-934-3333",
        "email": "stefkogl@yahoo.com",
    }
    assert payload["clinicInformation"] == prescriber["clinic"]
    assert payload["orderInformation"]["doctor"] == "Geoffrey Stefko"
    assert payload["doctorMatch"] == {
        "status": "matched",
        "method": "fuzzy",
        "confidence": 96.5,
        "matchedIdType": "doctorId",
        "matchedId": "doctor-1",
    }


def test_axs_does_not_treat_footer_as_clinic_email():
    displayed = """Clinic information
Name
S
Signature Smiles Streetsboro
Phone
+13304236779
Mail
Copyright © 2026 Straumann
CCPA
Imprint"""

    result = OrderDetailsPage.parse_displayed_text(displayed)

    assert "Clinic Mail" not in result


def test_axs_adopts_live_auth_replacement_page():
    closed_page = Mock()
    closed_page.is_closed.return_value = True
    replacement = Mock()
    replacement.is_closed.return_value = False
    login = LoginPage.__new__(LoginPage)
    login.page = closed_page
    login.context = Mock(pages=[closed_page, replacement])

    assert login._adopt_live_page() is True
    assert login.page is replacement
    replacement.bring_to_front.assert_called_once_with()


def test_axs_skips_tracked_order_before_opening_or_capturing(tmp_path, monkeypatch):
    monkeypatch.setattr(axs_capture_module, "RpaCaseTrackingService", Mock())
    page = Mock()
    login = Mock()
    login.login.return_value = page
    orders = Mock()
    orders.record_count.return_value = 1
    orders.record_id.return_value = "IO-EXISTING"
    orders.has_next_page.return_value = False
    details = Mock()

    monkeypatch.setattr(axs_capture_module, "LoginPage", Mock(return_value=login))
    monkeypatch.setattr(
        axs_capture_module,
        "DoctorCatalogService",
        Mock(return_value=Mock(load_and_export=Mock())),
    )
    monkeypatch.setattr(axs_capture_module, "LabOrdersPage", Mock(return_value=orders))
    monkeypatch.setattr(axs_capture_module, "OrderDetailsPage", Mock(return_value=details))

    service = AxsStraumannCaseCaptureService(tmp_path)
    service.tracker.is_downloaded = Mock(return_value=True)

    assert service.capture_all_cases(page, "user", "password") == []
    service.tracker.is_downloaded.assert_called_once_with("IO-EXISTING")
    orders.open_record.assert_not_called()
    details.capture.assert_not_called()
