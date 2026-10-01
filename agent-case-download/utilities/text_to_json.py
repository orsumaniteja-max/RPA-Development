import re
import json
from pathlib import Path

class TextToJson:

    @staticmethod
    def convert(text):

        data = {}

        # Normalize line endings
        text = text.replace("\r", "")

        patterns = {
            "Case ID": r"(IO-\d+-\d+)",
            "Date": r"Date:\s*(.+)",
            "Due Date": r"Due date:\s*(.+)",
            "Laboratory": r"Laboratory:\s*(.+)",
            "Dentist": r"Dentist:\s*(.+)",
            "Patient": r"Patient:\s*(.+)"
        }

        for key, pattern in patterns.items():

            match = re.search(pattern, text)

            if match:
                data[key] = match.group(1).strip()
        return data
    def save_json(case_id, data):
        folder = Path("Output") / case_id
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / "case_details.json", "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False
            )