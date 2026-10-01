from pathlib import Path
import os

import yaml


class ConfigReader:

    PROJECT_ROOT = Path(__file__).resolve().parents[1]

    @staticmethod
    def get_config(application=None):
        """Return shared settings merged with optional application settings."""
        config_path = ConfigReader.PROJECT_ROOT / "config" / "config.yaml"
        with config_path.open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}

        applications = config.pop("applications", {})
        if application:
            config.update(applications.get(application, {}))
        # Hosted CI containers have no desktop display. Keep local browser
        # visibility controlled by YAML while running CI in headless mode.
        if os.getenv("CI", "").strip().lower() in {"true", "1", "yes"}:
            config["headless"] = True
        return config
