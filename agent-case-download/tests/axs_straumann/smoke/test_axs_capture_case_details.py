import pytest
import json
import re
from services.axs_straumann_case_capture_service import AxsStraumannCaseCaptureService
from services.background_result_validation_service import validate_application_results


@pytest.mark.smoke
@pytest.mark.axs_straumann
def test_axs_capture_case_details(page, portal_credentials, application_report_root):
    results = AxsStraumannCaseCaptureService(application_report_root).capture_all_cases(
        page, portal_credentials["username"], portal_credentials["password"]
    )
    for result in results:
        assert result.json_file.stem == result.case_id
        assert result.json_file.is_file()
        assert result.text_file.is_file()
        assert result.screenshot_file.is_file()
        payload = json.loads(result.json_file.read_text(encoding="utf-8"))
        order = payload["orderInformation"]
        assert {
            "submittedOn", "createdOn", "dueDate", "status", "doctor",
            "patient", "summary", "lab", "typeOfOrder", "sitesToRestore",
            "comment", "labSlip",
        }.issubset(order)
        clinic = payload["clinicInformation"]
        assert {"name", "phone", "email"}.issubset(clinic)
        prescriber = payload["customerAccount"]["prescriber"]
        assert prescriber["name"] == order["doctor"]
        assert prescriber["clinic"] == clinic
        if clinic["email"]:
            assert prescriber["contact"]["email"] == clinic["email"]
        elif prescriber["contact"]["email"]:
            assert re.fullmatch(
                r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
                prescriber["contact"]["email"],
                re.IGNORECASE,
            )
        assert prescriber["contact"]["phone"] == clinic["phone"]
        assert not clinic["email"] or re.fullmatch(
            r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
            clinic["email"],
            re.IGNORECASE,
        )
        assert "id" not in payload["patientInfo"]
        doctor_match = payload["doctorMatch"]
        if doctor_match["status"] == "matched":
            assert prescriber["id"]
            assert doctor_match["matchedId"] == prescriber["id"]
            assert doctor_match["matchedIdType"] in {"doctorId", "accountId"}
        else:
            assert doctor_match["status"] == "humanReviewRequired"
            assert doctor_match["reason"]
            assert prescriber["id"] == ""
    validate_application_results(application_report_root)
