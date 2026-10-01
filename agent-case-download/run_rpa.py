"""User-configured capture and sequential Labtrac upload entry point."""

import argparse
import importlib
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from services.labtrac_api_service import LabtracApiClient
from services.labtrac_upload_service import LabtracUploadService, record_limit, select_applications
from utilities.config_reader import ConfigReader


CAPTURE_SERVICES = {
    "cares_connect": ("cares", "CaresCaseCaptureService"),
    "ori_portal": ("ori", "OriCaseCaptureService"),
    "io_scanner": ("io_scanner", "IoScannerCaseCaptureService"),
    "carestream": ("carestream", "CarestreamCaseCaptureService"),
    "ddx": ("ddx", "DdxCaseCaptureService"),
    "axs_straumann": ("axs_straumann", "AxsStraumannCaseCaptureService"),
}

LOGGER = logging.getLogger(__name__)


def capture(applications, limit=None):
    from utilities.browser_manager import BrowserManager

    for application in applications:
        if limit is not None and limit <= 0:
            break
        LOGGER.info("Starting capture: %s", application)
        config = ConfigReader.get_config(application)
        username = os.getenv(config["username_env"])
        password = os.getenv(config["password_env"])
        if not username or not password:
            raise ValueError(f"Missing credentials for {application}")
        module, name = CAPTURE_SERVICES[application]
        service_class = getattr(importlib.import_module(f"services.{module}_case_capture_service"), name)
        service = service_class(reports_root=ConfigReader.PROJECT_ROOT / "reports" / config["report_folder"])
        playwright, browser, page = BrowserManager().launch_browser(config["browser"], config["headless"])
        try:
            page.set_default_timeout(config.get("timeout", 30000))
            page.set_default_navigation_timeout(config.get("timeout", 30000))
            page.goto(config["base_url"], wait_until=config.get("navigation_wait_until", "load"))
            results = service.capture_all_cases(
                page, username, password, max_cases=sys.maxsize, max_new_cases=limit,
            )
            if limit is not None:
                limit -= len(results)
            LOGGER.info("Capture complete: %s; %s new records", application, len(results))
        finally:
            browser.close()
            playwright.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ConfigReader.PROJECT_ROOT / "config" / "rpa_input.json")
    parser.add_argument("--application", help='Application name or "all"')
    parser.add_argument("--records", help='Positive number or "all" (total across selected applications)')
    parser.add_argument("--mode", choices=("end_to_end", "capture_and_upload", "upload_only", "capture_only", "capture"))
    parser.add_argument("--check-labtrac", action="store_true",
                        help="Verify Labtrac authentication without capturing or uploading cases")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv(ConfigReader.PROJECT_ROOT / ".env")
    if args.check_labtrac:
        LabtracApiClient().check_authentication()
        print("Labtrac authentication successful. No cases were uploaded.")
        return 0
    input_path = args.input if args.input.is_absolute() else ConfigReader.PROJECT_ROOT / args.input
    settings = json.loads(input_path.read_text(encoding="utf-8-sig"))
    if not isinstance(settings, dict):
        raise ValueError("RPA input must be a JSON object")
    applications = select_applications(args.application or settings.get("application", "all"))
    limit = record_limit(args.records or settings.get("records", "all"))
    mode = args.mode or settings.get("mode", "capture_and_upload")
    if mode == "end_to_end":
        if limit is not None:
            raise ValueError("end_to_end processes all eligible cases; use --records all")
        from utilities.upload_database_cases import main as upload_database_cases
        failed = False
        for application in applications:
            try:
                capture((application,))
            except Exception as error:
                LOGGER.error("Capture failed for %s; continuing with other portals: %s", application, error)
                failed = True
        selection = "all" if len(applications) > 1 else applications[0]
        try:
            upload_result = upload_database_cases(["--apply", "--application", selection])
            failed = bool(upload_result) or failed
        except Exception as error:
            LOGGER.error("Database-listed upload could not complete: %s", error)
            failed = True
        return int(failed)
    if mode == "capture":
        mode = "capture_only"
    if mode not in {"capture_and_upload", "upload_only", "capture_only"}:
        raise ValueError("Invalid mode")
    LOGGER.info("Input: %s; mode: %s; applications: %s; upload limit: %s",
                input_path, mode, ", ".join(applications), limit if limit is not None else "all")
    if mode == "capture_only":
        capture(applications)
    else:
        LOGGER.info("Starting pending Labtrac uploads")
        uploader = LabtracUploadService()
        outcomes = uploader.upload(applications, limit)
        remaining = None if limit is None else limit - sum(
            item["status"] == "uploaded" for item in outcomes
        )
        if (mode == "capture_and_upload"
                and (remaining is None or remaining > 0)
                and all(item["status"] == "uploaded" for item in outcomes)):
            LOGGER.info("Saved pending cases exhausted; capturing up to %s new cases",
                        remaining if remaining is not None else "all")
            capture(applications, limit=remaining)
            outcomes.extend(uploader.upload(applications, remaining))
        print(json.dumps(outcomes, indent=2))
        if any(item["status"] != "uploaded" or item.get("sqlTrackingError") for item in outcomes):
            return 1
    return 0


def cli():
    try:
        return main()
    except KeyboardInterrupt:
        LOGGER.error("RPA interrupted")
        return 130
    except Exception as error:
        if "18456" in str(error):
            LOGGER.error(
                "RPA stopped: Azure SQL rejected the doctor-catalog login (18456). "
                "Check AZURE_SQL_USERNAME, AZURE_SQL_PASSWORD, AZURE_SQL_SERVER "
                "and AZURE_SQL_DATABASE in .env and any environment overrides."
            )
        else:
            LOGGER.error("RPA stopped: %s", error)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
