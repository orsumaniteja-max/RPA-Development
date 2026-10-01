from playwright.sync_api import Page, expect


class LabOrdersPage:
    RECORDS = "[data-cy='customOrderId']"
    NEXT = (
        "button[aria-label*='next' i]:visible:not([disabled]):not([aria-disabled='true']), "
        "a[aria-label*='next' i]:visible:not([aria-disabled='true']):not(.disabled):not(.disabled a)"
    )

    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> None:
        navigation = self.page.get_by_role(
            "link", name="Lab orders", exact=False
        ).or_(self.page.get_by_text("Lab orders", exact=False))
        navigation.first.click()
        self.page.locator(self.RECORDS).first.wait_for(
            state="visible", timeout=90000
        )

    def record_count(self) -> int:
        return self.page.locator(self.RECORDS).count()

    def record_id(self, index: int) -> str:
        return self.page.locator(self.RECORDS).nth(index).inner_text().strip()

    def open_record(self, index: int, order_id: str | None = None) -> str:
        record = self.page.locator(self.RECORDS).nth(index)
        record.scroll_into_view_if_needed()
        order_id = order_id or record.inner_text().strip()
        record.click()
        self.page.locator('[data-cy="caseOwner"]').wait_for(
            state="visible", timeout=90000
        )
        self.page.wait_for_function(
            """orderId => {
                const body = document.body?.innerText || '';
                const owner = document.querySelector('[data-cy="caseOwner"]')
                    ?.innerText?.trim() || '';
                return body.includes(orderId) && owner.length > 3;
            }""",
            arg=order_id,
            timeout=90000,
        )
        return order_id

    def return_to_orders(self) -> None:
        link = self.page.get_by_text("Lab orders", exact=False)
        if link.count() and link.first.is_visible():
            link.first.click()
        else:
            self.page.go_back(wait_until="domcontentloaded")
        self.page.locator(self.RECORDS).first.wait_for(
            state="visible", timeout=90000
        )

    def has_next_page(self) -> bool:
        control = self.page.locator(self.NEXT)
        return bool(control.count() and control.first.is_visible() and control.first.is_enabled())

    def next_page(self) -> None:
        first = self.page.locator(self.RECORDS).first
        previous = first.inner_text()
        self.page.locator(self.NEXT).first.click()
        expect(first).not_to_have_text(previous, timeout=90000)
        first.wait_for(state="visible", timeout=90000)
