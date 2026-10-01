"""Validate CARES dentist/practice data against the customer portal database."""

from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class DoctorRecord:
    account_id: str
    name: str
    practice: str
    email: str
    doctor_id: str = ""
    phone: str = ""
    address: str = ""
    zip_code: str = ""


@dataclass(frozen=True)
class DoctorValidationResult:
    doctor: DoctorRecord | None
    error: str | None = None


class DoctorValidationError(AssertionError):
    """Raised when CARES details do not match an Azure SQL doctor record."""


class ConsoleMismatchNotifier:
    """Report CARES/database mismatches without sending external email."""

    def send(self, laboratory: str, dentist: str, reason: str) -> None:
        print(
            "CARES doctor validation failed | "
            f"Laboratory/Practice: {laboratory} | Dentist: {dentist} | Reason: {reason}",
            flush=True,
        )


class GraphMismatchNotifier:
    """Send mismatch notifications with the Mail Sender app via Graph."""

    RECIPIENT = "sai.kodala@veltris.com"

    def send(self, laboratory: str, dentist: str, reason: str) -> None:
        tenant_id = os.getenv("MAIL_SENDER_TENANT_ID") or os.getenv(
            "INTERNAL_TENANT_ID"
        )
        client_id = os.getenv("MAIL_SENDER_CLIENT_ID")
        client_secret = os.getenv("MAIL_SENDER_CLIENT_SECRET")
        sender = os.getenv("MAIL_SENDER_ADDRESS")
        missing = [
            name
            for name, value in {
                "MAIL_SENDER_TENANT_ID (or INTERNAL_TENANT_ID)": tenant_id,
                "MAIL_SENDER_CLIENT_ID": client_id,
                "MAIL_SENDER_CLIENT_SECRET": client_secret,
                "MAIL_SENDER_ADDRESS": sender,
            }.items()
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing Microsoft Graph settings: {', '.join(missing)}")

        token_request = Request(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data=urlencode({
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(token_request, timeout=30) as response:
            access_token = json.load(response)["access_token"]

        content = (
            "CARES doctor validation failed.\n\n"
            f"Laboratory/Practice: {laboratory}\nDentist: {dentist}\nReason: {reason}\n"
        )
        mail_request = Request(
            f"https://graph.microsoft.com/v1.0/users/{quote(sender)}/sendMail",
            data=json.dumps({
                "message": {
                    "subject": "CARES doctor validation failed",
                    "body": {"contentType": "Text", "content": content},
                    "toRecipients": [{
                        "emailAddress": {"address": self.RECIPIENT}
                    }],
                },
                "saveToSentItems": True,
            }).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(mail_request, timeout=30) as response:
            if response.status != 202:
                raise RuntimeError(f"Microsoft Graph sendMail returned {response.status}")


class DoctorValidationService:
    """Resolve a CARES dentist and practice to an Azure Doctor.AccountId."""

    def __init__(self, notifier: Any | None = None) -> None:
        self.notifier = notifier or GraphMismatchNotifier()

    @staticmethod
    def _normalise(value: str) -> str:
        value = re.sub(r"\([^)]*\)\s*$", "", value or "")
        value = re.sub(r"^(?:dr|doctor)\.?\s+", "", value, flags=re.IGNORECASE)
        return " ".join(value.casefold().split())

    def validate(self, laboratory: str, dentist: str) -> DoctorValidationResult:
        candidates = self._find_doctors(dentist)
        self._print_doctor_records(candidates)
        expected_name = self._normalise(dentist)
        expected_practice = self._normalise(laboratory)
        doctor_matches = [
            row
            for row in candidates
            if self._normalise(row.name) == expected_name
            and row.account_id
        ]
        practice_matches = [
            row
            for row in doctor_matches
            if self._normalise(row.practice) == expected_practice
        ]
        selected = practice_matches[0] if practice_matches else (
            doctor_matches[0] if doctor_matches else None
        )
        if selected is not None:
            practice_status = (
                "matched"
                if self._normalise(selected.practice) == expected_practice
                else f"not matched (CARES={laboratory!r}, DB={selected.practice!r})"
            )
            print(
                "CARES doctor validation matched | "
                f"AccountId: {selected.account_id} | "
                f"DoctorName: {selected.name} | "
                f"PracticeName: {selected.practice} | "
                f"Practice check: {practice_status} | "
                f"Email: {selected.email}",
                flush=True,
            )
            return DoctorValidationResult(doctor=selected)

        reason = "no matching DoctorName record with a non-empty AccountId"
        ConsoleMismatchNotifier().send(laboratory, dentist, reason)
        try:
            self.notifier.send(laboratory, dentist, reason)
        except Exception as notification_error:
            reason = f"{reason}; notification failed: {notification_error}"
        message = (
            f"CARES Laboratory={laboratory!r}, Dentist={dentist!r}: {reason}"
        )
        return DoctorValidationResult(doctor=None, error=message)

    @staticmethod
    def _print_doctor_records(records: list[DoctorRecord]) -> None:
        if not records:
            print("Azure SQL doctor lookup returned no records", flush=True)
            return
        for number, doctor in enumerate(records, start=1):
            print(
                f"Azure SQL doctor candidate {number} | "
                f"AccountId: {doctor.account_id} | "
                f"DoctorName: {doctor.name} | "
                f"PracticeName: {doctor.practice} | "
                f"Email: {doctor.email}",
                flush=True,
            )

    def _find_doctors(self, dentist: str) -> list[DoctorRecord]:
        try:
            import pymssql
        except ImportError as error:
            raise RuntimeError("Install pymssql to validate CARES doctors") from error

        required = {
            "AZURE_SQL_SERVER": os.getenv("AZURE_SQL_SERVER"),
            "AZURE_SQL_DATABASE": os.getenv("AZURE_SQL_DATABASE"),
            "AZURE_SQL_USERNAME": os.getenv("AZURE_SQL_USERNAME"),
            "AZURE_SQL_PASSWORD": os.getenv("AZURE_SQL_PASSWORD"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing Azure SQL settings: {', '.join(missing)}")

        search_name = self._normalise(dentist)
        connection = pymssql.connect(
            server=required["AZURE_SQL_SERVER"],
            user=required["AZURE_SQL_USERNAME"],
            password=required["AZURE_SQL_PASSWORD"],
            database=required["AZURE_SQL_DATABASE"],
            login_timeout=15,
            timeout=30,
        )
        try:
            cursor = connection.cursor(as_dict=True)
            cursor.execute(
                "SELECT AccountId, DoctorName, PracticeName, Email "
                "FROM dbo.Doctor WHERE DoctorName LIKE %s ORDER BY Id",
                (f"%{search_name}%",),
            )
            return [
                DoctorRecord(
                    account_id=(row["AccountId"] or "").strip(),
                    name=(row["DoctorName"] or "").strip(),
                    practice=(row["PracticeName"] or "").strip(),
                    email=(row["Email"] or "").strip(),
                )
                for row in cursor.fetchall()
            ]
        finally:
            connection.close()
