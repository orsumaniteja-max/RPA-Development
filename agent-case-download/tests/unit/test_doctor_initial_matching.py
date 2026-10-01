from dataclasses import replace

import pytest

from services.doctor_match_service import DoctorIdentity, DoctorIdentificationError, DoctorMatchService
from services.doctor_catalog_service import DoctorCatalogService
from services.doctor_validation_service import DoctorRecord


@pytest.mark.parametrize("left,right", [
    ("Erin Pender", "E Pender"), ("E. Pender", "Erin Pender"),
    ("Dr. Erin Pender", "e. PENDER"),
    ("Erin Van Pender", "E Van Pender"),
])
def test_first_initial_and_surname_match(left, right):
    result = DoctorMatchService().identify(
        DoctorIdentity(name=left), [DoctorIdentity(name=right, account_id="account")]
    )
    assert result.doctor.account_id == "account"
    assert result.field_scores["name"] == 100


@pytest.mark.parametrize("left,right", [
    ("Erin Pender", "A Pender"), ("Erin Pender", "E Smith"),
    ("Erin Pender", "Eric Pender"), ("Erin", "E"),
    ("", "E Pender"), (None, "E Pender"),
    ("Erin Van Pender", "E Pender"),
])
def test_initial_rule_does_not_promote_other_names(left, right):
    assert DoctorMatchService._name_score(left, right) < 100


@pytest.mark.parametrize("field,value,other", [
    ("email", "erin@north.example", "office@south.example"),
    ("phone", "212-555-1234", "415-555-9876"),
    ("address", "123 Oak Avenue Boston 02110", "987 Pine Road Seattle 98101"),
    ("practice", "North Dental Clinic", "South Surgery"),
])
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_initial_names_use_secondary_evidence(field, value, other, reverse):
    first = DoctorIdentity(name="E Pender", account_id="north")
    second = DoctorIdentity(name="E Pender", account_id="south")
    records = [replace(first, **{field: value}), replace(second, **{field: other})]
    if reverse:
        records.reverse()
    source = DoctorIdentity(name="Erin Pender", **{field: value})
    assert DoctorMatchService().identify(source, records).doctor.account_id == "north"


@pytest.mark.parametrize("shared", [{}, {"email": "shared@example.test"}, {"practice": "North Dental"}])
def test_unresolved_duplicate_initials_remain_ambiguous(shared):
    records = [DoctorIdentity(name="E Pender", account_id=value, **shared) for value in ("a", "b")]
    with pytest.raises(DoctorIdentificationError, match="ambiguous"):
        DoctorMatchService().identify(DoctorIdentity(name="Erin Pender", **shared), records)


def test_catalog_initial_match_maps_actual_account_and_duplicate_uses_fallback(tmp_path):
    catalog = DoctorCatalogService(tmp_path)
    catalog.records = [DoctorRecord("ACCOUNT", "E Pender", "", "", doctor_id="doctor")]
    payload = {"reference": "case-1", "customerAccount": {"prescriber": {"name": "Erin Pender"}}}
    assert catalog.apply(payload) is not None
    assert payload["customerAccount"]["prescriber"]["id"] == "ACCOUNT"
    assert "id" not in payload["customerAccount"]
    catalog.records.append(DoctorRecord("OTHER", "E Pender", "", "", doctor_id="other"))
    assert catalog.apply(payload) is None
    assert payload["customerAccount"]["prescriber"]["id"] not in {"ACCOUNT", "OTHER", ""}
