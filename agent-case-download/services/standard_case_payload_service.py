"""Normalize portal-specific case data to the Labtrac RxSubmission contract."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping


class StandardCasePayloadService:
    """Build the same compact RxSubmission JSON shape for every portal."""

    PATIENT_KEYS = ("Patient", "Patient Name", "patient", "patientName")
    ID_KEYS = ("Case ID", "Caseid", "Fullcaseid", "Order Number", "id")
    DOCTOR_KEYS = ("Doctor", "Dentist", "Prescriber", "Doctor Name", "doctor", "dentist")
    DOCTOR_EMAIL_KEYS = (
        "Doctor Email", "Dentist Email", "Prescriber Email", "doctorEmail",
        "dentistEmail", "prescriberEmail", "email",
    )
    DOCTOR_ADDRESS_KEYS = (
        "Doctor Address", "Dentist Address", "Prescriber Address", "doctorAddress",
        "dentistAddress", "prescriberAddress", "address",
    )
    DATE_KEYS = (
        "Date", "Created", "Upload Time", "Submission date", "dateRequested",
    )
    DESCRIPTION_KEYS = ("Note", "Remark", "Details", "description")
    MATERIAL_KEYS = ("Material", "Case Type", "material", "name")
    TOOTH_KEYS = ("Tooth", "Tooth Number", "tooth", "toothNumber")

    @classmethod
    def build(cls, source: Mapping[str, Any]) -> dict[str, Any]:
        details = cls._flatten(source)
        case_id = cls._first(details, cls.ID_KEYS)
        patient = cls._first(details, cls.PATIENT_KEYS)
        doctor = cls._first(details, cls.DOCTOR_KEYS)
        doctor_email = cls._first(details, cls.DOCTOR_EMAIL_KEYS)
        description = cls._first(details, cls.DESCRIPTION_KEYS)
        material = cls._first(details, cls.MATERIAL_KEYS)
        tooth = cls._first(details, cls.TOOTH_KEYS)

        if not tooth:
            tooth = cls._extract_tooth(description)
        if not material:
            material = cls._extract_material(description)

        rx_items = []
        if material or tooth:
            rx_items.append({
                "name": material,
                "qty": 1,
                "attributes": cls._item_attributes(material, description),
                "teeth": ([{
                    "toothNumber": tooth,
                    "toothNumberingMethod": "Universal",
                    "attributes": [],
                }] if tooth else []),
                "attachments": [],
            })

        return {
            "reference": case_id,
            "patientInfo": {"id": case_id, "name": patient},
            "customerAccount": {
                "prescriber": {
                    "name": doctor,
                    "contact": {
                        "displayName": cls._display_name(doctor),
                        "email": doctor_email,
                    },
                },
            },
            "rxItems": rx_items,
            "dateRequested": cls._to_iso_datetime(cls._first(details, cls.DATE_KEYS)),
            "description": description,
            "attributes": [],
            "fileFolders": [],
        }

    @staticmethod
    def _display_name(full_name: str) -> str:
        """Return the prescriber's familiar name for the contact block."""
        parts = full_name.replace(",", " ").split()
        if parts and parts[0].lower().rstrip(".") in {"dr", "doctor"}:
            parts = parts[1:]
        return parts[0] if parts else ""

    @staticmethod
    def _flatten(source: Mapping[str, Any]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, value in source.items():
            if isinstance(value, Mapping):
                flattened.update(StandardCasePayloadService._flatten(value))
            else:
                flattened[key] = value
        return flattened

    @staticmethod
    def _first(source: Mapping[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _extract_tooth(text: str) -> str:
        match = re.search(r"(?:tooth\s*|#)(\d{1,2})\b", text, re.IGNORECASE)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_material(text: str) -> str:
        match = re.search(
            r"#\d{1,2}\s+([^\n,;]+?)(?:\s+(?:crown|bridge|implant|veneer))?\s*$",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        return match.group(1).strip() if match else ""

    @staticmethod
    def _item_attributes(material: str, description: str) -> list[dict[str, Any]]:
        shade_match = re.search(
            r"(?:vita\s+)?shade\s*:\s*([^\n,;]+)", description, re.IGNORECASE
        )
        shade = shade_match.group(1).strip() if shade_match else None
        return [
            {"attributeGroupId": "material", "attributeId": "material", "attributeValue": material or None},
            {"attributeGroupId": "implant", "attributeId": "implantSupported", "attributeValue": None},
            {"attributeGroupId": "shade", "attributeId": "shade", "attributeValue": shade},
            {"attributeGroupId": "workflow", "attributeId": "workflow", "attributeValue": None},
        ]

    @staticmethod
    def _to_iso_datetime(value: str) -> str:
        if not value:
            return ""
        for date_format in ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, date_format).strftime("%Y-%m-%dT00:00:00Z")
            except ValueError:
                continue
        return value
