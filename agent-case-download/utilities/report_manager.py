import os
import shutil


class ReportManager:

    @staticmethod
    def clean():

        paths = [
            "reports/screenshots",
            "reports/logs",
            "reports/allure-results",
            "reports/allure-report"
        ]

        files = [
            "reports/report.html"
        ]

        for path in paths:
            if os.path.exists(path):
                shutil.rmtree(path)

        for file in files:
            if os.path.exists(file):
                os.remove(file)

        os.makedirs("reports/screenshots", exist_ok=True)
        os.makedirs("reports/logs", exist_ok=True)