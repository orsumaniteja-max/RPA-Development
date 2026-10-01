"""Preview or submit only existing SQL-listed saved cases; never recapture cases."""
import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

from dotenv import load_dotenv
from services.labtrac_upload_service import LabtracUploadService, select_applications
from services.rpa_sql_tracking_service import RpaSqlTrackingService
from services.upload_history_service import UploadHistoryService
from utilities.config_reader import ConfigReader


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--timestamps-only", action="store_true")
    parser.add_argument("--application", default="all")
    args = parser.parse_args(argv)
    applications = select_applications(args.application)
    load_dotenv(ConfigReader.PROJECT_ROOT / ".env")
    import pymssql
    settings = {"server": os.getenv("AZURE_SQL_SERVER"), "database": os.getenv("AZURE_SQL_DATABASE"),
                "user": os.getenv("AZURE_SQL_USERNAME"), "password": os.getenv("AZURE_SQL_PASSWORD")}
    if not all(settings.values()):
        raise RuntimeError("Missing SQL settings")
    connection = pymssql.connect(**settings, login_timeout=15, timeout=30)
    try:
        cursor = connection.cursor(as_dict=True)
        cursor.execute("SELECT a.ApplicationName, c.PrescriptionId, c.CaseSubmisisonAt "
                       "FROM dbo.RpaDownloadedCase c JOIN dbo.RpaApplication a ON a.ID=c.ApplicationId")
        rows = cursor.fetchall()
    finally:
        connection.close()
    history = UploadHistoryService.__new__(UploadHistoryService)
    history.root = ConfigReader.PROJECT_ROOT
    history.path = history.root / "reports/labtrac/upload_history.csv"
    if args.apply:
        history = UploadHistoryService(history.root)
    records = {(r["Application"], r["CaseId"]): r for r in history._read()}
    counts = Counter(database_rows=len(rows))
    eligible, backfill = set(), []
    for row in rows:
        try:
            app = select_applications(row["ApplicationName"])[0]
            if app not in applications:
                continue
            reference = str(row["PrescriptionId"])
            stem = re.sub(r'[<>:"/\\|?*]', "_", reference).strip().rstrip(".")
            saved = records.get((app, stem), {})
            if row["CaseSubmisisonAt"] is not None:
                counts["already_submitted_in_sql"] += 1
                continue
            if saved.get("Status") in {"uploaded", "submitted"}:
                response = json.loads(saved.get("Response") or "{}")
                timestamp = response.get("caseSubmissionAt") or saved.get("UploadedAtUTC")
                if timestamp and saved.get("SubmissionId"):
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("Historical submission time has no timezone")
                    backfill.append((row["ApplicationName"], reference, timestamp))
                    counts["confirmed_timestamp_backfill"] += 1
                else:
                    counts["submitted_missing_timestamp_evidence"] += 1
                continue
            if saved:
                counts["uncertain_history_blocked"] += 1
                continue
            folder = ConfigReader.get_config(app)["report_folder"]
            path = history.root / "reports" / folder / "results" / (stem + ".json")
            if not path.is_file():
                counts["missing_source"] += 1
                continue
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            LabtracUploadService.validate_payload(payload)
            if payload["reference"] != reference or row["ApplicationName"] != app:
                counts["identity_mismatch"] += 1
                continue
            eligible.add((app, stem))
        except Exception:
            counts["incomplete_or_invalid"] += 1
    counts["eligible_for_verified_upload"] = len(eligible)
    print(json.dumps(dict(counts)), flush=True)
    if not args.apply:
        return
    report = {"startedAtUTC": datetime.now(timezone.utc).isoformat(), "selection": dict(counts),
              "timestampUpdates": 0, "timestampErrors": [], "outcomes": []}
    destination = history.root / "reports/labtrac" / (
        "database_timestamp_retry.json" if args.timestamps_only else "database_upload_run.json")
    def checkpoint():
        destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tracker = RpaSqlTrackingService()
    checkpoint()
    connection = pymssql.connect(**settings, login_timeout=15, timeout=30)
    try:
        for index, (app, reference, timestamp) in enumerate(backfill, 1):
            try:
                tracker.record_submission(app, reference, timestamp,
                                          connection=None if args.timestamps_only else connection)
                report["timestampUpdates"] += 1
            except Exception as error:
                report["timestampErrors"].append({"application": app, "case": reference, "error": str(error)})
            checkpoint()
            if index % 20 == 0:
                print(f"Historical timestamp updates: {index}/{len(backfill)}", flush=True)
    finally:
        connection.close()
    if args.timestamps_only:
        eligible = set()
    uploader = LabtracUploadService()
    for index, (app, case) in enumerate(sorted(eligible), 1):
        report["outcomes"].extend(uploader.upload((app,), eligible_cases={(app, case)}))
        checkpoint()
        print(f"Processed upload candidate {index}/{len(eligible)}", flush=True)
    report["finishedAtUTC"] = datetime.now(timezone.utc).isoformat()
    checkpoint()
    print(json.dumps({"timestampUpdates": report["timestampUpdates"],
                      "timestampErrors": len(report["timestampErrors"]),
                      "uploadOutcomes": dict(Counter(r["status"] for r in report["outcomes"])),
                      "sqlTrackingErrors": sum(bool(r.get("sqlTrackingError")) for r in report["outcomes"])}), flush=True)
    return int(bool(report["timestampErrors"]) or any(
        r["status"] != "uploaded" or r.get("sqlTrackingError") for r in report["outcomes"]))


if __name__ == "__main__":
    raise SystemExit(main())
