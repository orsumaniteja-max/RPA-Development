"""Backfill Azure SQL from local RPA history and preserved result files.

Run from the project root: python -m utilities.sync_rpa_case_history
"""

from dotenv import load_dotenv

from services.rpa_case_tracking_service import RpaCaseTrackingService
from utilities.config_reader import ConfigReader


def main():
    load_dotenv(ConfigReader.PROJECT_ROOT / ".env")
    for application in (
        "cares_connect", "ori_portal", "io_scanner", "carestream", "ddx", "axs_straumann",
    ):
        folder = ConfigReader.get_config(application)["report_folder"]
        RpaCaseTrackingService(
            application, ConfigReader.PROJECT_ROOT / "reports" / folder / "results",
        )
        print(f"Synchronized RPA history: {application}")


if __name__ == "__main__":
    main()
