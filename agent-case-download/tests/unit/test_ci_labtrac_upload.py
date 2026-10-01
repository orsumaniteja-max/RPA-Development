import json
from unittest.mock import Mock

import pytest

from utilities import ci_labtrac_upload as module
from services.labtrac_upload_service import APPLICATIONS, LabtracUploadService
from utilities.config_reader import ConfigReader


def test_default_zero_does_not_initialize_uploader(monkeypatch):
    factory = Mock(side_effect=AssertionError("Uploads must be disabled"))
    monkeypatch.setattr(module, "LabtracUploadService", factory)
    assert module.main([]) == 0
    factory.assert_not_called()


@pytest.mark.parametrize("count", ["-1", "1.5", "abc"])
def test_invalid_count_rejected_before_upload(monkeypatch, count):
    factory = Mock()
    monkeypatch.setattr(module, "LabtracUploadService", factory)
    with pytest.raises(SystemExit) as error:
        module.main(["--records-per-application", count])
    assert error.value.code == 2
    factory.assert_not_called()


@pytest.mark.parametrize("selection", ["carestream", "all"])
def test_custom_count_applies_to_each_selected_application(monkeypatch, selection):
    uploader = Mock()
    uploader.upload.return_value = []
    monkeypatch.setattr(module, "LabtracUploadService", lambda: uploader)
    assert module.main(["--application", selection, "--records-per-application", "5"]) == 0
    expected = APPLICATIONS if selection == "all" else (selection,)
    assert [call.args for call in uploader.upload.call_args_list] == [
        ((application,), 5) for application in expected
    ]


@pytest.mark.parametrize("selection", ["all", "carestream"])
def test_one_pending_per_selected_application_across_runs(tmp_path, monkeypatch, selection):
    for application in APPLICATIONS:
        folder = ConfigReader.get_config(application)["report_folder"]
        results = tmp_path / "reports" / folder / "results"
        results.mkdir(parents=True)
        for case in ("first", "second"):
            (results / f"{case}.json").write_text(json.dumps({
                "reference": case, "patientInfo": {"name": "Source Patient"}, "description": "Source prescription",
                "customerAccount": {"prescriber": {"id": "account-1", "name": "Source Doctor"}},
            }))
    client = Mock()
    client.submit_payload.return_value = {"submissionId": "test-submission"}
    monkeypatch.setattr(module, "LabtracUploadService",
                        lambda: LabtracUploadService(tmp_path, client, Mock(resolve=Mock(return_value="account-1")), sql_tracker=Mock()))
    monkeypatch.setattr(module, "LabtracAccountLookupService",
                        lambda: type("Lookup", (), {"resolve": lambda self, name: "account-1"})())
    expected = 6 if selection == "all" else 1
    args = ["--application", selection, "--records-per-application", "1"]
    assert module.main(args) == 0
    assert client.submit_payload.call_count == expected
    assert module.main(args) == 0
    assert client.submit_payload.call_count == 2 * expected
    assert module.main(args) == 0
    assert client.submit_payload.call_count == 2 * expected


def test_failed_application_is_reported_and_other_applications_are_processed(monkeypatch):
    uploader = Mock()
    uploader.upload.side_effect = [RuntimeError("configuration error")] + [
        [{"status": "uploaded"}]
    ] * 5
    monkeypatch.setattr(module, "LabtracUploadService", lambda: uploader)
    assert module.main(["--records-per-application", "1"]) == 1
    assert uploader.upload.call_count == 6
