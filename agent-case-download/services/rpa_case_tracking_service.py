"""Project-local prescription download history and duplicate prevention."""

from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from utilities.config_reader import ConfigReader
from services.rpa_sql_tracking_service import RpaSqlTrackingService


DEFAULT_DATABASE_PATH = ConfigReader.PROJECT_ROOT / "data" / "rpa_case_tracking.db"


class RpaCaseTrackingService:
    """Own the application master record and downloaded-case pre-check."""

    def __init__(
        self,
        application_name: str,
        results_root: Path,
        database_path: Path | None = None,
        sql_tracker: RpaSqlTrackingService | None = None,
    ) -> None:
        self.application_name = application_name.strip()
        if not self.application_name:
            raise ValueError("Application name is required for case tracking")
        self.results_root = Path(results_root)
        self.database_path = Path(database_path or DEFAULT_DATABASE_PATH)
        self.csv_path = self.database_path.with_suffix(".csv")
        # An explicit local database keeps isolated/offline callers local.
        self.sql_tracker = sql_tracker or (RpaSqlTrackingService() if database_path is None else None)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._export_enabled = False
        self._ensure_schema()
        self._adopt_existing_results()
        self._export_enabled = True
        self.export_latest_doctors()
        self.sync_sql_history()

    def sync_sql_history(self) -> None:
        """Backfill preserved history, including cases adopted from results."""
        if self.sql_tracker is None:
            return
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT cases.PrescriptionId FROM RpaDownloadedCases cases "
                "JOIN RpaApplications apps ON apps.Id = cases.ApplicationId "
                "WHERE apps.ApplicationName = ?", (self.application_name,),
            ).fetchall()
        self.sql_tracker.sync(self.application_name, [row[0] for row in rows])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _ensure_schema(self) -> None:
        """Create the local master and case/doctor detail tables when absent."""
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS RpaApplications (
                    Id TEXT NOT NULL PRIMARY KEY,
                    ApplicationName TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS RpaDownloadedCases (
                    Id TEXT NOT NULL PRIMARY KEY,
                    ApplicationId TEXT NOT NULL,
                    PrescriptionId TEXT NOT NULL,
                    DoctorName TEXT,
                    DownloadedAt TEXT NOT NULL DEFAULT (
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    ),
                    FOREIGN KEY (ApplicationId) REFERENCES RpaApplications(Id),
                    UNIQUE (ApplicationId, PrescriptionId)
                );

                CREATE INDEX IF NOT EXISTS IX_RpaDownloadedCases_PrescriptionId
                    ON RpaDownloadedCases(PrescriptionId);
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO RpaApplications (Id, ApplicationName)
                VALUES (?, ?)
                """,
                (str(uuid.uuid4()), self.application_name),
            )

    def is_downloaded(self, prescription_id: str) -> bool:
        """Return true only when the case history and JSON artifact agree."""
        prescription_id = self._normalise_prescription_id(prescription_id)
        stem = re.sub(r'[<>:"/\\|?*]', "_", prescription_id).strip().rstrip(".")
        result_file = self.results_root / f"{stem}.json"
        with self._connect() as connection:
            tracked = connection.execute(
                """
                SELECT 1
                FROM RpaDownloadedCases AS cases
                INNER JOIN RpaApplications AS apps
                    ON apps.Id = cases.ApplicationId
                WHERE apps.ApplicationName = ? AND cases.PrescriptionId = ?
                """,
                (self.application_name, prescription_id),
            ).fetchone() is not None
        if tracked:
            # Tracking is not completion when the persistent output was moved
            # or deleted. Let the portal regenerate the missing artifact.
            if result_file.is_file():
                if self.sql_tracker is not None:
                    self.sql_tracker.sync(self.application_name, [prescription_id])
                return True
            return False

        # Adopt result files created before tracking was introduced. This keeps
        # historical output intact and prevents it from being overwritten.
        if result_file.is_file():
            self.record_download(prescription_id, "")
            return True
        return False

    def _adopt_existing_results(self) -> None:
        """Seed history from preserved JSON results created by older runs."""
        if not self.results_root.is_dir():
            return
        for result_file in self.results_root.glob("*.json"):
            if result_file.stem.endswith("_labtrac"):
                continue
            try:
                payload = json.loads(result_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            self.record_download(
                payload.get("reference") or result_file.stem,
                self.doctor_name(payload) if isinstance(payload, dict) else "",
            )

    def record_download(self, prescription_id: str, doctor_name: str) -> bool:
        """Insert a completed case once; return false when it already exists."""
        prescription_id = self._normalise_prescription_id(prescription_id)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO RpaDownloadedCases (
                    Id, ApplicationId, PrescriptionId, DoctorName
                )
                SELECT ?, apps.Id, ?, NULLIF(?, '')
                FROM RpaApplications AS apps
                WHERE apps.ApplicationName = ?
                """,
                (
                    str(uuid.uuid4()),
                    prescription_id,
                    str(doctor_name or "").strip(),
                    self.application_name,
                ),
            )
            inserted = cursor.rowcount == 1
        if self._export_enabled:
            if self.sql_tracker is not None:
                self.sql_tracker.sync(self.application_name, [prescription_id])
            self.export_latest_doctors()
        return inserted

    def export_latest_doctors(self) -> None:
        """Export each named doctor once, using their latest downloaded case."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                WITH LatestDoctors AS (
                    SELECT
                        apps.ApplicationName,
                        cases.PrescriptionId,
                        TRIM(cases.DoctorName) AS DoctorName,
                        cases.DownloadedAt,
                        ROW_NUMBER() OVER (
                            PARTITION BY LOWER(TRIM(cases.DoctorName))
                            ORDER BY cases.DownloadedAt DESC, cases.rowid DESC
                        ) AS RowNumber
                    FROM RpaDownloadedCases AS cases
                    INNER JOIN RpaApplications AS apps
                        ON apps.Id = cases.ApplicationId
                    WHERE TRIM(COALESCE(cases.DoctorName, '')) <> ''
                )
                SELECT ApplicationName, PrescriptionId, DoctorName, DownloadedAt
                FROM LatestDoctors
                WHERE RowNumber = 1
                ORDER BY LOWER(DoctorName), DoctorName
                """
            ).fetchall()

        temporary_path = self.csv_path.with_name(
            f".{self.csv_path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary_path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    ("ApplicationName", "PrescriptionId", "DoctorName", "DownloadedAt")
                )
                writer.writerows(rows)
            os.replace(temporary_path, self.csv_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    @staticmethod
    def _normalise_prescription_id(prescription_id: str) -> str:
        value = str(prescription_id or "").strip()
        if not value:
            raise ValueError("Prescription ID is required for case tracking")
        return value

    @staticmethod
    def doctor_name(payload: dict[str, Any]) -> str:
        prescriber = payload.get("customerAccount", {}).get("prescriber", {})
        contact = prescriber.get("contact", {}) if isinstance(prescriber, dict) else {}
        return str(
            prescriber.get("name")
            or contact.get("displayName")
            or ""
        ).strip()
