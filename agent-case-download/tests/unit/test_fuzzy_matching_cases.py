"""Offline score and decision contracts using the real fuzzy matching library."""

import pytest

from services.doctor_match_service import (
    DoctorIdentificationError,
    DoctorIdentity,
    DoctorMatchService,
)


@pytest.fixture
def candidate():
    return DoctorIdentity(
        doctor_id="doctor-1", name="Jane Smith", practice="North Dental Clinic"
    )


# Literal expected scores deliberately do not call the scorer to compute an oracle.
# None means identify() must reject the input instead of returning a match.
@pytest.mark.parametrize(
    "name,clinic,name_score,clinic_score,method,confidence",
    [
        pytest.param("Jane Smith", "North Dental Clinic", 100, 100, "strict", 100, id="exact"),
        pytest.param("Dr. JANE SMITH", "North Dental Clinic", 100, 100, "strict", 100, id="title-and-case"),
        pytest.param("Doctor Jane Smith (DDS)", "North Dental Clinic", 100, 100, "strict", 100, id="title-and-suffix"),
        pytest.param("Jane  Smith", "North-Dental Clinic", 100, 100, "strict", 100, id="spacing-and-punctuation"),
        pytest.param("Smith Jane", "Clinic Dental North", 100, 100, "fuzzy", 100, id="reordered-tokens"),
        pytest.param("Jane Smyth", "North Dental Clinic", 90, 100, "fuzzy", 94, id="doctor-typo"),
        pytest.param("Jane Smith", "North Dental Clinc", 100, 97, "fuzzy", 98.8, id="clinic-typo"),
        pytest.param("Jane Smyth", "North Dental Clinc", 90, 97, "fuzzy", 92.8, id="both-typos"),
        pytest.param("Jane Smith", "North Dental", 100, 100, "fuzzy", 100, id="clinic-token-subset"),
        pytest.param("John Brown", "North Dental Clinic", 30, 100, None, None, id="different-doctor"),
        pytest.param("Jane", "North Dental Clinic", 57, 100, None, None, id="incomplete-doctor"),
        pytest.param("Jane Smith", "XYZ", 100, 0, "fuzzy", 60, id="clinic-mismatch-is-not-a-veto"),
        pytest.param("", "North Dental Clinic", 0, 100, "strict", 100, id="clinic-only"),
        pytest.param("Jane Smyth", "", 90, 0, "fuzzy", 90, id="doctor-only"),
        pytest.param("", "", 0, 0, None, None, id="empty-identity"),
    ],
)
def test_doctor_clinic_scores_and_decisions(
    candidate, name, clinic, name_score, clinic_score, method, confidence
):
    matcher = DoctorMatchService()
    source = DoctorIdentity(name=name, practice=clinic)

    # Rejected candidates have no public match result, so inspect field scores
    # separately to verify similarity even for no-match cases.
    scores = matcher._scores(source, candidate)
    assert scores["name"] == name_score
    assert scores["practice"] == clinic_score

    if method is None:
        reason = "No doctor identity fields" if not name and not clinic else "No candidate met"
        with pytest.raises(DoctorIdentificationError, match=reason):
            matcher.identify(source, [candidate])
    else:
        result = matcher.identify(source, [candidate])
        assert result.doctor == candidate
        assert result.method == method
        assert result.confidence == pytest.approx(confidence)
        assert result.field_scores == scores


@pytest.mark.parametrize("threshold,expected_match", [(89, True), (90, True), (91, False)])
def test_name_threshold_boundary(candidate, threshold, expected_match):
    matcher = DoctorMatchService(name_threshold=threshold)
    source = DoctorIdentity(name="Jane Smyth", practice="North Dental Clinic")
    if expected_match:
        result = matcher.identify(source, [candidate])
        assert result.field_scores["name"] == 90
        assert result.confidence == 94
        assert result.method == "fuzzy"
    else:
        with pytest.raises(DoctorIdentificationError, match="No candidate met"):
            matcher.identify(source, [candidate])


@pytest.mark.parametrize("reverse", [False, True], ids=["original-order", "reversed-order"])
def test_clinic_selects_same_name_doctor_independent_of_order(candidate, reverse):
    other = DoctorIdentity(doctor_id="doctor-2", name="Jane Smith", practice="XYZ")
    records = [candidate, other]
    if reverse:
        records.reverse()
    result = DoctorMatchService().identify(
        DoctorIdentity(name="Jane Smyth", practice="North Dental Clinic"), records
    )
    assert result.doctor.doctor_id == "doctor-1"
    assert result.method == "fuzzy"
    assert result.confidence == 94
    assert result.field_scores["practice"] == 100


@pytest.mark.parametrize("name", ["Jane Smith", "Jane Smyth"], ids=["strict-tie", "fuzzy-tie"])
def test_duplicate_names_and_clinics_require_review(candidate, name):
    duplicate = DoctorIdentity(
        doctor_id="doctor-2", name=candidate.name, practice=candidate.practice
    )
    with pytest.raises(DoctorIdentificationError, match="Fuzzy matching is ambiguous"):
        DoctorMatchService().identify(
            DoctorIdentity(name=name, practice=candidate.practice), [candidate, duplicate]
        )


@pytest.mark.parametrize(
    "records", [[], [DoctorIdentity(name="Jane Smith", practice="North Dental Clinic")]],
    ids=["empty-catalog", "record-without-id"],
)
def test_no_usable_records_is_no_match(records):
    with pytest.raises(DoctorIdentificationError, match="no usable doctor records"):
        DoctorMatchService().identify(DoctorIdentity(name="Jane Smith"), records)
