from copy import deepcopy
import json

import pytest

from services.account_identifier_service import ensure_account_identifier
from services.doctor_catalog_service import DoctorCatalogService
from services.doctor_validation_service import DoctorRecord
from services.labtrac_api_service import LabtracApiClient, LabtracSettings


@pytest.mark.parametrize("portal,suffix,expected", [
    ("ioscanner", {}, "Erin_Pender_5441"),
    ("oriportal", {"licenceNo": "39328"}, "Erin_Pender_39328"),
    ("carestream", {"contact": {"email": "ERIN@example.test"}}, "Erin_Pender_erin@example.test"),
    ("axs_straumann", {"contact": {"phone": "+1 (662) 655-4868"}}, "Erin_Pender_16626554868"),
    ("ddx", {"contact": {"email": "erin@example.test"}}, "Erin_Pender_erin@example.test"),
    ("caresconnect", {}, "Erin_Pender"),
])
def test_portal_fallback_through_matching_and_submission(tmp_path, portal, suffix, expected):
    original = {"reference": "5441_1776886980455", "customerAccount": {
        "prescriber": {"name": "Dr. Erin Pender", **suffix}}}
    catalog = DoctorCatalogService(tmp_path / portal)
    payload = deepcopy(original)
    catalog.apply(payload)
    assert payload["customerAccount"]["prescriber"]["id"] == expected
    assert ensure_account_identifier(payload, portal) == expected
    repeated = deepcopy(original)
    catalog.apply(repeated)
    assert repeated == payload
    requests = []
    class Response:
        def __init__(self, value): self.value = value
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(self.value).encode()
    def opener(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/token"):
            return Response({"access_token": "token"})
        return Response({"id": "case-created"})
    settings = LabtracSettings("https://example.test/token", "https://example.test", "a", "o", "u", "i", "c", "s", "scope", "user", "doctor", "name")
    assert LabtracApiClient(settings, opener).submit_payload(payload)["submissionId"] == "case-created"
    submitted_account = json.loads(requests[1].data)["customerAccount"]
    assert submitted_account["prescriber"]["id"] == expected
    # Match Postman: a doctor ID must not become a customer account lookup.
    assert "id" not in submitted_account
    assert submitted_account == payload["customerAccount"]
    assert requests[2].full_url.endswith("/case-created/submit")
    catalog.records = [DoctorRecord("DB-ACCOUNT", "Erin Pender", "", "", doctor_id="doctor")]
    catalog.apply(payload)
    assert payload["customerAccount"]["prescriber"]["id"] == "DB-ACCOUNT"
    assert "id" not in payload["customerAccount"]


@pytest.mark.parametrize("portal", ["io_scanner", "ori_portal", "carestream", "axs_straumann", "ddx", "cares_connect"])
def test_missing_identity_still_has_deterministic_fallback(portal):
    payload = {"reference": "case"}
    assert ensure_account_identifier(deepcopy(payload), portal) == ensure_account_identifier(deepcopy(payload), portal)


def test_license_text_extraction():
    from pages.ori_portal.case_details_page import CaseDetailsPage
    assert CaseDetailsPage._license_from_text("Doctor Name: Alina Ploaie\nLicense No.:\n39328\nSignature Image:") == "39328"


def test_missing_pdf_dependency_does_not_stop_capture(monkeypatch):
    import sys
    from unittest.mock import Mock
    from pages.ori_portal.case_details_page import CaseDetailsPage

    monkeypatch.setitem(sys.modules, "pypdf", None)
    page = Mock()
    page.locator.return_value.inner_text.return_value = "Case Details"
    page.locator.return_value.evaluate_all.return_value = ["https://example.test/prescription.pdf"]
    details = CaseDetailsPage(page)
    details.get_detail = Mock(return_value="")
    assert details.get_license_number() == ""
    page.context.request.get.assert_not_called()


def test_license_is_read_from_linked_prescription_pdf():
    from io import BytesIO
    from unittest.mock import Mock
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    from pages.ori_portal.case_details_page import CaseDetailsPage

    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=500)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 30 400 Td (License No.: 39328) Tj ET")
    page[NameObject("/Contents")] = stream
    data = BytesIO()
    writer.write(data)
    browser_page = Mock()
    browser_page.locator.return_value.inner_text.return_value = "Case Details"
    browser_page.locator.return_value.evaluate_all.return_value = ["https://example.test/prescription.pdf"]
    response = browser_page.context.request.get.return_value
    response.ok = True
    response.body.return_value = data.getvalue()
    details = CaseDetailsPage(browser_page)
    details.get_detail = Mock(return_value="")
    assert details.get_license_number() == "39328"
    response.dispose.assert_called_once()
