"""Spoken forms for the read-back, generated in code so digits and spellings are exact.

The voice agent reads these strings verbatim, so the LLM never spells a name or
says a digit on its own (docs/specs/data-model.md, "Spoken forms").
"""

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from intake.core.models import PatientCreate, PatientUpdate, Sex
from intake.core.states import STATE_NAMES

SpokenLanguage = Literal["English", "Spanish"]


class ReadbackGroup(BaseModel):
    """One breath of the read-back, e.g. the name with the last name spelled."""

    model_config = ConfigDict(frozen=True)

    group: str
    spoken: str


_DIGITS: dict[SpokenLanguage, tuple[str, ...]] = {
    "English": ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"),
    "Spanish": ("cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"),
}
_MONTHS: dict[SpokenLanguage, tuple[str, ...]] = {
    "English": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "Spanish": (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ),
}
_WEEKDAYS: dict[SpokenLanguage, tuple[str, ...]] = {
    "English": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "Spanish": ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"),
}
_SEX: dict[SpokenLanguage, dict[Sex, str]] = {
    "English": {
        Sex.MALE: "Male",
        Sex.FEMALE: "Female",
        Sex.OTHER: "Other",
        Sex.DECLINE: "Decline to answer",
    },
    "Spanish": {
        Sex.MALE: "Masculino",
        Sex.FEMALE: "Femenino",
        Sex.OTHER: "Otro",
        Sex.DECLINE: "Prefiere no decirlo",
    },
}
_NAME_PUNCTUATION: dict[SpokenLanguage, dict[str, str]] = {
    "English": {"-": "hyphen", "'": "apostrophe"},
    "Spanish": {"-": "guion", "'": "apóstrofo"},
}
_EMAIL_SYMBOLS: dict[SpokenLanguage, dict[str, str]] = {
    "English": {".": "dot", "@": "at", "_": "underscore", "-": "dash", "+": "plus"},
    "Spanish": {".": "punto", "@": "arroba", "_": "guion bajo", "-": "guion", "+": "más"},
}
# Unit designators in address line 2, and what to say for them. "#12B" says "unit 12B".
_UNIT_WORDS: dict[SpokenLanguage, dict[str, str]] = {
    "English": {
        "apt": "apartment",
        "apartment": "apartment",
        "unit": "unit",
        "#": "unit",
        "ste": "suite",
        "suite": "suite",
        "fl": "floor",
        "floor": "floor",
        "rm": "room",
        "room": "room",
        "bldg": "building",
        "building": "building",
    },
    "Spanish": {
        "apt": "apartamento",
        "apartment": "apartamento",
        "unit": "unidad",
        "#": "unidad",
        "ste": "suite",
        "suite": "suite",
        "fl": "piso",
        "floor": "piso",
        "rm": "cuarto",
        "room": "cuarto",
        "bldg": "edificio",
        "building": "edificio",
    },
}
_UNIT_DESIGNATOR = re.compile(
    r"(?i)(apt|apartment|unit|ste|suite|fl|floor|rm|room|bldg|building)\b\.?\s*|#\s*"
)
_LANGUAGE_NAMES: dict[SpokenLanguage, dict[str, str]] = {
    "English": {},
    "Spanish": {"English": "inglés", "Spanish": "español"},
}
_WORDS: dict[SpokenLanguage, dict[str, str]] = {
    "English": {
        "spelled": "that's",
        "dash": "dash",
        "address": "Address",
        "contact": "Emergency contact",
        "contact_phone": "phone",
    },
    "Spanish": {
        "spelled": "se escribe",
        "dash": "guion",
        "address": "Dirección",
        "contact": "Contacto de emergencia",
        "contact_phone": "teléfono",
    },
}
# How each changed field is announced; "{}" is the spoken value.
_PHRASES: dict[SpokenLanguage, dict[str, str]] = {
    "English": {
        "first_name": "First name {}.",
        "last_name": "Last name {}.",
        "date_of_birth": "Date of birth {}.",
        "sex": "Sex: {}.",
        "phone_number": "Phone {}.",
        "email": "Email {}.",
        "address_line_1": "Street address {}.",
        "address_line_2": "{}.",
        "city": "City {}.",
        "state": "State {}.",
        "zip_code": "ZIP code {}.",
        "insurance_provider": "Insurance {}.",
        "insurance_member_id": "Member ID {}.",
        "emergency_contact_name": "Emergency contact {}.",
        "emergency_contact_phone": "Emergency contact phone {}.",
        "preferred_language": "Preferred language {}.",
    },
    "Spanish": {
        "first_name": "Nombre {}.",
        "last_name": "Apellido {}.",
        "date_of_birth": "Fecha de nacimiento {}.",
        "sex": "Sexo: {}.",
        "phone_number": "Teléfono {}.",
        "email": "Correo electrónico {}.",
        "address_line_1": "Dirección {}.",
        "address_line_2": "{}.",
        "city": "Ciudad {}.",
        "state": "Estado {}.",
        "zip_code": "Código postal {}.",
        "insurance_provider": "Seguro {}.",
        "insurance_member_id": "Número de miembro {}.",
        "emergency_contact_name": "Contacto de emergencia {}.",
        "emergency_contact_phone": "Teléfono del contacto de emergencia {}.",
        "preferred_language": "Idioma preferido {}.",
    },
}
# Read-back groups in reading order (one group per breath).
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("name", ("first_name", "last_name")),
    ("dob_sex", ("date_of_birth", "sex")),
    ("phone_email", ("phone_number", "email")),
    ("address", ("address_line_1", "address_line_2", "city", "state", "zip_code")),
    ("insurance", ("insurance_provider", "insurance_member_id")),
    ("emergency_contact", ("emergency_contact_name", "emergency_contact_phone")),
    ("language", ("preferred_language",)),
)


def spell(name: str, language: SpokenLanguage) -> str:
    """Spell a name: ``Davis`` → ``D-A-V-I-S``; ``O'Brien`` → ``O, apostrophe, B-R-I-E-N``."""
    words = []
    for part in re.split(r"(['-])", name):
        if part in _NAME_PUNCTUATION[language]:
            words.append(_NAME_PUNCTUATION[language][part])
        elif part:
            words.append("-".join(part.upper()))
    return ", ".join(words)


def say_digits(digits: str, language: SpokenLanguage) -> str:
    """Say each digit: ``787`` → ``seven eight seven``."""
    return " ".join(_DIGITS[language][int(digit)] for digit in digits)


def say_phone(phone: str, language: SpokenLanguage) -> str:
    """Say a 10-digit number in 3-3-4 groups: ``five one two, five five five, zero one zero zero``."""
    return ", ".join(say_digits(group, language) for group in (phone[:3], phone[3:6], phone[6:]))


def say_date(day: date, language: SpokenLanguage) -> str:
    """``March 5th, 1990`` in English; ``5 de marzo de 1990`` in Spanish."""
    month = _MONTHS[language][day.month - 1]
    if language == "Spanish":
        return f"{day.day} de {month} de {day.year}"
    return f"{month} {_ordinal(day.day)}, {day.year}"


def _ordinal(day: int) -> str:
    return f"{day}{'th' if 11 <= day <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')}"


def say_slot(starts_at: datetime, zone: ZoneInfo, language: SpokenLanguage) -> str:
    """An appointment time at the clinic: ``Tuesday, September 29th at 10:30 AM``.

    In Spanish: ``martes 29 de septiembre a las 10:30 de la mañana``. On the hour,
    the minutes are left out (``at 9 AM``, ``a las 9 de la mañana``).
    """
    local = starts_at.astimezone(zone)
    hour = local.hour % 12 or 12
    clock = f"{hour}:{local.minute:02d}" if local.minute else str(hour)
    weekday = _WEEKDAYS[language][local.weekday()]
    month = _MONTHS[language][local.month - 1]
    if language == "Spanish":
        part = (
            "de la mañana"
            if local.hour < 12
            else "de la tarde"
            if local.hour < 19
            else "de la noche"
        )
        article = "la" if hour == 1 else "las"
        return f"{weekday} {local.day} de {month} a {article} {clock} {part}"
    return (
        f"{weekday}, {month} {_ordinal(local.day)} at {clock} {'AM' if local.hour < 12 else 'PM'}"
    )


def say_booking(
    starts_at: datetime, doctor_name: str, zone: ZoneInfo, language: SpokenLanguage
) -> str:
    """A booked appointment: ``Tuesday, September 29th at 10:30 AM with Dr. Priya Shah``."""
    with_word = "con" if language == "Spanish" else "with"
    return f"{say_slot(starts_at, zone, language)} {with_word} {doctor_name}"


def say_email(email: str, language: SpokenLanguage) -> str:
    """``jane.doe@example.com`` → ``jane dot doe at example dot com``."""
    symbols = _EMAIL_SYMBOLS[language]
    return " ".join("".join(f" {symbols[c]} " if c in symbols else c for c in email).split())


def say_unit(address_line_2: str, language: SpokenLanguage) -> str:
    """``Apt 12B`` → ``apartment 12B``; a bare ``12B`` → ``unit 12B``."""
    words = _UNIT_WORDS[language]
    match = _UNIT_DESIGNATOR.match(address_line_2)
    if match is None:
        return f"{words['unit']} {address_line_2}"
    designator = (match.group(1) or "#").casefold()
    return f"{words[designator]} {address_line_2[match.end() :]}".strip()


def say_zip(zip_code: str, language: SpokenLanguage) -> str:
    """``78701`` → ``seven eight seven zero one``; ZIP+4 adds ``dash`` and the last four."""
    five, _, four = zip_code.partition("-")
    spoken = say_digits(five, language)
    return f"{spoken}, {_WORDS[language]['dash']}, {say_digits(four, language)}" if four else spoken


def say_characters(value: str, language: SpokenLanguage) -> str:
    """Say an ID character by character: ``W123`` → ``W, one, two, three``."""
    return ", ".join(_DIGITS[language][int(c)] if c.isdigit() else c for c in value)


def say_language(value: str, language: SpokenLanguage) -> str:
    """Name a language the way the caller's language does: ``Spanish`` → ``español``."""
    return _LANGUAGE_NAMES[language].get(value, value)


def _as_is(value: str, _language: SpokenLanguage) -> str:
    return value


def _say_last_name(value: str, language: SpokenLanguage) -> str:
    return f"{value}, {_WORDS[language]['spelled']} {spell(value, language)}"


def _say_sex(value: Sex, language: SpokenLanguage) -> str:
    return _SEX[language][value]


def _say_state(value: str, _language: SpokenLanguage) -> str:
    return STATE_NAMES[value]


def _say_unit_sentence(value: str, language: SpokenLanguage) -> str:
    spoken = say_unit(value, language)
    return spoken[:1].upper() + spoken[1:]


_SAY: dict[str, Callable[[Any, SpokenLanguage], str]] = {
    "first_name": _as_is,
    "last_name": _say_last_name,
    "date_of_birth": say_date,
    "sex": _say_sex,
    "phone_number": say_phone,
    "email": say_email,
    "address_line_1": _as_is,
    "address_line_2": _say_unit_sentence,
    "city": _as_is,
    "state": _say_state,
    "zip_code": say_zip,
    "insurance_provider": _as_is,
    "insurance_member_id": say_characters,
    "emergency_contact_name": _as_is,
    "emergency_contact_phone": say_phone,
    "preferred_language": say_language,
}


def _phrase(field: str, value: object, language: SpokenLanguage) -> str:
    return _PHRASES[language][field].format(_SAY[field](value, language))


def _phrases(values: dict[str, Any], fields: tuple[str, ...], language: SpokenLanguage) -> str:
    return " ".join(_phrase(f, values[f], language) for f in fields if values.get(f) is not None)


def _name_text(patient: PatientCreate, language: SpokenLanguage) -> str:
    return f"{patient.first_name} {_say_last_name(patient.last_name, language)}."


def _address_text(patient: PatientCreate, language: SpokenLanguage) -> str:
    parts = [patient.address_line_1]
    if patient.address_line_2:
        parts.append(say_unit(patient.address_line_2, language))
    parts += [patient.city, STATE_NAMES[patient.state], say_zip(patient.zip_code, language)]
    return f"{_WORDS[language]['address']} {', '.join(parts)}."


def _contact_text(patient: PatientCreate, language: SpokenLanguage) -> str | None:
    words = _WORDS[language]
    name, phone = patient.emergency_contact_name, patient.emergency_contact_phone
    if name and phone:
        return f"{words['contact']} {name}, {words['contact_phone']} {say_phone(phone, language)}."
    if name or phone:
        values = patient.model_dump()
        return _phrases(values, ("emergency_contact_name", "emergency_contact_phone"), language)
    return None


def readback(
    patient: PatientCreate, language: SpokenLanguage, *, language_given: bool
) -> list[ReadbackGroup]:
    """Read-back for a new patient, in reading order.

    Optional groups appear only when given; preferred language only when the
    caller gave it or it isn't the default.
    """
    values = patient.model_dump()
    show_language = language_given or patient.preferred_language != "English"
    texts = {
        "name": _name_text(patient, language),
        "dob_sex": _phrases(values, ("date_of_birth", "sex"), language),
        "phone_email": _phrases(values, ("phone_number", "email"), language),
        "address": _address_text(patient, language),
        "insurance": _phrases(values, ("insurance_provider", "insurance_member_id"), language),
        "emergency_contact": _contact_text(patient, language),
        "language": _phrase("preferred_language", patient.preferred_language, language)
        if show_language
        else None,
    }
    return [ReadbackGroup(group=group, spoken=text) for group, text in texts.items() if text]


def update_readback(changes: PatientUpdate, language: SpokenLanguage) -> list[ReadbackGroup]:
    """Read-back for an update: only the changed fields, in reading order."""
    values = changes.changes()
    groups = []
    for group, fields in _GROUPS:
        text = _phrases(values, tuple(f for f in fields if f in values), language)
        if text:
            groups.append(ReadbackGroup(group=group, spoken=text))
    return groups
