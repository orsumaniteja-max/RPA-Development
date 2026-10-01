import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs

from services.labtrac_api_service import (
    DEFAULT_USER_ID,
    LabtracApiClient,
    LabtracSettings,
)


def test_api_error_includes_safe_phase_and_response_detail():
    settings = LabtracSettings(
        token_url="https://identity.example/token", api_base_url="https://connect.example/api",
        application_id="application", organisation_id="organisation", unit_id="unit",
        integration_id="integration", client_id="client", client_secret="private-secret",
        scope="scope", user_id="user", doctor_id="doctor", doctor_name="Doctor",
    )
    def opener(request, timeout):
        if request.full_url == settings.token_url:
            return FakeResponse({"access_token": "token"})
        raise HTTPError(request.full_url, 400, "Bad Request", {}, BytesIO(
            b'{"message":"CustomerAccount account-1 is not associated with user"}'))
    client = LabtracApiClient(settings, opener)
    import pytest
    with pytest.raises(Exception, match="HTTP 400 during creation.*not associated") as error:
        client.submit_payload({"customerAccount": {"id": "account-1"}, "patientInfo": {}})
    assert "private-secret" not in str(error.value)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_submit_payload_creates_then_submits_with_doctor_and_headers():
    requests = []
    responses = iter((
        FakeResponse({"id": "submission-123"}),
        FakeResponse({"id": "submission-123"}),
        FakeResponse({"value": [{"id": "submission-123", "status": "Pending"}]}),
    ))
    settings = LabtracSettings(
        token_url="https://identity.example/token",
        api_base_url="https://connect.example/api/v3.0",
        application_id="application",
        organisation_id="organisation",
        unit_id="unit",
        integration_id="integration",
        client_id="connect-veltris",
        client_secret="secret",
        scope="connect.data.reader connect.data.writer",
        user_id=DEFAULT_USER_ID,
        doctor_id=DEFAULT_USER_ID,
        doctor_name="Vitaly",
    )

    def opener(request, timeout):
        requests.append((request, timeout))
        if request.full_url.endswith("/token"):
            return FakeResponse({"access_token": "access-token"})
        return next(responses)

    client = LabtracApiClient(settings, opener)
    result = client.submit_payload({
        "patientInfo": {"name": "Patient"},
        "customerAccount": {"prescriber": {"name": "Source Doctor"}},
    })

    from datetime import datetime
    assert datetime.fromisoformat(result.pop("caseSubmissionAt")).utcoffset().total_seconds() == 0
    assert result == {
        "submissionId": "submission-123",
        "created": {"id": "submission-123"},
        "submitted": {"id": "submission-123"},
        "remoteStatus": "pending",
    }
    assert len(requests) == 4
    token_request, create_request, submit_request, list_request = [request for request, _ in requests]
    assert parse_qs(token_request.data.decode()) == {
        "grant_type": ["client_credentials"],
        "client_id": ["connect-veltris"],
        "client_secret": ["secret"],
        "scope": ["connect.data.reader connect.data.writer"],
    }
    assert create_request.full_url.endswith("/integrations/integration/RxSubmissions")
    assert submit_request.full_url.endswith(
        "/integrations/integration/RxSubmissions/submission-123/submit"
    )
    assert list_request.full_url.endswith("/integrations/integration/RxSubmissions")
    assert list_request.get_method() == "GET"
    assert create_request.headers["Authorization"] == "Bearer access-token"
    assert create_request.headers["Labtrac-userid"] == DEFAULT_USER_ID
    submitted_payload = json.loads(create_request.data.decode())
    assert submitted_payload["patientInfo"]["name"] == "Patient (RPA)"
    assert submitted_payload["customerAccount"]["prescriber"] == {
        "name": "Source Doctor",
        "id": submitted_payload["customerAccount"]["id"],
    }

    requests.clear()
    responses = iter((FakeResponse({"id": "second"}), FakeResponse({}), FakeResponse({"value": []})))
    payload = {"customerAccount": {"id": "matched-account", "prescriber": {
        "id": "matched-doctor", "name": "Matched Doctor",
    }}}
    client.submit_payload(payload)
    assert json.loads(requests[1][0].data)["customerAccount"] == payload["customerAccount"]

    # Match the working Postman contract: doctor_id is only prescriber.id.
    # A different doctor on the next case must not reuse a global doctor ID.
    for doctor_id in ("Erin_Pender", "Nanette_Tertel"):
        requests.clear()
        responses = iter((FakeResponse({"id": doctor_id}), FakeResponse({}), FakeResponse({"value": []})))
        payload = {"customerAccount": {"prescriber": {
            "id": doctor_id, "name": doctor_id.replace("_", " "),
            "contact": {"displayName": doctor_id.split("_")[0], "email": ""},
        }}, "reference": "case-reference"}
        client.submit_payload(payload)
        sent = json.loads(requests[1][0].data)
        assert sent["customerAccount"] == payload["customerAccount"]
        assert "id" not in sent["customerAccount"]
        assert sent["reference"] == "case-reference"
        assert "patientInfo" not in payload  # caller's saved payload is untouched


def test_submission_status_accepts_common_labtrac_collection_shapes():
    settings = LabtracSettings(
        token_url="https://identity.example/token", api_base_url="https://connect.example/api",
        application_id="application", organisation_id="organisation", unit_id="unit",
        integration_id="integration", client_id="client", client_secret="secret",
        scope="scope", user_id="user", doctor_id="doctor", doctor_name="Doctor",
    )
    responses = iter((
        FakeResponse([{"id": "pending", "isSubmitted": False}]),
        FakeResponse({"items": [{"Id": "submitted", "status": "Submitted"}]}),
        FakeResponse({"data": []}),
    ))
    client = LabtracApiClient(settings, lambda *_args, **_kwargs: next(responses))
    assert client.submission_status("pending", "token") == "pending"
    assert client.submission_status("submitted", "token") == "submitted"
    assert client.submission_status("missing", "token") == "unknown"


def test_rpa_patient_suffix_is_idempotent():
    assert LabtracApiClient.rpa_patient_name("Jane Smith") == "Jane Smith (RPA)"
    assert LabtracApiClient.rpa_patient_name("Jane Smith (RPA)") == "Jane Smith (RPA)"


def test_remote_status_failure_keeps_confirmed_submission():
    from unittest.mock import Mock
    client = LabtracApiClient(settings=Mock())
    client._get_access_token = Mock(return_value='token')
    client._resource_url = lambda resource: resource
    client._set_doctor = Mock()
    client._json_request = Mock(side_effect=[{'id': 'confirmed'}, {}])
    client.submission_status = Mock(side_effect=RuntimeError('status unavailable'))
    response = client.submit_payload({'customerAccount': {'id': 'verified'},
                                      'patientInfo': {'name': 'Source Patient'}})
    assert response['submissionId'] == 'confirmed'
    assert response['remoteStatus'] == 'unknown'
    assert response['caseSubmissionAt']
