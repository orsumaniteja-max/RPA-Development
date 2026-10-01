"""Resolve a Labtrac customer account from the unique ROE doctor name."""

from __future__ import annotations

import os
import re


class LabtracAccountLookupError(LookupError):
    """The captured doctor cannot be mapped to one unambiguous AccountId."""


class LabtracAccountLookupService:
    """Read only the AccountId needed immediately before Labtrac submission."""

    def resolve(self, doctor_name: str) -> str:
        name = self._normalise(doctor_name)
        if not name:
            raise LabtracAccountLookupError("Case has no doctor name for AccountId lookup")
        try:
            import pymssql
        except ImportError as error:
            raise RuntimeError("Install pymssql to resolve the Labtrac AccountId") from error
        settings = {
            "server": os.getenv("AZURE_SQL_SERVER"),
            "database": os.getenv("AZURE_SQL_DATABASE"),
            "user": os.getenv("AZURE_SQL_USERNAME"),
            "password": os.getenv("AZURE_SQL_PASSWORD"),
        }
        missing = [key for key, value in settings.items() if not value]
        if missing:
            raise RuntimeError("Missing Azure SQL settings for AccountId lookup: " + ", ".join(missing))
        connection = pymssql.connect(**settings, login_timeout=15, timeout=30)
        try:
            cursor = connection.cursor(as_dict=True)
            # The surname narrows the query; normalized full-name comparison
            # prevents a different doctor with the same first name being used.
            cursor.execute(
                "SELECT AccountId, AccountName FROM dbo.Doctor "
                "WHERE AccountName LIKE %s AND AccountId IS NOT NULL AND LTRIM(RTRIM(AccountId)) <> ''",
                (f"%{name.split()[-1]}%",),
            )
            account_ids = {
                str(row["AccountId"]).strip()
                for row in cursor.fetchall()
                if self._normalise(str(row.get("AccountName") or "")) == name
                and str(row.get("AccountId") or "").strip()
            }
        finally:
            connection.close()
        if len(account_ids) != 1:
            description = "no" if not account_ids else "multiple"
            raise LabtracAccountLookupError(
                f"Found {description} unique AccountId records for doctor '{doctor_name}'"
            )
        return account_ids.pop()

    @staticmethod
    def _normalise(value: str) -> str:
        value = re.sub(r"^(?:dr|doctor)\.?\s+", "", str(value or ""), flags=re.IGNORECASE)
        return " ".join(value.casefold().split())
