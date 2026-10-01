"""CSV-backed upload claims and outcomes; legacy SQLite is read only for migration."""

import csv
import json
import os
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path


class UploadHistoryService:
    FIELDS = ["Application", "CaseId", "Reference", "Patient", "SubmittedPatient",
              "Prescriber", "AccountId", "SubmissionId", "Status", "UploadedAtUTC",
              "UpdatedAtUTC", "Response"]
    LEGACY_FIELDS = FIELDS.copy()
    FIELDS = FIELDS + ["PrescriberEmail", "PrescriberPhone", "LicenceNo", "DateRequested",
                       "SourceFile", "SourcePayload", "MetadataSource", "Error"]
    PRE_TIMESTAMP_FIELDS = FIELDS.copy()
    FIELDS = FIELDS + ["DownloadedAtUTC", "UploadAttemptedAtUTC"]

    def __init__(self, root):
        self.root = Path(root)
        self.path = Path(root) / "reports" / "labtrac" / "upload_history.csv"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock():
            marker = self.path.with_suffix(".initialized")
            if not self.path.exists():
                if marker.exists():
                    raise ValueError("Upload history CSV is missing; restore it before uploading")
                self._write(self._legacy_rows(Path(root)))
            marker.touch(exist_ok=True)
            rows = self._read()
            for row in rows:
                self._backfill(row)
            self._write(rows)

    @contextmanager
    def _lock(self):
        # OS releases this lock if a runner crashes. Concurrent runners serialize
        # CSV updates before making requests rather than risking duplicate claims.
        with self.path.with_suffix(".lock").open("a+b") as stream:
            stream.seek(0, 2)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def _read(self):
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames not in (self.FIELDS, self.LEGACY_FIELDS, self.PRE_TIMESTAMP_FIELDS):
                raise ValueError("Upload history CSV is invalid; restore it before uploading")
            rows = list(reader)
        keys = set()
        for row in rows:
            key = (row.get("Application"), row.get("CaseId"))
            if not all(key) or key in keys or row.get("Status") not in {
                "uploaded", "in_progress", "needs_review", "submitted", "pending"
            } or None in row or any(value is None for value in row.values()):
                raise ValueError("Upload history CSV contains invalid records")
            keys.add(key)
        return rows

    @staticmethod
    def case_details(payload, path):
        prescriber = payload.get("customerAccount", {}).get("prescriber") or {}
        contact = prescriber.get("contact") or {}
        return {
            "Reference": payload.get("reference") or path.stem,
            "Patient": (payload.get("patientInfo") or {}).get("name", ""),
            "Prescriber": prescriber.get("name", ""),
            "AccountId": payload.get("customerAccount", {}).get("id") or prescriber.get("id", ""),
            "PrescriberEmail": contact.get("email", ""),
            "PrescriberPhone": contact.get("phone", ""),
            "LicenceNo": prescriber.get("licenceNo", ""),
            "DateRequested": payload.get("dateRequested", ""),
            "SourceFile": str(path),
            "SourcePayload": json.dumps(payload, ensure_ascii=False),
        }

    def _backfill(self, row):
        if row.get("SourcePayload"):
            return
        from utilities.config_reader import ConfigReader
        folder = ConfigReader.get_config(row["Application"])["report_folder"]
        path = self.root / "reports" / folder / "results" / (row["CaseId"] + ".json")
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            details = self.case_details(payload, path)
        except (OSError, ValueError, AttributeError, TypeError):
            row["MetadataSource"] = "Source file unavailable; historical details not recorded"
            return
        for key, value in details.items():
            if not row.get(key):
                row[key] = value
        row["MetadataSource"] = "Recovered from current source JSON; original request not recorded"

    def _write(self, rows):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8-sig",
                                             newline="", dir=self.path.parent,
                                             suffix=".tmp", delete=False) as stream:
                temporary = stream.name
                writer = csv.DictWriter(stream, fieldnames=self.FIELDS)
                writer.writeheader()
                writer.writerows(rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary:
                Path(temporary).unlink(missing_ok=True)

    def status(self, application, case_id):
        with self._lock():
            # Translate at the caller boundary without rewriting saved statuses.
            return next(({"submitted": "uploaded", "pending": "needs_review"}.get(
                            row["Status"], row["Status"]) for row in self._read()
                         if (row["Application"], row["CaseId"]) == (application, case_id)), None)

    def claim(self, application, case_id, info):
        with self._lock():
            rows = self._read()
            if any((row["Application"], row["CaseId"]) == (application, case_id) for row in rows):
                return False
            rows.append({**info, "Application": application, "CaseId": case_id,
                         "Status": "in_progress", "UpdatedAtUTC": self._now()})
            self._write(rows)
            return True

    def submission_tracking(self, application, case_id):
        with self._lock():
            row = next((r for r in self._read() if
                        (r["Application"], r["CaseId"]) == (application, case_id)), None)
            return json.loads(row.get("Response") or "{}") if row else {}

    def mark_submission_synced(self, application, case_id):
        with self._lock():
            rows = self._read()
            for row in rows:
                if (row["Application"], row["CaseId"]) == (application, case_id):
                    response = json.loads(row.get("Response") or "{}")
                    if row["Status"] not in {"submitted", "uploaded"}:
                        return
                    response["sqlTrackingPending"] = False
                    row["Response"] = json.dumps(response)
                    self._write(rows)
                    return

    def save(self, application, case_id, status, response):
        with self._lock():
            rows = self._read()
            row = next((r for r in rows if (r["Application"], r["CaseId"]) ==
                        (application, case_id)), None)
            if row is None:
                row = {"Application": application, "CaseId": case_id}
                self._backfill(row)
                rows.append(row)
            if row.get("Status") in {"uploaded", "submitted"}:
                return
            row.update(Status=status, Response=json.dumps(response),
                       SubmissionId=response.get("submissionId", ""), UpdatedAtUTC=self._now())
            row["Error"] = response.get("error", "")
            if status == "uploaded":
                row["UploadedAtUTC"] = row["UpdatedAtUTC"]
            self._write(rows)

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _legacy_rows(self, root):
        database = root / "data" / "labtrac_uploads.db"
        if not database.exists():
            return []
        import sqlite3
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            columns = {r[1] for r in connection.execute("PRAGMA table_info(uploads)")}
            info = "record_info" if "record_info" in columns else "'{}'"
            records = connection.execute(
                f"SELECT application, case_id, status, response, updated_at, {info} FROM uploads"
            ).fetchall()
        return [{**json.loads(info or "{}"), "Application": app, "CaseId": case,
                 "Status": status, "Response": response or "{}",
                 "SubmissionId": json.loads(response or "{}").get("submissionId", ""),
                 "UpdatedAtUTC": timestamp,
                 "UploadedAtUTC": timestamp if status == "uploaded" else ""}
                for app, case, status, response, timestamp, info in records]
