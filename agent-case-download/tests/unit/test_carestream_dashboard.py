from unittest.mock import MagicMock

from pages.carestream.dashboard_page import DashboardPage


def test_get_case_numbers_finds_nested_rows_and_excludes_selected_case():
    page = MagicMock()
    selected_case = MagicMock()
    page.locator.return_value = selected_case
    selected_case.inner_text.return_value = "OHA-5572"
    selected_case.bounding_box.return_value = {"x": 400, "y": 0, "width": 100, "height": 40}

    def case_match(text, x):
        match = MagicMock()
        match.is_visible.return_value = True
        match.bounding_box.return_value = {"x": x, "y": 100, "width": 80, "height": 20}
        match.inner_text.return_value = text
        return match

    page.get_by_text.return_value.all.return_value = [
        case_match("OHA-5572", 20),
        case_match("OHA-5573", 20),
        case_match("OHA-5574", 20),
        case_match("OHA-5573", 20),
        case_match("OHA-9999", 700),
    ]

    assert DashboardPage(page).get_case_numbers() == ["OHA-5573", "OHA-5574"]
    selected_case.wait_for.assert_called_once_with(
        state="visible", timeout=180000
    )
