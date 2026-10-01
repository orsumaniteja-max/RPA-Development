from unittest.mock import Mock

import pytest

from pages.cares_connect.dashboard_page import DashboardPage


@pytest.mark.parametrize("text,expected", [
    ("Displaying 1 - 10 out of 1512", True),
    ("Displaying 1501 - 1510 out of 1,512", True),
    ("Displaying 1511 - 1512 out of 1512", False),
    ("Displaying 0 - 0 out of 0", False),
])
def test_unlabelled_next_uses_result_range(text, expected):
    dashboard = DashboardPage.__new__(DashboardPage)
    dashboard.page = Mock()
    indicator = dashboard.page.get_by_text.return_value.first
    indicator.inner_text.return_value = text
    assert dashboard.has_next_page() is expected
    dashboard.page.locator.assert_not_called()


def test_unavailable_next_cannot_silently_truncate_results():
    dashboard = DashboardPage.__new__(DashboardPage)
    dashboard.page = Mock()
    indicator = dashboard.page.get_by_text.return_value.first
    indicator.inner_text.return_value = "Displaying 1 - 10 out of 1512"
    indicator.locator.return_value.locator.return_value.last.is_visible.return_value = False
    with pytest.raises(RuntimeError, match="10 of 1512"):
        dashboard.has_next_page()
