from pages.common.base_page import BasePage


class TrackPage(BasePage):

    SEARCH = "input[type='text']"

    SEARCH_BUTTON = "text=Search"

    REFRESH = "text=Refresh"

    def search_order(self, order):

        self.type(self.SEARCH, order)

        self.click(self.SEARCH_BUTTON)

    def refresh(self):

        self.click(self.REFRESH)
