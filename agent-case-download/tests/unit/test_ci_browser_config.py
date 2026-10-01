"""Check the host-to-container CI browser configuration."""

from pathlib import Path

import pytest
import yaml

from utilities.config_reader import ConfigReader


@pytest.mark.parametrize("ci", ["true", "TRUE", "1", "yes"])
def test_ci_uses_headless_browser_for_every_portal(monkeypatch, ci):
    monkeypatch.setenv("CI", ci)
    for application in ("ddx", "ori_portal", "io_scanner", "cares_connect",
                        "carestream", "axs_straumann"):
        assert ConfigReader.get_config(application)["headless"] is True


@pytest.mark.parametrize("ci", ["", "false"])
def test_local_browser_setting_is_preserved(tmp_path, monkeypatch, ci):
    monkeypatch.setenv("CI", ci)
    monkeypatch.setattr(ConfigReader, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text("headless: false\n")
    assert ConfigReader.get_config()["headless"] is False


def test_pipeline_passes_ci_to_container():
    path = Path(__file__).resolve().parents[2] / "azure-pipelines.yml"
    pipeline = yaml.safe_load(path.read_text())
    steps = pipeline["jobs"][0]["steps"]
    capture = next(step for step in steps if "--reruns" in step.get("bash", ""))
    assert capture["env"]["CI"] is True or capture["env"]["CI"] == "true"
    assert "--env CI" in capture["bash"]
