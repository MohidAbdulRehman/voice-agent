"""Spoken forms and read-back groups in English and Spanish."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from intake.core.models import PatientCreate, PatientUpdate, Sex
from intake.core.speech import (
    readback,
    say_booking,
    say_characters,
    say_date,
    say_email,
    say_language,
    say_phone,
    say_slot,
    say_unit,
    say_zip,
    spell,
    update_readback,
)

AVERY = PatientCreate(
    first_name="Avery",
    last_name="Collins",
    date_of_birth=date(1988, 4, 12),
    sex=Sex.FEMALE,
    phone_number="2125550143",
    email="avery.collins@example.com",
    address_line_1="410 West 57th Street",
    address_line_2="Apt 12B",
    city="New York",
    state="NY",
    zip_code="10019",
    insurance_provider="Aetna",
    insurance_member_id="W123456789",
    preferred_language="English",
    emergency_contact_name="Jordan Collins",
    emergency_contact_phone="2125550187",
)
MINIMAL = PatientCreate(
    first_name="Jane",
    last_name="Davis",
    date_of_birth=date(1990, 3, 5),
    sex=Sex.DECLINE,
    phone_number="5125550100",
    address_line_1="1 Main St",
    city="Austin",
    state="TX",
    zip_code="78701",
)


@pytest.mark.parametrize(
    ("name", "language", "spoken"),
    [
        ("Davis", "English", "D-A-V-I-S"),
        ("O'Brien", "English", "O, apostrophe, B-R-I-E-N"),
        ("Smith-Jones", "Spanish", "S-M-I-T-H, guion, J-O-N-E-S"),
        ("Núñez", "Spanish", "N-Ú-Ñ-E-Z"),
    ],
)
def test_spell(name: str, language: str, spoken: str):
    assert spell(name, language) == spoken


def test_say_phone():
    assert say_phone("5125550100", "English") == "five one two, five five five, zero one zero zero"
    assert (
        say_phone("5125550100", "Spanish") == "cinco uno dos, cinco cinco cinco, cero uno cero cero"
    )


@pytest.mark.parametrize(
    ("day", "ordinal"),
    [
        (1, "1st"),
        (2, "2nd"),
        (3, "3rd"),
        (4, "4th"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (22, "22nd"),
        (23, "23rd"),
        (30, "30th"),
        (31, "31st"),
    ],
)
def test_say_date_ordinals(day: int, ordinal: str):
    assert say_date(date(2000, 1, day), "English") == f"January {ordinal}, 2000"


def test_say_date():
    assert say_date(date(1990, 3, 5), "English") == "March 5th, 1990"
    assert say_date(date(1990, 3, 5), "Spanish") == "5 de marzo de 1990"


@pytest.mark.parametrize(
    ("email", "language", "spoken"),
    [
        ("jane.doe@example.com", "English", "jane dot doe at example dot com"),
        (
            "jane_doe-1+x@example.com",
            "English",
            "jane underscore doe dash 1 plus x at example dot com",
        ),
        ("jane.doe@example.com", "Spanish", "jane punto doe arroba example punto com"),
        (
            "jane_doe-1@example.com",
            "Spanish",
            "jane guion bajo doe guion 1 arroba example punto com",
        ),
    ],
)
def test_say_email(email: str, language: str, spoken: str):
    assert say_email(email, language) == spoken


@pytest.mark.parametrize(
    ("line", "language", "spoken"),
    [
        ("Apt 12B", "English", "apartment 12B"),
        ("Apt. 12B", "English", "apartment 12B"),
        ("Apt 12B", "Spanish", "apartamento 12B"),
        ("Suite 300", "English", "suite 300"),
        ("Floor 2", "Spanish", "piso 2"),
        ("#4", "English", "unit 4"),
        ("12B", "English", "unit 12B"),
    ],
)
def test_say_unit(line: str, language: str, spoken: str):
    assert say_unit(line, language) == spoken


def test_say_zip():
    assert say_zip("78701", "English") == "seven eight seven zero one"
    assert say_zip("78701", "Spanish") == "siete ocho siete cero uno"
    assert say_zip("78701-1234", "English") == (
        "seven eight seven zero one, dash, one two three four"
    )


def test_say_characters():
    assert say_characters("W123", "English") == "W, one, two, three"
    assert say_characters("W123", "Spanish") == "W, uno, dos, tres"


def test_say_language():
    assert say_language("Spanish", "Spanish") == "español"
    assert say_language("English", "Spanish") == "inglés"
    assert say_language("Spanish", "English") == "Spanish"
    assert say_language("French", "Spanish") == "French"


def test_full_readback_in_english():
    groups = readback(AVERY, "English", language_given=True)

    assert [(g.group, g.spoken) for g in groups] == [
        ("name", "Avery Collins, that's C-O-L-L-I-N-S."),
        ("dob_sex", "Date of birth April 12th, 1988. Sex: Female."),
        (
            "phone_email",
            "Phone two one two, five five five, zero one four three."
            " Email avery dot collins at example dot com.",
        ),
        (
            "address",
            "Address 410 West 57th Street, apartment 12B, New York, New York,"
            " one zero zero one nine.",
        ),
        (
            "insurance",
            "Insurance Aetna. Member ID W, one, two, three, four, five, six, seven, eight, nine.",
        ),
        (
            "emergency_contact",
            "Emergency contact Jordan Collins, phone two one two, five five five, zero one eight seven.",
        ),
        ("language", "Preferred language English."),
    ]


def test_full_readback_in_spanish():
    groups = readback(AVERY, "Spanish", language_given=True)

    assert [(g.group, g.spoken) for g in groups] == [
        ("name", "Avery Collins, se escribe C-O-L-L-I-N-S."),
        ("dob_sex", "Fecha de nacimiento 12 de abril de 1988. Sexo: Femenino."),
        (
            "phone_email",
            "Teléfono dos uno dos, cinco cinco cinco, cero uno cuatro tres."
            " Correo electrónico avery punto collins arroba example punto com.",
        ),
        (
            "address",
            "Dirección 410 West 57th Street, apartamento 12B, New York, New York,"
            " uno cero cero uno nueve.",
        ),
        (
            "insurance",
            "Seguro Aetna. Número de miembro W, uno, dos, tres, cuatro, cinco, seis, siete, ocho, nueve.",
        ),
        (
            "emergency_contact",
            "Contacto de emergencia Jordan Collins, teléfono dos uno dos, cinco cinco cinco,"
            " cero uno ocho siete.",
        ),
        ("language", "Idioma preferido inglés."),
    ]


def test_readback_leaves_out_optional_groups_that_are_empty():
    groups = readback(MINIMAL, "English", language_given=False)

    assert [(g.group, g.spoken) for g in groups] == [
        ("name", "Jane Davis, that's D-A-V-I-S."),
        ("dob_sex", "Date of birth March 5th, 1990. Sex: Decline to answer."),
        ("phone_email", "Phone five one two, five five five, zero one zero zero."),
        ("address", "Address 1 Main St, Austin, Texas, seven eight seven zero one."),
    ]


def test_readback_includes_a_non_default_language_even_if_not_asked():
    patient = MINIMAL.model_copy(update={"preferred_language": "Spanish"})

    groups = readback(patient, "Spanish", language_given=False)

    assert groups[-1].group == "language"
    assert groups[-1].spoken == "Idioma preferido español."


def test_single_emergency_contact_detail():
    patient = MINIMAL.model_copy(update={"emergency_contact_phone": "2125550187"})

    groups = readback(patient, "English", language_given=False)

    assert groups[-1].spoken == (
        "Emergency contact phone two one two, five five five, zero one eight seven."
    )


def test_update_readback_has_only_the_changed_fields():
    changes = PatientUpdate(last_name="Davis", city="Dallas", address_line_2="Apt 4")

    english = update_readback(changes, "English")
    spanish = update_readback(changes, "Spanish")

    assert [(g.group, g.spoken) for g in english] == [
        ("name", "Last name Davis, that's D-A-V-I-S."),
        ("address", "Apartment 4. City Dallas."),
    ]
    assert [(g.group, g.spoken) for g in spanish] == [
        ("name", "Apellido Davis, se escribe D-A-V-I-S."),
        ("address", "Apartamento 4. Ciudad Dallas."),
    ]


EASTERN = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    ("starts_at", "english", "spanish"),
    [
        (  # 14:30 UTC is 10:30 in New York (daylight saving time)
            datetime(2026, 9, 29, 14, 30, tzinfo=UTC),
            "Tuesday, September 29th at 10:30 AM",
            "martes 29 de septiembre a las 10:30 de la mañana",
        ),
        (  # on the hour, no minutes; 1 PM is "la 1" in Spanish
            datetime(2026, 10, 1, 17, 0, tzinfo=UTC),
            "Thursday, October 1st at 1 PM",
            "jueves 1 de octubre a la 1 de la tarde",
        ),
        (  # after the switch to standard time, 14:00 UTC is 9 AM
            datetime(2026, 11, 2, 14, 0, tzinfo=UTC),
            "Monday, November 2nd at 9 AM",
            "lunes 2 de noviembre a las 9 de la mañana",
        ),
    ],
)
def test_say_slot_in_the_clinic_time_zone(starts_at: datetime, english: str, spanish: str):
    assert say_slot(starts_at, EASTERN, "English") == english
    assert say_slot(starts_at, EASTERN, "Spanish") == spanish


def test_say_booking_names_the_doctor():
    starts_at = datetime(2026, 9, 29, 14, 30, tzinfo=UTC)

    assert say_booking(starts_at, "Dr. Priya Shah", EASTERN, "English") == (
        "Tuesday, September 29th at 10:30 AM with Dr. Priya Shah"
    )
    assert say_booking(starts_at, "Dr. Elena Ruiz", EASTERN, "Spanish") == (
        "martes 29 de septiembre a las 10:30 de la mañana con Dr. Elena Ruiz"
    )
