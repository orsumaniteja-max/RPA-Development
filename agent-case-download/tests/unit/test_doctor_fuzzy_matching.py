from services.doctor_catalog_service import DoctorCatalogService
import pytest
from unittest.mock import Mock

from services.doctor_match_service import (
    DoctorIdentificationError,
    DoctorIdentity,
    DoctorMatchService,
)
from services.doctor_validation_service import DoctorRecord


def _konstan_records():
    shared = {
        "address": "11 S Cleveland Ave, Mogadore, OH",
        "zip_code": "44260",
        "phone": "330-628-3017",
        "email": "info@mogadoredentist.com",
    }
    return [
        DoctorRecord(
            doctor_id="8CA0AF95-9271-456E-837D-F71152D78DEE",
            account_id="STARKCOLL",
            name="Dr. Louis Jeffrey Konstan",
            practice="",
            **shared,
        ),
        DoctorRecord(
            doctor_id="8DEC9329-3CD1-48DD-A6DC-9509AB422996",
            account_id="STARDENTAL",
            name="Dr. Louis William Konstan",
            practice="",
            **shared,
        ),
    ]


def test_fuzzy_match_uses_full_name_to_resolve_shared_contact_details():
    match = DoctorMatchService().identify(
        DoctorIdentity(
            name="Dr. Louis Jeffrey Konstan",
            email="info@mogadoredentist.com",
            address="11 S Cleveland Ave\n44260 Mogadore",
        ),
        _konstan_records(),
    )

    assert match.doctor.doctor_id == "8CA0AF95-9271-456E-837D-F71152D78DEE"
    assert match.field_scores["email"] == 100
    assert match.field_scores["zip_code"] == 100


def test_catalog_enriches_json_but_keeps_application_doctor_name(tmp_path):
    catalog = DoctorCatalogService(tmp_path)
    catalog.records = _konstan_records()
    payload = {
        "customerAccount": {
            "prescriber": {
                "name": "Konstan Louis",
                "contact": {
                    "displayName": "Konstan",
                    "email": "info@mogadoredentist.com",
                },
            }
        },
        "doctorInformation": {
            "address": "11 S Cleveland Ave\n44260 Mogadore\nAfghanistan"
        },
    }

    catalog.apply(payload, match_name="Dr. Louis Jeffrey Konstan")

    prescriber = payload["customerAccount"]["prescriber"]
    assert prescriber["name"] == "Konstan Louis"
    assert "id" not in payload["customerAccount"]
    assert prescriber["contact"]["email"] == "info@mogadoredentist.com"


def test_practice_resolves_doctors_with_the_same_name(tmp_path):
    catalog = DoctorCatalogService(tmp_path)
    catalog.records = [
        DoctorRecord("FIRST", "Dr. Eric Buck", "Third Street Dental Care", "first@example.com", doctor_id="1"),
        DoctorRecord("SECOND", "Dr. Eric Buck", "Distinctive Smiles of Dublin", "second@example.com", doctor_id="2"),
    ]
    payload = {
        "customerAccount": {
            "prescriber": {
                "name": "Dr. Eric Buck",
                "contact": {"displayName": "Eric", "email": ""},
            }
        }
    }

    catalog.apply(payload, practice="Distinctive Smiles of Dublin")

    prescriber = payload["customerAccount"]["prescriber"]
    assert "id" not in payload["customerAccount"]
    assert prescriber["contact"]["email"] == "second@example.com"


def test_database_address_columns_follow_doctor_table_schema():
    row = {
        "Address1": "601 S 3rd St",
        "Address2": "Suite 1",
        "Address3": "Columbus",
        "Address4": "OH",
        "Address5": "43206",
        "Telephone": "614-228-4850",
    }

    assert DoctorCatalogService._address(row) == (
        "601 S 3rd St, Suite 1, Columbus, OH, 43206"
    )
    assert DoctorCatalogService._field(row, "Telephone", "Phone") == "614-228-4850"


def test_catalog_uses_account_id_when_doctor_id_is_unavailable(tmp_path):
    catalog = DoctorCatalogService(tmp_path)
    catalog.records = [
        DoctorRecord(
            account_id="ACCOUNT-42",
            doctor_id="",
            name="Dr. Jane Smith",
            practice="North Clinic",
            email="jane@example.com",
        )
    ]
    payload = {
        "customerAccount": {
            "prescriber": {
                "name": "Jane Smith",
                "contact": {"displayName": "Jane", "email": "jane@example.com"},
            }
        }
    }

    catalog.apply(payload, practice="North Clinic")

    assert "id" not in payload["customerAccount"]
    assert catalog.last_match is not None


def test_unmatched_doctor_is_sent_to_human_review_notifier():
    notifier = Mock()
    matcher = DoctorMatchService(notifier=notifier)

    with pytest.raises(DoctorIdentificationError):
        matcher.identify_or_notify(
            DoctorIdentity(name="Unknown Doctor", practice="Unknown Clinic"),
            _konstan_records(),
        )

    notifier.send.assert_called_once()
