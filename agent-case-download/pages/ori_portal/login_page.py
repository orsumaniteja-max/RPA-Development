from pages.common.base_page import BasePage
from loguru import logger
from utilities.allure_helper import step
import allure 

class LoginPage(BasePage):

    USERNAME = "[name='username']"
    PASSWORD = "[name='password']"
    LOGIN = "button[type='submit']"

    @allure.step("Login with username: {username}")
    def login(self, username, password):
        self.type(self.USERNAME, username, "user name")
        self.type(self.PASSWORD, password, "password")
        self.click(self.LOGIN)
        logger.info("Successfully login into the application")
