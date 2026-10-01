from loguru import logger
from playwright.sync_api import expect
import os


class BasePage:

    PAGE_LOAD_STATE = "load"

    def __init__(self, page):
        self.page = page
        self.wait_for_page_load()

    def wait_for_page_load(self, timeout=None):
        """Wait until the current document has finished loading."""
        logger.debug(f"Waiting for page load state: {self.PAGE_LOAD_STATE}")
        self.page.wait_for_load_state(
            self.PAGE_LOAD_STATE,
            timeout=timeout,
        )

    # ==========================
    # Browser Actions
    # ==========================

    def open_url(self, url):
        logger.info(f"Opening URL : {url}")
        self.page.goto(url, wait_until=self.PAGE_LOAD_STATE)

    def refresh(self):
        logger.info("Refreshing browser")
        self.page.reload(wait_until=self.PAGE_LOAD_STATE)

    def go_back(self):
        logger.info("Navigating Back")
        self.page.go_back(wait_until=self.PAGE_LOAD_STATE)

    def go_forward(self):
        logger.info("Navigating Forward")
        self.page.go_forward(wait_until=self.PAGE_LOAD_STATE)

    def get_title(self):
        title = self.page.title()
        logger.info(f"Page Title : {title}")
        return title

    def get_current_url(self):
        url = self.page.url
        logger.info(f"Current URL : {url}")
        return url

    # ==========================
    # Click Actions
    # ==========================

    def click(self, locator, action_name=None, index=None):

        element = self.page.locator(locator)

        if index is None:
            element.first.click()
        else:
            element.nth(index).click()

        self.wait_for_page_load()
        logger.success(f"Clicked : {action_name if action_name else locator}")

    def double_click(self, locator):

        self.page.locator(locator).first.dblclick()
        logger.success(f"Double clicked : {locator}")

    def right_click(self, locator):

        self.page.locator(locator).first.click(button="right")
        logger.success(f"Right clicked : {locator}")

    def hover(self, locator):

        self.page.locator(locator).first.hover()
        logger.success(f"Hovered : {locator}")

    # ==========================
    # Textbox Actions
    # ==========================

    def type(self, locator, value, field_name=""):

        self.page.locator(locator).fill(value)
        logger.info(f"Entered value into {field_name or locator}")

    def clear(self, locator):

        self.page.locator(locator).clear()
        logger.info(f"Cleared : {locator}")

    def append_text(self, locator, value):

        self.page.locator(locator).press_sequentially(value)
        logger.info(f"Appended : {value}")

    # ==========================
    # Dropdown
    # ==========================

    def select_by_text(self, locator, text):

        self.page.locator(locator).select_option(label=text)
        logger.info(f"Selected Text : {text}")

    def select_by_value(self, locator, value):

        self.page.locator(locator).select_option(value=value)
        logger.info(f"Selected Value : {value}")

    def select_by_index(self, locator, index):

        self.page.locator(locator).select_option(index=index)
        logger.info(f"Selected Index : {index}")

    # ==========================
    # Checkbox
    # ==========================

    def check(self, locator):

        self.page.locator(locator).check()
        logger.info("Checkbox checked")

    def uncheck(self, locator):

        self.page.locator(locator).uncheck()
        logger.info("Checkbox unchecked")

    def is_checked(self, locator):

        return self.page.locator(locator).is_checked()

    # ==========================
    # Keyboard
    # ==========================

    def press_key(self, locator, key):

        self.page.locator(locator).press(key)
        logger.info(f"Pressed : {key}")

    def keyboard_press(self, key):

        self.page.keyboard.press(key)

    # ==========================
    # Mouse
    # ==========================

    def mouse_click(self, x, y):

        self.page.mouse.click(x, y)

    def mouse_move(self, x, y):

        self.page.mouse.move(x, y)

    # ==========================
    # Upload
    # ==========================

    def upload_file(self, locator, file_path):

        self.page.locator(locator).set_input_files(file_path)
        logger.info(f"Uploaded : {os.path.basename(file_path)}")

    # ==========================
    # Waits
    # ==========================

    def wait_for_element(self, locator, timeout=30000):

        self.page.locator(locator).wait_for(timeout=timeout)

    def wait_for_load(self, timeout=None):
        """Backward-compatible alias for the framework page-load wait."""
        self.wait_for_page_load(timeout=timeout)

    def wait(self, milliseconds):

        self.page.wait_for_timeout(milliseconds)

    # ==========================
    # Text
    # ==========================

    def get_body_text(self, locator, field_name="", index=None):

        text = self.page.locator(locator).inner_text() 
    
        text = text.strip() if text else ""

        logger.info(f"{field_name} : {text}")

        return text

    def get_text(self, locator, field_name="", index=None):
    
            element = self.page.locator(locator)
    
            if index is None:
                text = element.first.text_content()
            else:
                text = element.nth(index).text_content()
    
            text = text.strip() if text else ""
    
            logger.info(f"{field_name} : {text}")
    
            return text
    

    def get_attribute(self, locator, attribute):

        value = self.page.locator(locator).get_attribute(attribute)

        logger.info(f"{attribute} : {value}")

        return value

    # ==========================
    # Visibility
    # ==========================

    def is_visible(self, locator):

        return self.page.locator(locator).is_visible()

    def is_enabled(self, locator):

        return self.page.locator(locator).is_enabled()

    def is_disabled(self, locator):

        return self.page.locator(locator).is_disabled()

    def is_editable(self, locator):

        return self.page.locator(locator).is_editable()

    # ==========================
    # Assertions
    # ==========================

    def verify_visible(self, locator):

        expect(self.page.locator(locator)).to_be_visible()
        logger.success("Element is visible")

    def verify_hidden(self, locator):

        expect(self.page.locator(locator)).to_be_hidden()

    def verify_enabled(self, locator):

        expect(self.page.locator(locator)).to_be_enabled()

    def verify_disabled(self, locator):

        expect(self.page.locator(locator)).to_be_disabled()

    def verify_text(self, locator, expected):

        expect(self.page.locator(locator)).to_have_text(expected)

        logger.success(f"Verified text : {expected}")

    def verify_contains_text(self, locator, expected):

        expect(self.page.locator(locator)).to_contain_text(expected)

    def verify_value(self, locator, expected):

        expect(self.page.locator(locator)).to_have_value(expected)

    def verify_title(self, expected):

        expect(self.page).to_have_title(expected)

    def verify_url(self, expected):

        expect(self.page).to_have_url(expected)

    # ==========================
    # Screenshot
    # ==========================

    def take_screenshot(self, path):

        self.page.screenshot(path=path, full_page=True)

        logger.info(f"Screenshot saved : {path}")

    # ==========================
    # Scrolling
    # ==========================

    def scroll_into_view(self, locator):

        self.page.locator(locator).scroll_into_view_if_needed()

    def scroll_to_bottom(self):

        self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    def scroll_to_top(self):

        self.page.evaluate("window.scrollTo(0,0)")

    def get_locator(self, locator):
        return self.page.locator(locator)

    def get_locator_count(self, locator):
        count = self.page.locator(locator).count()
        logger.info(f"Locator Count : {count}")
        return count

    def get_first_locator(self, locator):
        return self.page.locator(locator).first

    def get_last_locator(self, locator):
        return self.page.locator(locator).last

    def get_nth_locator(self, locator, index):
        return self.page.locator(locator).nth(index)

    def drag_and_drop(self, source, target):
        self.page.locator(source).drag_to(
            self.page.locator(target)
        )
        logger.success("Drag and Drop completed")
    def get_frame(self, frame_locator):
        return self.page.frame_locator(frame_locator)

    def switch_frame(self, frame_name):
        return self.page.frame(name=frame_name)

    def switch_frame_by_url(self, url):
        return self.page.frame(url=url)

    def get_pages(self):
        return self.page.context.pages

    def switch_to_tab(self, index):
        pages = self.page.context.pages
        pages[index].bring_to_front()
        pages[index].wait_for_load_state(self.PAGE_LOAD_STATE)
        logger.info(f"Switched to tab {index}")
        return pages[index]

    def close_current_tab(self):
        self.page.close()

    def download_file(self, click_locator, save_path):
        with self.page.expect_download() as download_info:
            self.click(click_locator)
        download = download_info.value
        download.save_as(save_path)
        logger.success(f"Downloaded : {save_path}")

    def execute_js(self, script):
        return self.page.evaluate(script)

    def execute_js_on_element(self, locator, script):
        element = self.page.locator(locator)
        return element.evaluate(script)
    
    def focus(self, locator):
        self.page.locator(locator).focus()
        logger.info("Focused on element")

    def highlight(self, locator):
        self.page.locator(locator).evaluate("""
            element => {
                element.style.border='3px solid red';
            }
        """)

    def get_local_storage(self, key):
        return self.page.evaluate(
            f"localStorage.getItem('{key}')"
        )

    def set_local_storage(self, key, value):
        self.page.evaluate(
            f"localStorage.setItem('{key}','{value}')"
        )

    def clear_local_storage(self):
        self.page.evaluate("localStorage.clear()")

    def get_cookies(self):
        return self.page.context.cookies()

    def clear_cookies(self):
        self.page.context.clear_cookies()

    def get_inner_html(self, locator):
        return self.page.locator(locator).inner_html()

    def get_outer_html(self, locator):
        return self.page.locator(locator).evaluate(
            "e=>e.outerHTML"
        )

    def get_css_value(self, locator, property_name):
        return self.page.locator(locator).evaluate(
            f"e=>getComputedStyle(e).getPropertyValue('{property_name}')"
        )

    def capture_element(self, locator, path):
        self.page.locator(locator).screenshot(path=path)
        logger.success(path)

    def wait_until_visible(self, locator):
        expect(self.page.locator(locator)).to_be_visible()

    def wait_until_hidden(self, locator):
        expect(self.page.locator(locator)).to_be_hidden()

    def retry_click(self, locator, retries=3):
        for attempt in range(retries):
            try:
                self.click(locator)
                return
            except Exception:
                if attempt == retries - 1:
                    raise

    def dynamic_locator(self, locator, *args):
        return locator.format(*args)

    def get_table_rows(self, locator):
        return self.page.locator(locator).count()

    def get_table_text(self, locator,field_name=""):
        return self.page.locator(locator).all_inner_texts()

    def click_table_row(self, locator, row):
        self.page.locator(locator).nth(row).click()
        self.wait_for_page_load()

    def get_cell_text(self, locator, row):
        return self.page.locator(locator).nth(row).text_content()

    def wait_until_enabled(self, locator):
        expect(self.page.locator(locator)).to_be_enabled()

    def wait_until_disabled(self, locator):
        expect(self.page.locator(locator)).to_be_disabled()

    def accept_alert(self):
        self.page.once(
            "dialog",
            lambda dialog: dialog.accept()
        )

    def dismiss_alert(self):
        self.page.once(
            "dialog",
            lambda dialog: dialog.dismiss()
        )

    def choose_file(self, locator, filepath):
        with self.page.expect_file_chooser() as fc:
            self.click(locator)
        chooser = fc.value
        chooser.set_files(filepath)

    def wait_for_response(self, url):
        return self.page.wait_for_response(url)

    def wait_for_request(self, url):
        return self.page.wait_for_request(url)

    def verify_count(self, locator, count):
        expect(self.page.locator(locator)).to_have_count(count)

    def verify_attribute(self, locator, attribute, value):
        expect(
            self.page.locator(locator)
        ).to_have_attribute(attribute, value)

    def get_all_texts(self, locator):
        return self.page.locator(locator).all_inner_texts()

    def get_all_values(self, locator):
        return self.page.locator(locator).evaluate_all(
            "elements => elements.map(e => e.value)"
        )

    def scroll_by(self, x, y):
        self.page.mouse.wheel(x, y)
