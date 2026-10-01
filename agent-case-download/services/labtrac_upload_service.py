"""Sequential upload of persistent results with durable duplicate prevention."""

import json
import logging
from pathlib import Path

from services.labtrac_api_service import LabtracApiClient
from utilities.config_reader import ConfigReader


APPLICATIONS = (
    "cares_connect", "ori_portal", "io_scanner", "carestream", "ddx", "axs_straumann",
)


def select_applications(value):
    name = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"caresconnect": "cares_connect", "oriportal": "ori_portal",
               "ioscanner": "io_scanner"}
    name = aliases.get(name, name)
    if name == "all":
        return APPLICATIONS
    if name not in APPLICATIONS:
        raise ValueError("application must be all or one of: " + ", ".join(APPLICATIONS))
    return (name,)


def record_limit(value):
    if isinstance(value, str) and value.strip().lower() == "all":
        return None
    if isinstance(value, str) and value.strip().lower() in {"one", "one record"}:
        return 1
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError("records must be a positive integer or all")
    return int(value)


class LabtracUploadService:
    def __init__(self, project_root=None, client=None, account_lookup=None, sql_tracker=None):
        self.root = Path(project_root or ConfigReader.PROJECT_ROOT)
        self.client = client
        from services.labtrac_account_lookup_service import LabtracAccountLookupService
        from services.rpa_sql_tracking_service import RpaSqlTrackingService
        self.account_lookup = account_lookup or LabtracAccountLookupService()
        self.sql_tracker = sql_tracker or RpaSqlTrackingService()
        from services.upload_history_service import UploadHistoryService
        self.history = None
        self.initialization_error = None
        try:
            self.history = UploadHistoryService(self.root)
        except Exception as error:
            self.initialization_error = f"{type(error).__name__}: {error}"
        self.sheet = self.root / "reports/labtrac/upload_history.csv"

    @staticmethod
    def validate_payload(payload):
        """Require case identity and clinical content before claiming or submitting."""
        if not isinstance(payload, dict):
            raise ValueError("Case payload must be an object")
        def required_text(value, field):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Incomplete case: {field} is required")
        required_text(payload.get("reference"), "reference")
        patient = payload.get("patientInfo")
        if not isinstance(patient, dict):
            raise ValueError("Incomplete case: patientInfo must be an object")
        required_text(patient.get("name"), "patientInfo.name")
        account = payload.get("customerAccount")
        if not isinstance(account, dict) or not isinstance(account.get("prescriber"), dict):
            raise ValueError("Incomplete case: prescriber must be an object")
        prescriber = account["prescriber"]
        required_text(prescriber.get("name"), "prescriber.name")
        if prescriber.get("contact") is not None and not isinstance(prescriber["contact"], dict):
            raise ValueError("Invalid prescriber contact")
        items = payload.get("rxItems")
        if items is not None and (not isinstance(items, list) or
                                  any(not isinstance(item, dict) for item in items)):
            raise ValueError("Invalid rxItems")
        description = payload.get("description")
        has_description = isinstance(description, str) and bool(description.strip())
        has_items = isinstance(items, list) and any(
            isinstance(item.get("name"), str) and item["name"].strip() for item in items)
        if not has_description and not has_items:
            raise ValueError("Incomplete case: prescription description or named rxItems required")

    def upload(self, applications, limit=None, eligible_cases=None):
        outcomes = []
        attempted = 0
        if self.history is None:
            return [{"application": app, "case": "", "status": "needs_review",
                     "error": "Upload history unavailable; no cases submitted: " + self.initialization_error}
                    for app in applications]
        for application in applications:
            try:
                folder = ConfigReader.get_config(application).get("report_folder", application)
                paths = sorted((self.root / "reports" / folder / "results").glob("*.json"))
            except Exception as error:
                outcomes.append(self._error(application, "", error))
                continue
            for path in paths:
                if eligible_cases is not None and (application, path.stem) not in eligible_cases:
                    continue
                if path.stem.endswith("_labtrac"):
                    continue
                try:
                    previous = self.history.status(application, path.stem)
                    if previous:
                        if previous == "uploaded":
                            warning = self._sync_submission(application, path.stem)
                            if warning:
                                outcomes.append(warning)
                        else:
                            outcomes.append({"application": application, "case": path.stem,
                                             "status": "needs_review"})
                        continue
                    receipt = path.with_name(path.stem + "_labtrac.json")
                    if receipt.exists():
                        legacy = json.loads(receipt.read_text(encoding="utf-8-sig"))
                        if not isinstance(legacy, dict) or not legacy.get("submissionId"):
                            raise ValueError("Incomplete legacy receipt")
                        self.save(application, path.stem, "uploaded", legacy)
                        continue
                    if limit is not None and attempted >= limit:
                        return outcomes
                    payload = json.loads(path.read_text(encoding="utf-8-sig"))
                    self.validate_payload(payload)
                    self._apply_verified_account_id(payload)
                    client = self.client or LabtracApiClient()
                    record_info = {
                        **self.history.case_details(payload, path),
                        "SubmittedPatient": LabtracApiClient.rpa_patient_name(payload["patientInfo"]["name"]),
                        "MetadataSource": "Captured at upload attempt",
                        "UploadAttemptedAtUTC": self.history._now(),
                    }
                    if not self.history.claim(application, path.stem, record_info):
                        continue
                    attempted += 1
                    try:
                        response = client.submit_payload(payload)
                        if not isinstance(response, dict) or not response.get("submissionId"):
                            raise ValueError("Labtrac response missing submissionId")
                    except Exception as error:
                        outcome = self._error(application, path.stem, error)
                        try:
                            self.save(application, path.stem, "needs_review", {"error": outcome["error"]})
                        except Exception as save_error:
                            outcome["historyError"] = str(save_error)
                        outcomes.append(outcome)
                        continue
                    # Durable SQL retry information: a DB outage must never resubmit the case.
                    response = dict(response, caseSubmissionAt=response.get("caseSubmissionAt") or self.history._now(),
                                    prescriptionId=payload["reference"], sqlTrackingPending=True)
                    outcome = {"application": application, "case": path.stem, "status": "uploaded",
                               "submissionId": response["submissionId"],
                               "remoteStatus": response.get("remoteStatus", "unknown")}
                    try:
                        self.save(application, path.stem, "uploaded", response)
                    except Exception as error:
                        outcome["status"] = "needs_review"
                        outcome["error"] = "Labtrac submitted, but history save failed: " + str(error)
                        # The earlier claim still blocks automatic re-creation.
                    warning = self._sync_submission(application, path.stem, response)
                    if warning:
                        outcome["sqlTrackingError"] = warning["error"]
                    outcomes.append(outcome)
                except Exception as error:
                    outcomes.append(self._error(application, path.stem, error))
        return outcomes

    @staticmethod
    def _error(application, case_id, error):
        logging.getLogger(__name__).warning("Case skipped or held for review (%s)", type(error).__name__)
        return {"application": application, "case": case_id, "status": "needs_review",
                "error": f"{type(error).__name__}: {error}"}

    def _sync_submission(self, application, case_id, response=None):
        try:
            if response is None:
                response = self.history.submission_tracking(application, case_id)
            if not response or not response.get("sqlTrackingPending"):
                return None
            self.sql_tracker.record_submission(application, response["prescriptionId"], response["caseSubmissionAt"])
            self.history.mark_submission_synced(application, case_id)
        except Exception as error:
            return self._error(application, case_id, error)
        return None

    def save(self, application, case_id, status, response):
        self.history.save(application, case_id, status, response)

    def _apply_verified_account_id(self, payload):
        """Replace captured fallback IDs with the matched ROE AccountId."""
        if self.account_lookup is None:
            return
        account = payload.get("customerAccount") or {}
        prescriber = account.get("prescriber") if isinstance(account, dict) else None
        if not isinstance(prescriber, dict):
            raise ValueError("Case has no prescriber for AccountId lookup")
        account_id = self.account_lookup.resolve(str(prescriber.get("name") or ""))
        if not isinstance(account_id, str) or not account_id.strip():
            raise LookupError("No unique verified AccountId; case skipped")
        account["id"] = account_id
        prescriber["id"] = account_id
