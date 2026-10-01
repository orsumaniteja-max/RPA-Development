"""Non-test validation executed inside each application's smoke workflow."""

from __future__ import annotations

import csv
import json
from pathlib import Path


STANDARD_KEYS = {
    "patientInfo",
    "customerAccount",
    "rxItems",
    "dateRequested",
    "description",
    "attributes",
    "fileFolders",
}


def validate_application_results(application_report_root: Path) -> None:
    """Validate outputs without creating an additional pytest report row."""
    results_root = Path(application_report_root) / "results"
    json_files = sorted(results_root.glob("*.json"))
    if not json_files:
        # A capture run may legitimately produce nothing when all displayed
        # cases are already present in persistent RPA tracking. The individual
        # capture test verifies every newly returned result before this shared
        # validator is called.
        return

    doctors_csv = results_root / "doctors.csv"
    if not doctors_csv.is_file():
        raise AssertionError(f"Doctor catalog is missing: {doctors_csv}")
    with doctors_csv.open(encoding="utf-8-sig", newline="") as stream:
        doctor_rows = list(csv.DictReader(stream))
    if not doctor_rows:
        raise AssertionError(f"Doctor catalog is empty: {doctors_csv}")
    expected_columns = {
        "Id", "AccountId", "DoctorName", "PracticeName", "Address",
        "ZipCode", "Phone", "Email",
    }
    if set(doctor_rows[0]) != expected_columns:
        raise AssertionError(
            f"Unexpected doctor catalog columns in {doctors_csv}: "
            f"{set(doctor_rows[0])}"
        )

    for json_file in json_files:
        payload = json.loads(json_file.read_text(encoding="utf-8"))
        missing = STANDARD_KEYS.difference(payload)
        if missing:
            raise AssertionError(f"{json_file} is missing fields: {sorted(missing)}")
        if "id" in payload["patientInfo"]:
            raise AssertionError(f"Patient ID must not be present in {json_file}")
        prescriber = payload["customerAccount"]["prescriber"]
        missing_prescriber = {"name", "contact", "id"}.difference(prescriber)
        if missing_prescriber:
            raise AssertionError(
                f"{json_file} is missing prescriber fields: {sorted(missing_prescriber)}"
            )
        missing_contact = {"displayName", "email"}.difference(prescriber["contact"])
        if missing_contact:
            raise AssertionError(
                f"{json_file} is missing contact fields: {sorted(missing_contact)}"
            )
