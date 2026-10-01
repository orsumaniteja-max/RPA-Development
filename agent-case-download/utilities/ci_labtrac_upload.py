"""Opt-in CI uploads, with a separate limit for each selected portal."""

import argparse
import json
import logging

from services.labtrac_upload_service import LabtracUploadService, select_applications
from services.labtrac_account_lookup_service import LabtracAccountLookupService


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", default="all")
    parser.add_argument("--records-per-application", type=int, default=0)
    args = parser.parse_args(argv)
    if args.records_per_application < 0:
        parser.error("--records-per-application must be a non-negative whole number")
    applications = select_applications(args.application)
    if args.records_per_application == 0:
        print("Labtrac uploads disabled (0 records per application).")
        return 0

    logging.basicConfig(level=logging.INFO)
    uploader = LabtracUploadService()
    # CI must use the database AccountId rather than a portal-name fallback.
    uploader.account_lookup = LabtracAccountLookupService()
    failed = False
    for application in applications:
        try:
            outcomes = uploader.upload((application,), args.records_per_application)
            print(json.dumps({"application": application, "outcomes": outcomes}), flush=True)
            if not outcomes:
                print(f"{application}: no pending cases available.", flush=True)
            failed |= any(item["status"] != "uploaded" or item.get("sqlTrackingError") for item in outcomes)
        except Exception as error:
            logging.error("Labtrac upload failed for %s: %s", application, error)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
