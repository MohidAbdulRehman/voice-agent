"""Validation examples shared by the unit tests and the database parity tests."""

from dataclasses import dataclass

# A complete, valid new patient, in the form the API and the agent send.
VALID_INPUT: dict[str, str] = {
    "first_name": "Jane",
    "last_name": "Doe",
    "date_of_birth": "03/05/1990",
    "sex": "Female",
    "phone_number": "(512) 555-0100",
    "address_line_1": "1 Main St",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701",
}


@dataclass(frozen=True)
class Rejected:
    """An input the rules reject with ``code``.

    ``constraint`` names the database constraint that rejects the same value
    when it's inserted directly, or is None for a rule only Python enforces.
    """

    field: str
    value: str
    code: str
    constraint: str | None


REJECTED: tuple[Rejected, ...] = (
    Rejected("first_name", "", "required", "first_name_valid"),
    Rejected("first_name", "Van Buren", "invalid_characters", "first_name_valid"),
    Rejected("first_name", "Jane2", "invalid_characters", "first_name_valid"),
    Rejected("first_name", "J.", "invalid_characters", "first_name_valid"),
    Rejected("first_name", "-Jane", "invalid_characters", "first_name_valid"),
    Rejected("first_name", "Jane-", "invalid_characters", "first_name_valid"),
    Rejected("first_name", "A" * 51, "too_long", "first_name_valid"),
    Rejected("last_name", "O'", "invalid_characters", "last_name_valid"),
    Rejected("last_name", "Doe Smith", "invalid_characters", "last_name_valid"),
    Rejected("last_name", "D" * 51, "too_long", "last_name_valid"),
    # The database checks only ASCII punctuation and the ends of a name.
    Rejected("last_name", "Doe--Smith", "invalid_characters", None),
    Rejected("last_name", "Doe™", "invalid_characters", None),
    Rejected("date_of_birth", "12/31/1899", "too_old", "dob_valid"),
    Rejected("date_of_birth", "01/01/2999", "in_future", "dob_valid"),
    # Format and calendar checks happen before a value can become a DATE.
    Rejected("date_of_birth", "02/29/2023", "not_a_real_date", None),
    Rejected("date_of_birth", "13/01/1990", "not_a_real_date", None),
    Rejected("date_of_birth", "1990-03-05", "invalid_format", None),
    Rejected("date_of_birth", "3/5/1990", "invalid_format", None),
    # The sex_type enum rejects these too, with a type error (tests/db/test_parity.py).
    Rejected("sex", "F", "invalid_value", None),
    Rejected("phone_number", "5550100", "invalid_phone", "phone_valid"),
    Rejected("phone_number", "1125550100", "invalid_area_code", "phone_valid"),
    Rejected("phone_number", "0125550100", "invalid_area_code", "phone_valid"),
    Rejected("phone_number", "5121550100", "invalid_phone", "phone_valid"),
    Rejected("email", "jane.doe", "invalid_email", "email_valid"),
    Rejected("email", "jane@example", "invalid_email", "email_valid"),
    Rejected("email", "a" * 243 + "@example.com", "invalid_email", "email_valid"),
    Rejected("address_line_1", "A" * 201, "too_long", "address_line_1_valid"),
    Rejected("address_line_2", "A" * 101, "too_long", "address_line_2_valid"),
    Rejected("city", "A" * 101, "too_long", "city_valid"),
    Rejected("state", "ZZ", "invalid_state", "state_valid"),
    Rejected("state", "Texas", "invalid_state", "state_valid"),
    Rejected("zip_code", "7870", "invalid_zip", "zip_valid"),
    Rejected("zip_code", "78701-12", "invalid_zip", "zip_valid"),
    Rejected("zip_code", "ABCDE", "invalid_zip", "zip_valid"),
    Rejected("insurance_provider", "A" * 101, "too_long", "insurance_provider_valid"),
    Rejected("insurance_member_id", "W123!", "invalid_member_id", "insurance_member_id_valid"),
    Rejected("insurance_member_id", "A" * 31, "invalid_member_id", "insurance_member_id_valid"),
    Rejected("preferred_language", "A" * 51, "too_long", "preferred_language_valid"),
    Rejected(
        "emergency_contact_name", "Jordan 2", "invalid_characters", "emergency_contact_name_valid"
    ),
    Rejected("emergency_contact_name", "A" * 101, "too_long", "emergency_contact_name_valid"),
    Rejected(
        "emergency_contact_phone", "5550100", "invalid_phone", "emergency_contact_phone_valid"
    ),
    Rejected(
        "emergency_contact_phone",
        "1125550100",
        "invalid_area_code",
        "emergency_contact_phone_valid",
    ),
)
