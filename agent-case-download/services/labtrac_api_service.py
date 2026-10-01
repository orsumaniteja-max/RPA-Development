"""Authenticated Labtrac Connect API client for Rx submissions."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from services.account_identifier_service import ensure_account_identifier

LOGGER = logging.getLogger(__name__)


DEFAULT_TOKEN_URL = "https://identity.dentalrx.online/connect/token"
DEFAULT_API_BASE_URL = "https://connect.labtrac.com/api/v3.0"
DEFAULT_APPLICATION_ID = "468a29c6-8094-4b56-a503-7c5310e4f116"
DEFAULT_ORGANISATION_ID = "a1d8c745-e7ae-4b14-84e2-f96c48833fda"
DEFAULT_UNIT_ID = "8c11a6b4-12cb-4476-ba68-75203a275b87"
DEFAULT_INTEGRATION_ID = "e32309cf-c3cf-4655-a9aa-5a1be70f7bea"
DEFAULT_USER_ID = "7d509fe4-430e-49b0-be05-53ee42ace01f"


class LabtracApiError(RuntimeError):
    """Raised when Labtrac rejects or cannot process an API request."""


@dataclass(frozen=True)
class LabtracSettings:
    token_url: str
    api_base_url: str
    application_id: str
    organisation_id: str
    unit_id: str
    integration_id: str
    client_id: str
    client_secret: str
    scope: str
    user_id: str
    doctor_id: str
    doctor_name: str

    @classmethod
    def from_environment(cls) -> "LabtracSettings":
        client_secret = os.getenv("LABTRAC_CLIENT_SECRET", "")
        if not client_secret:
            raise LabtracApiError("Missing LABTRAC_CLIENT_SECRET")
        return cls(
            token_url=os.getenv("LABTRAC_TOKEN_URL", DEFAULT_TOKEN_URL),
            api_base_url=os.getenv("LABTRAC_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/"),
            application_id=os.getenv("LABTRAC_APPLICATION_ID", DEFAULT_APPLICATION_ID),
            organisation_id=os.getenv("LABTRAC_ORGANISATION_ID", DEFAULT_ORGANISATION_ID),
            unit_id=os.getenv("LABTRAC_UNIT_ID", DEFAULT_UNIT_ID),
            integration_id=os.getenv("LABTRAC_INTEGRATION_ID", DEFAULT_INTEGRATION_ID),
            client_id=os.getenv("LABTRAC_CLIENT_ID", "connect-veltris"),
            client_secret=client_secret,
            scope=os.getenv("LABTRAC_SCOPE", "connect.data.reader connect.data.writer"),
            user_id=os.getenv("LABTRAC_USER_ID", DEFAULT_USER_ID),
            doctor_id=os.getenv("LABTRAC_DOCTOR_ID", DEFAULT_USER_ID),
            doctor_name=os.getenv("LABTRAC_DOCTOR_NAME", "Vitaly"),
        )


class LabtracApiClient:
    """Create and submit RxSubmission records in Labtrac Connect."""

    def __init__(
        self,
        settings: LabtracSettings | None = None,
        opener: Callable[..., object] = urlopen,
    ) -> None:
        self.settings = settings or LabtracSettings.from_environment()
        self.opener = opener

    def check_authentication(self) -> None:
        """Verify configured client credentials without creating a submission."""
        self._get_access_token()

    @staticmethod
    def rpa_patient_name(name) -> str:
        name = str(name or "").strip()
        return name if name.upper().endswith("(RPA)") else f"{name} (RPA)".strip()

    def submit_payload(self, payload: Mapping[str, object]) -> dict[str, object]:
        submission_payload = json.loads(json.dumps(payload))
        patient = submission_payload.setdefault("patientInfo", {})
        if not isinstance(patient, dict):
            raise ValueError("patientInfo must be an object")
        patient["name"] = self.rpa_patient_name(patient.get("name"))
        # Postman supplies doctor_id under prescriber.id. Do not promote it to
        # customerAccount.id: that is a separate account lookup in Labtrac.
        ensure_account_identifier(submission_payload)
        submission_payload.setdefault("isSubmitted", False)
        self._set_doctor(submission_payload)
        LOGGER.info("Rx case creation and submission attempted")
        token = self._get_access_token()
        created = self._json_request(
            "POST",
            self._resource_url("RxSubmissions"),
            token,
            body=submission_payload,
        )
        submission_id = created.get("id")
        if not submission_id:
            raise LabtracApiError("Labtrac RxSubmissions response did not contain an id")
        submitted = self._json_request(
            "POST",
            self._resource_url(f"RxSubmissions/{submission_id}/submit"),
            token,
        )
        from datetime import datetime, timezone
        submission_time = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        try:
            remote_status = self.submission_status(submission_id, token)
        except Exception:
            LOGGER.warning("Submission succeeded; remote status lookup unavailable")
            remote_status = "unknown"
        LOGGER.info("Rx case submission successful")
        return {
            "submissionId": submission_id,
            "created": created,
            "submitted": submitted,
            "remoteStatus": remote_status,
            "caseSubmissionAt": submission_time,
        }

    def submission_status(self, submission_id: str, token: str | None = None) -> str:
        """Read the RxSubmissions collection and return the remote workflow state.

        The collection endpoint is used because it is the endpoint supplied by
        the Labtrac integration. Unknown is a valid result while the service is
        still indexing a newly submitted case.
        """
        response = self._json_request(
            "GET", self._resource_url("RxSubmissions"), token or self._get_access_token()
        )
        for record in self._records(response):
            if str(record.get("id") or record.get("Id") or "") == str(submission_id):
                return self._workflow_status(record)
        return "unknown"

    def submit_json_file(self, json_file: str) -> dict[str, object]:
        with open(json_file, encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, Mapping):
            raise LabtracApiError(f"Expected a JSON object in {json_file}")
        return self.submit_payload(payload)

    def _get_access_token(self) -> str:
        form = urlencode({
            "grant_type": "client_credentials",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "scope": self.settings.scope,
        }).encode("utf-8")
        request = Request(
            self.settings.token_url,
            data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        response = self._open(request)
        token = response.get("access_token") if isinstance(response, Mapping) else None
        if not token:
            raise LabtracApiError("Labtrac token response did not contain access_token")
        return str(token)

    def _json_request(
        self,
        method: str,
        url: str,
        token: str,
        body: Mapping[str, object] | None = None,
    ) -> object:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            url,
            data=data,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Labtrac-UserId": self.settings.user_id,
            },
            method=method,
        )
        return self._open(request)

    def _open(self, request: Request) -> object:
        try:
            with self.opener(request, timeout=30) as response:
                raw = response.read()
        except HTTPError as error:
            LOGGER.error("Rx API request failed (HTTP %s)", error.code)
            detail = error.read().decode("utf-8", errors="replace")
            # Identify the failed phase without logging request headers or payloads.
            phase = ("authentication" if request.full_url == self.settings.token_url
                     else "submission" if request.full_url.endswith("/submit")
                     else "creation")
            for secret in (self.settings.client_secret, request.get_header("Authorization")):
                if secret:
                    detail = detail.replace(secret, "[REDACTED]")
            raise LabtracApiError(
                f"Labtrac request failed with HTTP {error.code} during {phase}: {detail}"
            ) from error
        except OSError as error:
            LOGGER.error("Rx API request failed (transport error)")
            raise LabtracApiError(f"Labtrac request failed: {error}") from error
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LabtracApiError("Labtrac returned an invalid JSON response") from error
        return parsed

    @staticmethod
    def _records(response: object) -> list[Mapping[str, object]]:
        if isinstance(response, list):
            records = response
        elif isinstance(response, Mapping):
            records = next((response.get(key) for key in ("value", "items", "data", "results")
                            if isinstance(response.get(key), list)), [])
        else:
            records = []
        return [record for record in records if isinstance(record, Mapping)]

    @staticmethod
    def _workflow_status(record: Mapping[str, object]) -> str:
        status = record.get("status") or record.get("Status") or record.get("state")
        if status:
            return str(status).strip().lower()
        if record.get("isSubmitted") is True or record.get("submitted") is True:
            return "submitted"
        return "pending"

    def _resource_url(self, resource: str) -> str:
        settings = self.settings
        return (
            f"{settings.api_base_url}/{settings.application_id}/orgs/"
            f"{settings.organisation_id}/units/{settings.unit_id}/integrations/"
            f"{settings.integration_id}/{resource}"
        )

    def _set_doctor(self, payload: dict[str, object]) -> None:
        customer_account = payload.setdefault("customerAccount", {})
        if not isinstance(customer_account, dict):
            customer_account = {}
            payload["customerAccount"] = customer_account
        prescriber = customer_account.setdefault("prescriber", {})
        if not isinstance(prescriber, dict):
            prescriber = {}
            customer_account["prescriber"] = prescriber
        prescriber["id"] = prescriber.get("id") or customer_account["id"]
        prescriber["name"] = prescriber.get("name") or self.settings.doctor_name
