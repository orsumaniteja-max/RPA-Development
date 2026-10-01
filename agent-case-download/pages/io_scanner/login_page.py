from pages.common.base_page import BasePage
from loguru import logger
from utilities.allure_helper import step
import allure 
import re

class LoginPage(BasePage):

    USERNAME = "[id='form_item_loginName']"
    PASSWORD = "[type='password']"
    LOGIN = "button:has-text('Log in'), button:has-text('login.login')"
    COOKIES="//*[text()='Accept cookies']"

    @allure.step("Login with username: {username}")
    def login(self, username, password):
        self.page.wait_for_function(
            """() => document.querySelector('#form_item_loginName')
                || document.body.innerText.includes('Accept cookies')
                || document.body.innerText.includes('cookieModal.enum13')""",
            timeout=90000,
        )
        cookies = self.page.locator(self.COOKIES)
        if cookies.count() and cookies.first.is_visible():
            self.click(self.COOKIES)
        elif not self.page.locator(self.USERNAME).is_visible():
            accept = self.page.get_by_text(
                re.compile(r"^(Accept cookies|login\.cookieModal\.enum13)$")
            )
            if accept.count() and accept.last.is_visible():
                accept.last.click()
        self.page.locator(self.USERNAME).wait_for(state="visible")
        self.type(self.USERNAME, username, "user name")
        self.type(self.PASSWORD, password, "password")
        self.click(self.LOGIN)
        logger.info("Successfully login into the application")
