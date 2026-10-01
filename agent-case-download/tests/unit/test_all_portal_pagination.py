import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


APPLICATIONS = [
    ("cares", "CaresCaseCaptureService"),
    ("carestream", "CarestreamCaseCaptureService"),
    ("ddx", "DdxCaseCaptureService"),
    ("io_scanner", "IoScannerCaseCaptureService"),
    ("ori", "OriCaseCaptureService"),
    ("axs_straumann", "AxsStraumannCaseCaptureService"),
]


@pytest.mark.parametrize("application,class_name", APPLICATIONS)
@pytest.mark.parametrize("limits,expected", [({}, 54), ({"max_cases": 51}, 51), ({"max_new_cases": 1}, 51)])
def test_all_pages_after_downloaded_first_page(monkeypatch, tmp_path, application, class_name, limits, expected):
    module = importlib.import_module(f"services.{application}_case_capture_service")
    cls = getattr(module, class_name)
    service = cls.__new__(cls)
    service.results_root = tmp_path / "results"
    service.reports_root = tmp_path
    tracker = Mock()
    tracker.is_downloaded.side_effect = lambda case_id: int(case_id[3:]) < 50
    service.case_tracker = service.tracker = tracker
    service._export = Mock(side_effect=lambda page, case_id, *args: case_id)
    service._capture_current_case = Mock(side_effect=lambda *args, case_id: SimpleNamespace(case_id=case_id))

    pages = [[f"RX-{i}" for i in range(50)], ["RX-50", "RX-51"], ["RX-52", "RX-53"]]
    state = {"page": 0, "record": 0}
    current_ids = lambda: pages[state["page"]]
    current_id = lambda: current_ids()[state["record"]]
    dashboard = Mock()

    def next_page():
        state["page"] += 1
        state["record"] = 0

    def open_record(index, *args):
        state["record"] = index
        return current_id()

    dashboard.get_record_count.side_effect = dashboard.record_count.side_effect = lambda: len(current_ids())
    dashboard.has_next_page.side_effect = lambda: state["page"] < len(pages) - 1
    dashboard.open_next_page.side_effect = dashboard.next_page.side_effect = next_page
    dashboard.open_record.side_effect = open_record
    dashboard.record_id.side_effect = lambda index: current_ids()[index]
    dashboard.get_case_numbers.side_effect = lambda: current_ids()
    dashboard.get_selected_case_number.side_effect = current_id
    dashboard.open_case.side_effect = lambda case_id: open_record(current_ids().index(case_id))
    dashboard.open_first_record.side_effect = lambda: open_record(0)
    dashboard.has_next_case.side_effect = lambda: state["record"] < len(current_ids()) - 1
    dashboard.open_next_case.side_effect = lambda case_id: open_record(state["record"] + 1)

    details = Mock()
    details.get_case_id.side_effect = current_id
    details.get_detail.side_effect = lambda label: current_id()
    details._clean_case_id.side_effect = lambda value: value
    details.get_case_information.side_effect = lambda: {"Order Number": current_id()}
    monkeypatch.setattr(module, "LabOrdersPage" if application == "axs_straumann" else "DashboardPage", Mock(return_value=dashboard))
    monkeypatch.setattr(module, "OrderDetailsPage" if application == "axs_straumann" else "CaseDetailsPage", Mock(return_value=details))
    monkeypatch.setattr(module, "LoginPage", Mock())
    monkeypatch.setattr(module, "DoctorCatalogService", Mock())

    output = service.capture_all_cases(Mock(), "user", "password", **limits)

    assert tracker.is_downloaded.call_count == expected
    assert [call.args[0] for call in tracker.is_downloaded.call_args_list] == [f"RX-{i}" for i in range(expected)]
    assert [item.case_id if application == "cares" else item for item in output] == [f"RX-{i}" for i in range(50, expected)]
    next_control = dashboard.next_page if application == "axs_straumann" else dashboard.open_next_page
    assert next_control.call_count == (2 if expected == 54 else 1)
