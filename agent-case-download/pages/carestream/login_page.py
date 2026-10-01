from pages.common.base_page import BasePage
from loguru import logger
from utilities.allure_helper import step
import allure 
import re

class LoginPage(BasePage):

    USERNAME = "#signInName"
    NEXT="#next"
    PASSWORD = "#password"
    LOGIN = "button[type='submit']"

    @allure.step("Login with username: {username}")
    def login(self, username, password):
        self.type(self.USERNAME, username, "user name")
        self.click(self.NEXT)
        self.type(self.PASSWORD, password, "password")
        self.page.locator(self.NEXT).click(no_wait_after=True)
        self.page.wait_for_url(
            re.compile(r"^https://csdentalconnect\.com(?:/|$)"),
            wait_until="domcontentloaded",
            timeout=180000,
        )
        self.page.locator("#caseId").wait_for(state="visible", timeout=180000)
        logger.info("Successfully login into the application")

