from pathlib import Path
import json

from utilities.file_helper import FileHelper
from services.standard_case_payload_service import StandardCasePayloadService


class CaseExportService:
    @staticmethod
    def export(page, case_information, reports_root):

        payload = StandardCasePayloadService.build(case_information)

        case_id = payload["patientInfo"]["id"] or "unknown-case"

        folder = Path(reports_root) / str(case_id)

        FileHelper.create_folder(folder)

        txt_file = folder / "reference.txt"
        json_file = folder / "case_details.json"
        screenshot = folder / "case.png"

        # -----------------------------
        # Text File
        # -----------------------------

        content = ""

        for section, values in case_information.items():

            content += f"\n[{section}]\n"

            if isinstance(values, dict):

                for key, value in values.items():
                    content += f"{key:<22}: {value}\n"

            elif isinstance(values, list):

                if not values:
                    content += "No Data\n"
                else:
                    for idx, record in enumerate(values, 1):
                        content += f"\nRecord {idx}\n"
                        for key, value in record.items():
                            content += f"{key:<22}: {value}\n"

            else:
                content += f"{values}\n"
        # -----------------------------
        # JSON
        # -----------------------------

        with open(json_file, "w", encoding="utf-8") as file:

            json.dump(
                payload,
                file,
                indent=4,
                ensure_ascii=False
            )

        # -----------------------------
        # Screenshot
        # -----------------------------

        page.screenshot(
            path=str(screenshot),
            full_page=True
        )

        txt_file = folder / "case_details.txt"

        # Generate text from JSON
        content = ""

        for section, values in payload.items():

            content += f"{section}\n"
            content += "-" * len(section) + "\n"

            if isinstance(values, dict):

                for key, value in values.items():
                    content += f"{key:<25}: {value}\n"

            elif isinstance(values, list):

                if not values:
                    content += "No Data\n"

                else:

                    for i, item in enumerate(values, start=1):

                        # If the list contains dictionaries
                        if isinstance(item, dict):

                            # Show "Record" only if there are multiple items
                            if len(values) > 1:
                                content += f"\nRecord {i}\n"

                            for key, value in item.items():
                                content += f"{key:<25}: {value}\n"

                        else:
                            content += f"{item}\n"

            else:
                content += f"{values}\n"

            content += "\n"

        FileHelper.write_text(txt_file, content)
