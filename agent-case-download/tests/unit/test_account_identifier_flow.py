import base64
import copy
import json

import pytest
from unittest.mock import Mock

from services.account_identifier_service import ensure_account_identifier
from services.doctor_catalog_service import DoctorCatalogService
from services.doctor_validation_service import DoctorRecord
from services.labtrac_api_service import LabtracApiClient, LabtracSettings
from services.labtrac_upload_service import LabtracUploadService
from utilities.config_reader import ConfigReader


@pytest.mark.parametrize("name,practice,records,expected", [
    ("Jane Smith", "North Dental Clinic", 1, "ACCOUNT-42"),
    ("Jane Smyth", "North Dental Clinic", 1, "ACCOUNT-42"),
    ("Jane Smith", "North Dental Clinc", 1, "ACCOUNT-42"),
    ("Unknown Person", "Unknown", 1, None),
    ("Jane Smith", "North Dental Clinic", 2, None),
    (None, None, 0, None),
])
def test_capture_through_create_and_submit(tmp_path, name, practice, records, expected):
    catalog = DoctorCatalogService(tmp_path)
    catalog.records = [DoctorRecord(
        account_id=f"ACCOUNT-{42 + index}", doctor_id=f"doctor-{index}",
        name="Jane Smith", practice="North Dental Clinic", email="",
    ) for index in range(records)]
    payload = {"reference": "case-1", "patientInfo": {"name": "Source Patient"},
               "description": "Source prescription", "customerAccount": {
        "prescriber": {"name": name, "contact": None}}}
    catalog.apply(payload, practice=practice)
    identifier = payload["customerAccount"]["prescriber"]["id"]
    if expected:
        assert identifier == expected
        assert "id" not in payload["customerAccount"]
    else:
        assert len(base64.urlsafe_b64decode(identifier)) == 32

    folder = ConfigReader.get_config("carestream")["report_folder"]
    path = tmp_path / "reports" / folder / "results" / "case-1.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    requests = []

    class Response:
        def __init__(self, value):
            self.value = value
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json.dumps(self.value).encode()

    def opener(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/token"):
            return Response({"access_token": "test"})
        if request.full_url.endswith("/submit"):
            return Response({})
        if request.get_method() == "GET" and request.full_url.endswith("/RxSubmissions"):
            return Response({"value": [{"id": "created-case", "status": "Pending"}]})
        return Response({"id": "created-case"})

    settings = LabtracSettings(
        "https://example.test/token", "https://example.test", "app", "org",
        "unit", "integration", "client", "secret", "scope", "user", "doctor", "name",
    )
    uploader = LabtracUploadService(tmp_path, LabtracApiClient(settings, opener),
                                    Mock(resolve=Mock(return_value=expected)), sql_tracker=Mock())
    if expected is None:
        assert uploader.upload(("carestream",))[0]["status"] == "needs_review"
        assert requests == []
        return
    assert uploader.upload(("carestream",))[0]["status"] == "uploaded"
    assert len(requests) == 4
    assert requests[-2].full_url.endswith("/created-case/submit")
    assert requests[-1].get_method() == "GET"
    assert requests[-1].full_url.endswith("/RxSubmissions")
    assert json.loads(requests[1].data)["customerAccount"]["id"] == identifier
    assert uploader.upload(("carestream",)) == []


def test_missing_account_uses_fallback_even_with_matched_doctor(tmp_path):
    catalog = DoctorCatalogService(tmp_path)
    catalog.records = [DoctorRecord("", "Jane Smith", "", "", doctor_id="doctor")]
    payload = {"customerAccount": {"prescriber": {"name": "Jane Smith"}}}
    catalog.apply(payload)
    assert len(base64.urlsafe_b64decode(payload["customerAccount"]["prescriber"]["id"])) == 32
    assert "id" not in payload["customerAccount"]


@pytest.mark.parametrize("account", [None, "invalid", {}, {"id": 123}, {"id": " "}])
def test_empty_and_invalid_account_data(account):
    payload = {"reference": "stable-case", "customerAccount": account}
    duplicate = copy.deepcopy(payload)
    identifier = ensure_account_identifier(payload)
    assert identifier == ensure_account_identifier(duplicate)
    assert identifier == ensure_account_identifier(payload)
    assert len(base64.urlsafe_b64decode(identifier)) == 32


def test_fallback_is_namespaced_and_independent_of_key_order():
    assert ensure_account_identifier({"reference": "a", "description": "b"}) == ensure_account_identifier({"description": "b", "reference": "a"})
    assert ensure_account_identifier({}, "portal:a") != ensure_account_identifier({}, "portal:b")
    assert ensure_account_identifier({"reference": "case-1", "description": "old"}, "portal") == ensure_account_identifier({"reference": "case-1", "description": "new"}, "portal")


@pytest.mark.parametrize("value", [None, [], "invalid", 42])
def test_invalid_payload_rejected(value):
    with pytest.raises(ValueError):
        ensure_account_identifier(value)
