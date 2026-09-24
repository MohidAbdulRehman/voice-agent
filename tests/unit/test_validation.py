"""Field rules, normalization and error codes from docs/specs/data-model.md."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from intake.core.models import PatientUpdate, Sex, ValidationFailed
from intake.core.validation import (
    ValidationContext,
    as_input,
    clean_field,
    clinic_today,
    validate_new_patient,
    validate_patient_changes,
)
from tests.cases import REJECTED, VALID_INPUT, Rejected

TODAY = date(2026, 9, 24)
API = ValidationContext(today=TODAY)
AGENT = ValidationContext(today=TODAY, accept_state_names=True)
EASTERN = ZoneInfo("America/New_York")


def new_patient_errors(
    data: dict[str, object], ctx: ValidationContext = API
) -> list[tuple[str | None, str]]:
    with pytest.raises(ValidationFailed) as excinfo:
        validate_new_patient(data, ctx)
    return [(error.field, error.code) for error in excinfo.value.errors]


def update_errors(data: dict[str, object]) -> list[tuple[str | None, str]]:
    with pytest.raises(ValidationFailed) as excinfo:
        validate_patient_changes(data, API)
    return [(error.field, error.code) for error in excinfo.value.errors]


@pytest.mark.parametrize("example", REJECTED, ids=lambda e: f"{e.field}={e.value[:24]!r}")
def test_rejected_examples(example: Rejected):
    data = {**VALID_INPUT, example.field: example.value}

    assert new_patient_errors(data) == [(example.field, example.code)]


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("first_name", "José", "José"),
        ("first_name", "Jose\N{COMBINING ACUTE ACCENT}", "José"),  # composed by NFC
        ("first_name", "O'Brien", "O'Brien"),
        ("first_name", "o\N{RIGHT SINGLE QUOTATION MARK}brien", "O'Brien"),
        ("first_name", "de'andre", "De'Andre"),
        ("first_name", "A" * 50, "A" + "a" * 49),
        ("last_name", "Smith-Jones", "Smith-Jones"),
        ("last_name", "SMITH-JONES", "Smith-Jones"),
        ("last_name", "McDonald", "McDonald"),
        ("last_name", "mcdonald", "Mcdonald"),
        ("last_name", "  Doe\N{NO-BREAK SPACE}", "Doe"),
        ("date_of_birth", "02/29/2024", date(2024, 2, 29)),
        ("date_of_birth", "01/01/1900", date(1900, 1, 1)),
        ("date_of_birth", "09/24/2026", TODAY),
        ("sex", "female", Sex.FEMALE),
        ("sex", "DECLINE TO  ANSWER", Sex.DECLINE),
        ("phone_number", "(512) 555-0100", "5125550100"),
        ("phone_number", "+1 512 555 0100", "5125550100"),
        ("phone_number", "512.555.0100", "5125550100"),
        ("email", "Jane.Doe@Example.COM", "Jane.Doe@example.com"),
        ("address_line_1", "1   Main\tSt\n", "1 Main St"),
        ("address_line_1", "A" * 200, "A" * 200),
        ("address_line_2", "Apt 12B", "Apt 12B"),
        ("state", "tx", "TX"),
        ("state", " pr ", "PR"),
        ("zip_code", "78701", "78701"),
        ("zip_code", "78701-1234", "78701-1234"),
        ("zip_code", "787011234", "78701-1234"),
        ("zip_code", "78701 1234", "78701-1234"),
        ("insurance_member_id", "w123-456 789", "W123456789"),
        ("preferred_language", "español", "Spanish"),
        ("preferred_language", "SPANISH", "Spanish"),
        ("preferred_language", "Inglés", "English"),
        ("preferred_language", "haitian creole", "Haitian Creole"),
        (
            "emergency_contact_name",
            "Mary-Ann O\N{RIGHT SINGLE QUOTATION MARK}Neil Jr.",
            "Mary-Ann O'Neil Jr.",
        ),
        ("emergency_contact_phone", "212-555-0187", "2125550187"),
    ],
)
def test_accepted_values_are_normalized(field: str, raw: str, expected: object):
    patient = validate_new_patient({**VALID_INPUT, field: raw}, API)

    assert getattr(patient, field) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("texas", "TX"),
        ("New York", "NY"),
        ("Puerto Rico", "PR"),
        ("District of Columbia", "DC"),
        ("Washington, D.C.", "DC"),
        ("Washington", "WA"),
        ("u.s. virgin islands", "VI"),
    ],
)
def test_agent_may_name_the_state(raw: str, expected: str):
    assert validate_new_patient({**VALID_INPUT, "state": raw}, AGENT).state == expected


@pytest.mark.parametrize("value", ["Aus\x00tin", "\x1b[31mAustin", "Aus\x7ftin"])
def test_control_characters_are_rejected(value: str):
    assert new_patient_errors({**VALID_INPUT, "city": value}) == [("city", "invalid_characters")]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_blank_required_fields_are_required(value: str | None):
    assert new_patient_errors({**VALID_INPUT, "city": value}) == [("city", "required")]


def test_missing_required_fields_are_required():
    data = {k: v for k, v in VALID_INPUT.items() if k not in {"sex", "zip_code"}}

    assert new_patient_errors(data) == [("sex", "required"), ("zip_code", "required")]


def test_blank_optional_fields_become_null():
    patient = validate_new_patient({**VALID_INPUT, "email": "  ", "address_line_2": ""}, API)

    assert patient.email is None
    assert patient.address_line_2 is None


def test_preferred_language_defaults_to_english():
    assert validate_new_patient(VALID_INPUT, API).preferred_language == "English"


def test_every_problem_is_reported_in_field_order():
    data = {**VALID_INPUT, "date_of_birth": "09/25/2026"}
    del data["last_name"]

    with pytest.raises(ValidationFailed) as excinfo:
        validate_new_patient(data, API)

    assert [(e.field, e.code, e.message) for e in excinfo.value.errors] == [
        ("last_name", "required", "Last name is required."),
        ("date_of_birth", "in_future", "Date of birth can't be in the future."),
    ]


def test_unexpected_fields_are_reported_first():
    data = {**VALID_INPUT, "patient_id": "x", "source_call_id": "x", "sex": "F"}

    assert new_patient_errors(data) == [
        ("patient_id", "read_only"),
        ("source_call_id", "unknown_field"),
        ("sex", "invalid_value"),
    ]


@pytest.mark.parametrize("value", [123, True, ["Jane"]])
def test_non_string_values_are_invalid_type(value: object):
    assert new_patient_errors({**VALID_INPUT, "first_name": value}) == [
        ("first_name", "invalid_type")
    ]


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 25, 2, 0, tzinfo=UTC), date(2026, 9, 24)),  # 10 PM on the 24th, Eastern
        (datetime(2026, 9, 25, 5, 0, tzinfo=UTC), date(2026, 9, 25)),  # 1 AM on the 25th, Eastern
    ],
)
def test_today_is_the_clinic_date_not_the_utc_date(now: datetime, expected: date):
    assert clinic_today(now, EASTERN) == expected


def test_tomorrow_in_the_clinic_is_in_the_future_even_when_it_is_today_in_utc():
    late_evening_eastern = datetime(2026, 9, 25, 2, 0, tzinfo=UTC)
    ctx = ValidationContext(today=clinic_today(late_evening_eastern, EASTERN))

    assert new_patient_errors({**VALID_INPUT, "date_of_birth": "09/25/2026"}, ctx) == [
        ("date_of_birth", "in_future")
    ]


def test_update_changes_only_the_fields_given():
    changes = validate_patient_changes({"city": " Dallas ", "email": None}, API)

    assert changes.changes() == {"city": "Dallas", "email": None}


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, [(None, "empty_update")]),
        ({"last_name": None}, [("last_name", "required")]),
        ({"last_name": "  "}, [("last_name", "required")]),
        ({"preferred_language": None}, [("preferred_language", "required")]),
        ({"patient_id": "x", "city": "Dallas"}, [("patient_id", "read_only")]),
        ({"date_of_birth": "01/01/2999"}, [("date_of_birth", "in_future")]),
    ],
)
def test_update_rejections(data: dict[str, object], expected: list[tuple[str | None, str]]):
    assert update_errors(data) == expected


def test_update_blank_optional_field_clears_it():
    assert validate_patient_changes({"email": " "}, API).changes() == {"email": None}


def test_clean_field_normalizes_one_value():
    assert clean_field("phone_number", "+1 (512) 555-0100", API) == "5125550100"


def test_clean_field_raises_the_fields_error():
    with pytest.raises(ValidationFailed) as excinfo:
        clean_field("phone_number", "555-0100", API)

    assert [(e.field, e.code) for e in excinfo.value.errors] == [("phone_number", "invalid_phone")]


def test_as_input_round_trips_through_validation():
    patient = validate_new_patient({**VALID_INPUT, "email": "jane@example.com"}, API)
    payload = as_input(patient)

    assert payload["date_of_birth"] == "03/05/1990"
    assert payload["sex"] == "Female"
    assert validate_new_patient(payload, API) == patient


def test_as_input_of_an_update_keeps_only_the_changes():
    changes = PatientUpdate(date_of_birth=date(1990, 3, 5), email=None)

    assert as_input(changes) == {"date_of_birth": "03/05/1990", "email": None}
