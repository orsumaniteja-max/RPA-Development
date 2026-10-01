"""Load the Azure SQL doctor catalog once and enrich portal case payloads."""

from __future__ import annotations

import csv
import logging
import os
import re
from pathlib import Path
from typing import Any

from services.doctor_validation_service import DoctorRecord
from services.account_identifier_service import ensure_account_identifier
from services.doctor_match_service import (
    DoctorIdentificationError,
    DoctorMatch,
    DoctorMatchService,
    GraphDoctorMatchNotifier,
)


class DoctorCatalogService:
    CSV_NAME = "doctors.csv"

    def __init__(
        self, reports_root: Path, matcher: DoctorMatchService | None = None
    ) -> None:
        self.results_root = Path(reports_root) / "results"
        self.records: list[DoctorRecord] = []
        alerts_enabled = os.getenv("DOCTOR_MATCH_ALERTS_ENABLED", "").casefold() in {
            "1", "true", "yes", "on",
        }
        self.matcher = matcher or DoctorMatchService(
            notifier=GraphDoctorMatchNotifier() if alerts_enabled else None
        )
        self.last_match_error: str | None = None
        self.last_match: DoctorMatch | None = None

    def load_and_export(self) -> list[DoctorRecord]:
        try:
            import pymssql
        except ImportError as error:
            raise RuntimeError("Install pymssql to export the doctor catalog") from error

        settings = {
            "server": os.getenv("AZURE_SQL_SERVER"),
            "database": os.getenv("AZURE_SQL_DATABASE"),
            "user": os.getenv("AZURE_SQL_USERNAME"),
            "password": os.getenv("AZURE_SQL_PASSWORD"),
        }
        missing = [name for name, value in settings.items() if not value]
        if missing:
            raise RuntimeError(
                "Missing Azure SQL settings: " + ", ".join(missing)
            )

        connection = pymssql.connect(
            **settings, login_timeout=15, timeout=30
        )
        try:
            cursor = connection.cursor(as_dict=True)
            # SELECT * keeps this compatible with database deployments where
            # address fields have been added under slightly different names.
            cursor.execute("SELECT * FROM dbo.Doctor ORDER BY Id")
            self.records = [
                DoctorRecord(
                    doctor_id=self._field(row, "Id", "DoctorId"),
                    account_id=self._field(row, "AccountId"),
                    name=(
                        self._field(row, "AccountName")
                        or self._field(row, "DoctorName")
                        or self._field(row, "Name")
                    ),
                    practice=self._field(row, "PracticeName"),
                    email=self._field(row, "Email", "EmailAddress"),
                    phone=self._field(row, "Telephone", "Phone", "PhoneNumber"),
                    address=self._address(row),
                    zip_code=self._field(
                        row, "ZipCode", "Zip", "PostalCode", "Address5"
                    ),
                )
                for row in cursor.fetchall()
            ]
        finally:
            connection.close()

        self.results_root.mkdir(parents=True, exist_ok=True)
        csv_file = self.results_root / self.CSV_NAME
        with csv_file.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=[
                    "Id", "AccountId", "DoctorName", "PracticeName", "Address",
                    "ZipCode", "Phone", "Email",
                ],
            )
            writer.writeheader()
            writer.writerows({
                "Id": record.doctor_id,
                "AccountId": record.account_id,
                "DoctorName": record.name,
                "PracticeName": record.practice,
                "Address": record.address,
                "ZipCode": record.zip_code,
                "Phone": record.phone,
                "Email": record.email,
            } for record in self.records)
        return self.records

    def apply(
        self, payload: dict[str, Any], practice: str = "", match_name: str = ""
    ) -> DoctorRecord | None:
        if not isinstance(payload.get("customerAccount"), dict):
            payload["customerAccount"] = {}
        if not isinstance(payload["customerAccount"].get("prescriber"), dict):
            payload["customerAccount"]["prescriber"] = {}
        prescriber = payload.setdefault("customerAccount", {}).setdefault(
            "prescriber", {}
        )
        if not isinstance(prescriber.get("contact"), dict):
            prescriber["contact"] = {}
        contact = prescriber["contact"]
        doctor_information = payload.get("doctorInformation") or {}
        if not isinstance(doctor_information, dict):
            doctor_information = {}
        scraped = {
            "name": match_name or prescriber.get("name", ""),
            "email": contact.get("email", ""),
            "phone": contact.get("phone", "") or doctor_information.get("phone", ""),
            "address": doctor_information.get("address", ""),
            "practice": practice,
        }
        logger = logging.getLogger(__name__)
        logger.info("Doctor matching attempted using common strict/fuzzy matcher")
        try:
            match = self.matcher.identify_or_notify(scraped, self.records)
            selected = next(record for record in self.records if (
                match.doctor.doctor_id and record.doctor_id == match.doctor.doctor_id
            ) or (
                not match.doctor.doctor_id
                and record.account_id == match.doctor.account_id
            ))
            self.last_match_error = None
            self.last_match = match
            logger.info("Doctor matching successful (%s)", match.method)
        except DoctorIdentificationError as error:
            selected = None
            self.last_match_error = str(error)
            self.last_match = None
            logger.info("Doctor matching unsuccessful; continuing case generation")
        # Discard any previous doctor UUID before resolving the account ID.
        prescriber.pop("id", None)
        if selected and selected.email and not contact.get("email"):
            contact["email"] = selected.email
        payload["customerAccount"]["id"] = selected.account_id if selected else ""
        if selected and selected.account_id:
            logger.info("Actual account identifier found (masked)")
        else:
            ensure_account_identifier(payload, self.results_root.parent.name)
        # Captured JSON stores the account identity only under prescriber.
        prescriber["id"] = payload["customerAccount"].pop("id")
        return selected

    @staticmethod
    def _normalise(value: str) -> str:
        value = re.sub(r"\([^)]*\)\s*$", "", value or "")
        value = re.sub(r"^(?:dr|doctor)\.?\s+", "", value, flags=re.IGNORECASE)
        return " ".join(value.casefold().split())

    @staticmethod
    def _field(row: dict[str, Any], *names: str) -> str:
        keys = {str(key).casefold(): key for key in row}
        for name in names:
            key = keys.get(name.casefold())
            if key is not None and row.get(key) is not None:
                return str(row[key]).strip()
        return ""

    @classmethod
    def _address(cls, row: dict[str, Any]) -> str:
        direct = cls._field(row, "Address", "DoctorAddress")
        if direct:
            return direct
        values = [
            cls._field(row, "Address1"),
            cls._field(row, "Address2"),
            cls._field(row, "Address3", "City"),
            cls._field(row, "Address4", "State"),
            cls._field(row, "Address5", "ZipCode", "PostalCode"),
        ]
        return ", ".join(value for value in values if value)
