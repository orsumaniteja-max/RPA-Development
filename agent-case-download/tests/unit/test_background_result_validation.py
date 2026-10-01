from services.background_result_validation_service import validate_application_results


def test_empty_results_are_valid_when_capture_has_no_new_cases(tmp_path):
    (tmp_path / "results").mkdir()
    validate_application_results(tmp_path)
