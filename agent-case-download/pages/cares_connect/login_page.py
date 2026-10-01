from pages.common.base_page import BasePage
from loguru import logger
from utilities.allure_helper import step
import allure

class LoginPage(BasePage):

    USERNAME = "#loginUsername"
    PASSWORD = "#loginPassword"
    LOGIN = "input[type='submit']"

    @allure.step("Login with username: {username}")
    def login(self, username, password):
        self.type(self.USERNAME, username, "user name")
        self.type(self.PASSWORD, password, "password")
        self.click(self.LOGIN)
        self.wait_for_load()
        logger.info("Successfully login into the application")

