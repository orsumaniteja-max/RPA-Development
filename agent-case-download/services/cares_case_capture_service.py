"""Reusable workflow for exporting a CARES case as a Labtrac RxSubmission."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Response

from pages.cares_connect.case_details_page import CaseDetailsPage
from pages.cares_connect.dashboard_page import DashboardPage
from pages.cares_connect.login_page import LoginPage
from services.doctor_validation_service import DoctorValidationService
from services.doctor_catalog_service import DoctorCatalogService
from services.labtrac_api_service import LabtracApiClient
from services.rpa_case_tracking_service import RpaCaseTrackingService


LOGGER = logging.getLogger(__name__)
DEFAULT_SWAGGER_URL = "https://connect.labtrac.com/api/swagger/v3.0/swagger.json"
DEFAULT_REPORTS_ROOT = Path("reports/caresconnect")


@dataclass(frozen=True)
class CaseCaptureResult:
    """Files and case identifier produced by a CARES case capture."""

    case_id: str
    json_file: Path
    text_file: Path
    cares_text_file: Path
    screenshot_file: Path


class CaresCaseCaptureService:
    """Capture, convert, and export CARES cases matching a status."""

    def __init__(
        self,
        swagger_url: str = DEFAULT_SWAGGER_URL,
        reports_root: Path = DEFAULT_REPORTS_ROOT,
        swagger_loader: Callable[[str], dict[str, Any]] | None = None,
        doctor_validator: DoctorValidationService | None = None,
        case_tracker: RpaCaseTrackingService | None = None,
        labtrac_client: LabtracApiClient | None = None,
    ) -> None:
        self.swagger_url = swagger_url
        self.reports_root = reports_root
        self.swagger_loader = swagger_loader or self._load_swagger
        self.doctor_validator = doctor_validator or DoctorValidationService()
        self.case_tracker = case_tracker or RpaCaseTrackingService(
            "cares_connect", self.reports_root / "results"
        )
        self.labtrac_client = labtrac_client

    def capture_first_case(
        self,
        page: Page,
        username: str,
        password: str,
        status: str = "Waiting for designer",
    ) -> CaseCaptureResult:
        """Export the first case returned by CARES advanced search."""
        doctor_catalog = DoctorCatalogService(self.reports_root)
        doctor_catalog.load_and_export()
        captured_responses: list[dict[str, Any]] = []
        page.on("response", self._response_handler(captured_responses))

        login = LoginPage(page)
        dashboard = DashboardPage(page)
        case_details_page = CaseDetailsPage(page)

        login.login(username, password)
        dashboard.click_on_advance_link()
        dashboard.select_status(status)
        dashboard.click_on_advance_button()
        dashboard.open_first_record()

        case_id = case_details_page.get_case_id()
        case_details = case_details_page.get_case_information()
        body_text = dashboard.get_data_app()
        payload = self.build_rx_submission_payload(
            self.get_case_json_response(captured_responses)
        )
        self.apply_cares_clinical_data(
            payload,
            case_id,
            case_details,
            self.get_prescription_note(case_details.get("Note", ""), body_text),
        )
        doctor_catalog.apply(
            payload,
            practice=case_details.get("Laboratory", ""),
            match_name=case_details.get("Dentist", ""),
        )
        self.apply_manufacturing_info(payload, self.extract_manufacturing_items(body_text))
        return self._export_by_case_id(case_details_page, case_id, payload, body_text)

    def capture_all_cases(
        self,
        page: Page,
        username: str,
        password: str,
        status: str | None = None,
        max_cases: int | None = None,
        max_new_cases: int | None = None,
    ) -> list[CaseCaptureResult]:
        """Export every case displayed by the CARES advanced-search result."""
        doctor_catalog = DoctorCatalogService(self.reports_root)
        doctor_catalog.load_and_export()
        captured_responses: list[dict[str, Any]] = []
        page.on("response", self._response_handler(captured_responses))

        login = LoginPage(page)
        dashboard = DashboardPage(page)
        case_details_page = CaseDetailsPage(page)

        login.login(username, password)
        dashboard.click_on_advance_link()
        if status is not None:
            dashboard.select_status(status)
        dashboard.click_on_advance_button()

        results_by_case_id: dict[str, CaseCaptureResult] = {}
        examined = 0
        while max_cases is None or examined < max_cases:
            record_count = dashboard.get_record_count()
            LOGGER.info("Found %s CARES cases on the current results page", record_count)
            page_limit = record_count if max_cases is None else min(record_count, max_cases - examined)
            for index in range(page_limit):
                examined += 1
                # Only responses generated while opening this record may feed its payload.
                captured_responses.clear()
                dashboard.open_record(index)
                case_id = case_details_page.get_case_id()
                if self.case_tracker.is_downloaded(case_id):
                    LOGGER.info("Skipping previously downloaded CARES case %s", case_id)
                    dashboard.return_to_search_results()
                    continue
                result = self._capture_current_case(
                    dashboard, case_details_page, captured_responses, doctor_catalog,
                    case_id=case_id,
                )
                # Repeated rows resolve to one output path and result entry.
                results_by_case_id[result.case_id] = result
                if max_new_cases is not None and len(results_by_case_id) >= max_new_cases:
                    return list(results_by_case_id.values())
                dashboard.return_to_search_results()
            if (max_cases is not None and examined >= max_cases) or not dashboard.has_next_page():
                break
            dashboard.open_next_page()
        return list(results_by_case_id.values())

    def _capture_current_case(
        self,
        dashboard: DashboardPage,
        case_details_page: CaseDetailsPage,
        captured_responses: Sequence[Mapping[str, Any]],
        doctor_catalog: DoctorCatalogService,
        case_id: str | None = None,
    ) -> CaseCaptureResult:
        """Capture and export the currently open case."""
        case_id = case_id or case_details_page.get_case_id()
        case_details = case_details_page.get_case_information()
        body_text = dashboard.get_data_app()
        payload = self.build_rx_submission_payload(
            self.get_case_json_response(captured_responses)
        )
        self.apply_cares_clinical_data(
            payload,
            case_id,
            case_details,
            self.get_prescription_note(case_details.get("Note", ""), body_text),
        )
        doctor_catalog.apply(
            payload,
            practice=case_details.get("Laboratory", ""),
            match_name=case_details.get("Dentist", ""),
        )
        self.apply_manufacturing_info(payload, self.extract_manufacturing_items(body_text))
        return self._export_by_case_id(case_details_page, case_id, payload, body_text)

    @staticmethod
    def _response_handler(
        captured_responses: list[dict[str, Any]],
    ) -> Callable[[Response], None]:
        def handle_response(response: Response) -> None:
            if "json" not in response.headers.get("content-type", "").lower():
                return
            try:
                payload = response.json()
                if isinstance(payload, str):
                    payload = json.loads(payload)
                captured_responses.append({"url": response.url, "payload": payload})
            except (PlaywrightError, ValueError):
                LOGGER.debug("Ignoring non-JSON response from %s", response.url)

        return handle_response

    @staticmethod
    def get_case_json_response(captured_data: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Return the most complete captured RxSubmission-like response."""
        schema_markers = {
            "id", "reference", "customerAccount", "patientInfo", "salesOrders",
            "rxItems", "dateExpected", "providerStatus",
        }
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for index, response in enumerate(captured_data):
            payload = response.get("payload")
            if isinstance(payload, dict):
                candidates.append((len(schema_markers.intersection(payload)), index, payload))
        if not candidates:
            return {}
        score, _, payload = max(candidates, key=lambda item: (item[0], item[1]))
        return payload if score else {}

    def build_rx_submission_payload(self, captured_case_data: Mapping[str, Any]) -> dict[str, Any]:
        """Build only the fields accepted by the RxSubmission request contract.

        CARES responses use the full RxSubmission *response* model.  Expanding its
        Swagger definition exports many read-only and unrelated nested objects.
        The request body intentionally contains only the submission fields.
        """
        patient = captured_case_data.get("patientInfo")
        patient = patient if isinstance(patient, Mapping) else {}
        customer_account = captured_case_data.get("customerAccount")
        customer_account = customer_account if isinstance(customer_account, Mapping) else {}
        prescriber = customer_account.get("prescriber")
        prescriber = prescriber if isinstance(prescriber, Mapping) else {}
        contact = prescriber.get("contact")
        contact = contact if isinstance(contact, Mapping) else {}
        return {
            "patientInfo": {
                "name": patient.get("name") or "",
            },
            "customerAccount": {
                "prescriber": {
                    "name": prescriber.get("name") or "",
                    "contact": {
                        "displayName": contact.get("displayName") or "",
                        "email": contact.get("email") or "",
                    },
                },
            },
            "rxItems": self.compact_rx_items(captured_case_data.get("rxItems")),
            "dateRequested": captured_case_data.get("dateRequested") or "",
            "description": captured_case_data.get("description") or "",
            "attributes": self.compact_attributes(captured_case_data.get("attributes")),
            "fileFolders": self.as_list(captured_case_data.get("fileFolders")),
        }

    @classmethod
    def compact_rx_items(cls, value: Any) -> list[dict[str, Any]]:
        """Keep only request-safe fields from captured prescription items."""
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            teeth = item.get("teeth")
            compact_teeth = []
            if isinstance(teeth, list):
                for tooth in teeth:
                    if isinstance(tooth, Mapping):
                        compact_teeth.append({
                            "toothNumber": tooth.get("toothNumber") or "",
                            "toothNumberingMethod": tooth.get("toothNumberingMethod") or "",
                            "attributes": cls.as_list(tooth.get("attributes")),
                        })
            items.append({
                "name": item.get("name") or "",
                "qty": item.get("qty") or 1,
                "attributes": cls.compact_attributes(item.get("attributes")),
                "teeth": compact_teeth,
                "attachments": cls.as_list(item.get("attachments")),
            })
        return items

    @staticmethod
    def as_list(value: Any) -> list[Any]:
        """Use an empty array for absent optional request collections."""
        return value if isinstance(value, list) else []

    @classmethod
    def compact_attributes(cls, value: Any) -> list[dict[str, Any]]:
        """Exclude response-only metadata from attribute values."""
        return [
            {
                key: attribute[key]
                for key in ("attributeGroupId", "attributeId", "attributeValue")
                if key in attribute
            }
            for attribute in cls.as_list(value)
            if isinstance(attribute, Mapping)
        ]

    @staticmethod
    def _load_swagger(swagger_url: str) -> dict[str, Any]:
        with urlopen(swagger_url, timeout=30) as response:
            return json.load(response)

    @classmethod
    def build_from_schema(
        cls,
        schema: Mapping[str, Any],
        definitions: Mapping[str, Any],
        value: Any = None,
        ref_stack: set[str] | None = None,
    ) -> Any:
        """Recursively populate a Swagger schema with captured/default values."""
        ref_stack = ref_stack if ref_stack is not None else set()
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", maxsplit=1)[-1]
            if name in ref_stack:
                return {}
            ref_stack.add(name)
            try:
                return cls.build_from_schema(definitions[name], definitions, value, ref_stack)
            finally:
                ref_stack.remove(name)
        if "allOf" in schema:
            result: dict[str, Any] = {}
            for child_schema in schema["allOf"]:
                child = cls.build_from_schema(child_schema, definitions, value, ref_stack)
                if isinstance(child, dict):
                    result.update(child)
            return result
        if schema.get("type") == "object" or "properties" in schema:
            source = value if isinstance(value, Mapping) else {}
            return {
                name: cls.build_from_schema(
                    property_schema, definitions, source.get(name), ref_stack
                )
                for name, property_schema in schema.get("properties", {}).items()
            }
        if schema.get("type") == "array":
            items = value if isinstance(value, list) and value else [None]
            return [
                cls.build_from_schema(schema["items"], definitions, item, ref_stack)
                for item in items
            ]
        if value is not None:
            return value
        if schema.get("type") in {"integer", "number"}:
            return 0
        if schema.get("type") == "boolean":
            return False
        return ""

    @staticmethod
    def get_prescription_note(note: str, body_text: str) -> str:
        if note:
            return note
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        for index, line in enumerate(lines[:-1]):
            if line.lower() == "note":
                return lines[index + 1]
        return ""

    @classmethod
    def apply_cares_clinical_data(
        cls,
        payload: dict[str, Any],
        case_id: str,
        details: Mapping[str, str],
        prescription_text: str,
    ) -> None:
        """Map CARES clinical labels to the Labtrac RxSubmission model."""
        dentist = details.get("Dentist", "")
        patient = details.get("Patient", "")
        laboratory = details.get("Laboratory", "")
        submitted_date = cls.to_iso_datetime(details.get("Date", ""))
        due_date = cls.to_iso_datetime(details.get("Due Date", ""))

        del laboratory, due_date  # Not part of the compact request body.
        payload["reference"] = case_id
        payload["dateRequested"] = submitted_date
        payload["description"] = prescription_text
        patient_info = payload["patientInfo"]
        patient_info.pop("id", None)
        patient_info["name"] = patient
        prescriber = payload.setdefault("customerAccount", {}).setdefault("prescriber", {})
        prescriber["name"] = dentist
        contact = prescriber.setdefault("contact", {})
        name_parts = dentist.replace(",", " ").split()
        if name_parts and name_parts[0].lower().rstrip(".") in {"dr", "doctor"}:
            name_parts = name_parts[1:]
        contact["displayName"] = name_parts[0] if name_parts else ""
        contact.setdefault("email", "")

    @staticmethod
    def apply_doctor_validation(payload: dict[str, Any], validation: Any) -> None:
        """Add the matched account ID or retain a non-fatal validation error."""
        prescriber = payload.setdefault("customerAccount", {}).setdefault(
            "prescriber", {}
        )
        if validation.doctor is not None:
            prescriber["id"] = validation.doctor.account_id
            if validation.doctor.email:
                prescriber.setdefault("contact", {})["email"] = validation.doctor.email
            return
        prescriber["id"] = ""
        payload.setdefault("validationErrors", []).append(validation.error)

    @staticmethod
    def set_contact_name(contact: dict[str, Any], full_name: str) -> None:
        parts = full_name.replace(",", " ").split()
        contact["displayName"] = full_name
        contact["title"] = (
            parts[0]
            if parts and parts[0].lower().rstrip(".") in {"dr", "doctor"}
            else ""
        )
        name_parts = parts[1:] if contact["title"] else parts
        contact["firstName"] = name_parts[0] if name_parts else ""
        contact["middleName"] = " ".join(name_parts[1:-1]) if len(name_parts) > 2 else ""
        contact["lastName"] = name_parts[-1] if len(name_parts) > 1 else ""

    @staticmethod
    def to_iso_datetime(value: str) -> str:
        try:
            return datetime.strptime(value, "%d/%m/%Y").strftime("%Y-%m-%dT00:00:00Z")
        except (TypeError, ValueError):
            return value or ""

    @staticmethod
    def extract_manufacturing_items(body_text: str) -> list[dict[str, str]]:
        """Extract every CARES item, material, and tooth block."""
        lines = [line.strip() for line in body_text.splitlines() if line.strip()]
        items: list[dict[str, str]] = []
        current_item: dict[str, str] | None = None
        for line in lines:
            item_match = re.fullmatch(
                r"Item\s+#(?P<number>\d+)\s*(?::\s*(?P<material>.*))?",
                line,
                re.IGNORECASE,
            )
            if item_match:
                if current_item is not None:
                    items.append(current_item)
                current_item = {
                    "number": item_match.group("number"),
                    "material": (item_match.group("material") or "").strip(),
                    "tooth": "",
                }
                continue
            tooth_match = re.fullmatch(r"Tooth\s+(?P<number>\S+)", line, re.IGNORECASE)
            if current_item is not None and tooth_match:
                current_item["tooth"] = tooth_match.group("number")
                items.append(current_item)
                current_item = None
        if current_item is not None:
            items.append(current_item)
        return items

    @staticmethod
    def apply_manufacturing_info(
        payload: dict[str, Any], items: Sequence[Mapping[str, str]]
    ) -> None:
        if not items:
            return
        rx_items = []
        for item in items:
            rx_items.append({
                "name": item["material"],
                "qty": 1,
                "attributes": CaresCaseCaptureService.build_item_attributes(
                    item["material"], payload.get("description", "")
                ),
                "teeth": [{
                    "toothNumber": item["tooth"],
                    "toothNumberingMethod": "Universal",
                    "attributes": [],
                }],
                "attachments": [],
            })
        payload["rxItems"] = rx_items

    @staticmethod
    def build_item_attributes(material: str, prescription_text: str) -> list[dict[str, str | None]]:
        """Create the standard request attributes from data available in CARES.

        CARES exposes material and, when specified, Vita shade in the prescription.
        It does not expose implant support or workflow on this case screen, so those
        attribute values must remain explicit JSON nulls instead of empty strings.
        """
        shade_match = re.search(
            r"(?:vita\s+)?shade\s*:\s*([^\n,;]+)", prescription_text, re.IGNORECASE
        )
        shade = shade_match.group(1).strip() if shade_match else None
        return [
            {
                "attributeGroupId": "material",
                "attributeId": "material",
                "attributeValue": material or None,
            },
            {
                "attributeGroupId": "implant",
                "attributeId": "implantSupported",
                "attributeValue": None,
            },
            {
                "attributeGroupId": "shade",
                "attributeId": "shade",
                "attributeValue": shade,
            },
            {
                "attributeGroupId": "workflow",
                "attributeId": "workflow",
                "attributeValue": None,
            },
        ]

    @classmethod
    def nullify_empty_blocks(cls, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {key: cls.nullify_empty_blocks(item) for key, item in value.items()}
            return (
                None if all(cls.is_empty_value(item) for item in cleaned.values()) else cleaned
            )
        if isinstance(value, list):
            cleaned = [cls.nullify_empty_blocks(item) for item in value]
            return (
                None
                if not cleaned or all(cls.is_empty_value(item) for item in cleaned)
                else cleaned
            )
        return None if value == "" else value

    @staticmethod
    def is_empty_value(value: Any) -> bool:
        return value is None or value == 0 or value is False

    def _export(
        self,
        case_page: CaseDetailsPage,
        case_id: str,
        payload: dict[str, Any],
        body_text: str,
    ) -> CaseCaptureResult:
        output_file = self.reports_root / case_id / "case_details.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
        text_file = output_file.with_suffix(".txt")
        with text_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
        cares_text_file = output_file.with_name("case_details_cares.txt")
        cares_text_file.write_text(f"{body_text}\n", encoding="utf-8")
        screenshot_file = output_file.with_name("case_details.png")
        case_page.take_screenshot(str(screenshot_file))
        LOGGER.info("Exported CARES case %s to %s", case_id, output_file.parent)
        return CaseCaptureResult(case_id, output_file, text_file, cares_text_file, screenshot_file)

    def _export_by_case_id(
        self,
        case_page: CaseDetailsPage,
        case_id: str,
        payload: dict[str, Any],
        body_text: str,
    ) -> CaseCaptureResult:
        """Write artifacts named by case ID, replacing an older case capture."""
        results_folder = self.reports_root / "results"
        results_folder.mkdir(parents=True, exist_ok=True)
        stem = re.sub(r'[<>:"/\\|?*]', "_", case_id).strip().rstrip(".")
        if not stem:
            raise ValueError("CARES returned an empty case ID")
        json_file = results_folder / f"{stem}.json"
        with json_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
        text_file = results_folder / f"{stem}.txt"
        with text_file.open("w", encoding="utf-8") as file:
            json.dump(payload, file, indent=4, ensure_ascii=False)
        cares_text_file = results_folder / f"{stem}_cares.txt"
        cares_text_file.write_text(f"{body_text}\n", encoding="utf-8")
        screenshot_file = results_folder / f"{stem}.png"
        case_page.take_screenshot(str(screenshot_file))
        LOGGER.info("Exported CARES case %s to %s", case_id, json_file)
        self.case_tracker.record_download(case_id, self.case_tracker.doctor_name(payload))
        return CaseCaptureResult(
            case_id, json_file, text_file, cares_text_file, screenshot_file
        )
